"""DuckDB connection helpers and SQL-file runner."""
from __future__ import annotations

import re
from pathlib import Path
from string import Template

import duckdb

from edgar_fundamentals import config


def connect(path: Path | str | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the warehouse (or any DuckDB file / ':memory:') with the configured pragmas."""
    # duckdb's Python bindings import pandas lazily on the FIRST parameter bind of a process (measured
    # 560-740 ms once per process; see bench/plans/before/company_search_bisection.txt). Importing it here
    # moves that cost into connection set-up, where it is reported as such, instead of into whichever
    # parameterised query happens to run first. The cost is moved, not removed (bench/OPTIMIZATION.md).
    import pandas  # noqa: F401

    path = str(path) if path is not None else str(config.path("warehouse"))
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(path, read_only=read_only)
    dd = config.settings()["duckdb"]
    con.execute(f"SET memory_limit='{dd['memory_limit']}'")
    con.execute(f"SET threads={int(dd['threads'])}")
    tmp = config.path("temp_dir")
    tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET enable_progress_bar=false")
    return con


def sql_path_literal(p: Path | str) -> str:
    """Posix-style path literal safe to embed in SQL (DuckDB accepts forward slashes on Windows)."""
    return "'" + Path(p).as_posix().replace("'", "''") + "'"


def render_sql(text: str, params: dict | None = None) -> str:
    """Substitute ${name} placeholders. Plain '$' elsewhere is left alone."""
    if not params:
        return text
    return Template(text).safe_substitute(params)


def split_statements(text: str) -> list[str]:
    """Split SQL on ';' outside single-quoted strings and -- comments."""
    stmts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":  # escaped quote
                    buf.append("'")
                    i += 1
                else:
                    in_str = False
        elif ch == "'":
            in_str = True
            buf.append(ch)
        elif ch == "-" and i + 1 < n and text[i + 1] == "-":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def run_sql_file(con: duckdb.DuckDBPyConnection, path: Path, params: dict | None = None) -> None:
    text = render_sql(Path(path).read_text(encoding="utf-8"), params)
    for stmt in split_statements(text):
        con.execute(stmt)


def table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()[0] > 0


def row_count(con: duckdb.DuckDBPyConnection, name: str) -> int:
    return con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
