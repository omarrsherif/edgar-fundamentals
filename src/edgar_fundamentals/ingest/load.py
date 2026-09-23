"""Parse one FSDS quarter into Parquet.

ZIP -> data/extracted/<q>/<file>.txt (UTF-8 sanitized) -> DuckDB read_csv with explicit types
-> data/parquet/<q>/<file>.parquet (written to .tmp then atomically renamed).

The manifest records rows parsed, rows rejected, bytes and wall-clock per phase, so the ingest is
idempotent (complete quarters are skipped) and resumable (a failed quarter restarts from the ZIP).
"""
from __future__ import annotations

import io
import os
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from edgar_fundamentals import config, db
from edgar_fundamentals.ingest import manifest
from edgar_fundamentals.log import get_logger

log = get_logger("edgar.load")

FILES = ["sub", "num", "tag", "pre"]

# Expected header rows. Verified against 2024q3 (sub.txt gained `accepted` in 2020).
EXPECTED_COLUMNS: dict[str, list[str]] = {
    "sub": [
        "adsh", "cik", "name", "sic", "countryba", "stprba", "cityba", "zipba", "bas1", "bas2", "baph",
        "countryma", "stprma", "cityma", "zipma", "mas1", "mas2", "countryinc", "stprinc", "ein", "former",
        "changed", "afs", "wksi", "fye", "form", "period", "fy", "fp", "filed", "accepted", "prevrpt",
        "detail", "instance", "nciks", "aciks",
    ],
    "num": ["adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg", "value", "footnote"],
    "tag": ["tag", "version", "custom", "abstract", "datatype", "iord", "crdr", "tlabel", "doc"],
    "pre": ["adsh", "report", "line", "stmt", "inpth", "rfile", "tag", "version", "plabel", "negating"],
}

# DuckDB types. Dates are kept as the raw YYYYMMDD text here and cast in the warehouse layer so a bad
# date never rejects a whole row; leading-zero codes (fye, zip, ein) stay VARCHAR.
COLUMN_TYPES: dict[str, dict[str, str]] = {
    "sub": {
        "adsh": "VARCHAR", "cik": "BIGINT", "name": "VARCHAR", "sic": "INTEGER", "countryba": "VARCHAR",
        "stprba": "VARCHAR", "cityba": "VARCHAR", "zipba": "VARCHAR", "bas1": "VARCHAR", "bas2": "VARCHAR",
        "baph": "VARCHAR", "countryma": "VARCHAR", "stprma": "VARCHAR", "cityma": "VARCHAR", "zipma": "VARCHAR",
        "mas1": "VARCHAR", "mas2": "VARCHAR", "countryinc": "VARCHAR", "stprinc": "VARCHAR", "ein": "VARCHAR",
        "former": "VARCHAR", "changed": "VARCHAR", "afs": "VARCHAR", "wksi": "INTEGER", "fye": "VARCHAR",
        "form": "VARCHAR", "period": "VARCHAR", "fy": "INTEGER", "fp": "VARCHAR", "filed": "VARCHAR",
        "accepted": "VARCHAR", "prevrpt": "INTEGER", "detail": "INTEGER", "instance": "VARCHAR",
        "nciks": "INTEGER", "aciks": "VARCHAR",
    },
    "num": {
        "adsh": "VARCHAR", "tag": "VARCHAR", "version": "VARCHAR", "ddate": "VARCHAR", "qtrs": "INTEGER",
        "uom": "VARCHAR", "segments": "VARCHAR", "coreg": "VARCHAR", "value": "DOUBLE", "footnote": "VARCHAR",
    },
    "tag": {
        "tag": "VARCHAR", "version": "VARCHAR", "custom": "INTEGER", "abstract": "INTEGER", "datatype": "VARCHAR",
        "iord": "VARCHAR", "crdr": "VARCHAR", "tlabel": "VARCHAR", "doc": "VARCHAR",
    },
    "pre": {
        "adsh": "VARCHAR", "report": "INTEGER", "line": "INTEGER", "stmt": "VARCHAR", "inpth": "INTEGER",
        "rfile": "VARCHAR", "tag": "VARCHAR", "version": "VARCHAR", "plabel": "VARCHAR", "negating": "INTEGER",
    },
}


class HeaderMismatch(RuntimeError):
    pass


@dataclass
class LoadResult:
    quarter: str
    cached: bool
    rows: dict[str, int] = field(default_factory=dict)
    rejects: dict[str, int] = field(default_factory=dict)
    extracted_bytes: int = 0
    extract_seconds: float = 0.0
    parse_seconds: float = 0.0
    parquet_bytes: int = 0

    @property
    def total_rows(self) -> int:
        return sum(self.rows.values())

    @property
    def rows_per_second(self) -> float:
        return self.total_rows / self.parse_seconds if self.parse_seconds else 0.0


def verify_header(header_line: str, name: str) -> None:
    cols = header_line.rstrip("\r\n").split("\t")
    expected = EXPECTED_COLUMNS[name]
    if cols != expected:
        raise HeaderMismatch(
            f"{name}.txt header differs from expected.\n  got:      {cols}\n  expected: {expected}"
        )


def extract_sanitized(zip_path: Path, out_dir: Path) -> tuple[int, dict[str, int]]:
    """Copy the four txt members out of the ZIP, replacing invalid UTF-8 with U+FFFD.

    Returns (total bytes written, newline counts per file) so parse row counts can be cross-checked.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    newlines: dict[str, int] = {}
    with zipfile.ZipFile(zip_path) as z:
        for name in FILES:
            member = f"{name}.txt"
            target = out_dir / member
            tmp = out_dir / (member + ".tmp")
            lines = 0
            with z.open(member) as raw, open(tmp, "w", encoding="utf-8", newline="") as out:
                reader = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
                first = reader.readline()
                verify_header(first, name)
                out.write(first)
                lines += first.count("\n")
                while True:
                    chunk = reader.read(1 << 20)
                    if not chunk:
                        break
                    lines += chunk.count("\n")
                    out.write(chunk)
            os.replace(tmp, target)
            total += target.stat().st_size
            newlines[name] = lines
    return total, newlines


def _read_csv_sql(path: Path, name: str) -> str:
    cols = ", ".join(f"'{c}': '{t}'" for c, t in COLUMN_TYPES[name].items())
    return (
        f"read_csv({db.sql_path_literal(path)}, delim='\\t', header=true, quote='', escape='', "
        f"columns={{{cols}}}, null_padding=true, store_rejects=true, "
        f"rejects_table='rejects_{name}', rejects_scan='rejects_scan_{name}', "
        f"strict_mode=false, sample_size=-1)"
    )


def parse_quarter(quarter: str, extracted_dir: Path, parquet_dir: Path) -> tuple[dict[str, int], dict[str, int], int]:
    """Parse the sanitized txt files into Parquet with DuckDB. Returns (rows, rejects, parquet bytes)."""
    parquet_dir.mkdir(parents=True, exist_ok=True)
    con = db.connect(":memory:")
    rows: dict[str, int] = {}
    rejects: dict[str, int] = {}
    pq_bytes = 0
    try:
        for name in FILES:
            src = extracted_dir / f"{name}.txt"
            target = parquet_dir / f"{name}.parquet"
            tmp = parquet_dir / f"{name}.parquet.tmp"
            con.execute(f"CREATE OR REPLACE TABLE stage_{name} AS SELECT *, '{quarter}' AS dataset_quarter "
                        f"FROM {_read_csv_sql(src, name)}")
            rows[name] = db.row_count(con, f"stage_{name}")
            try:
                rejects[name] = con.execute(f"SELECT count(*) FROM rejects_{name}").fetchone()[0]
            except Exception:
                rejects[name] = 0
            con.execute(f"COPY stage_{name} TO {db.sql_path_literal(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD)")
            con.execute(f"DROP TABLE stage_{name}")
            os.replace(tmp, target)
            pq_bytes += target.stat().st_size
    finally:
        con.close()
    return rows, rejects, pq_bytes


def is_loaded(quarter: str) -> bool:
    entry = manifest.get(quarter)
    if entry.get("parse_status") != "complete":
        return False
    pq = config.path("parquet_dir") / quarter
    return all((pq / f"{n}.parquet").exists() for n in FILES)


def load_quarter(quarter: str, zip_path: Path | None = None, force: bool = False,
                 drop_extracted: bool = False) -> LoadResult:
    zip_path = zip_path or (config.path("raw_dir") / f"{quarter}.zip")
    parquet_dir = config.path("parquet_dir") / quarter
    extracted_dir = config.path("extracted_dir") / quarter

    if is_loaded(quarter) and not force:
        e = manifest.get(quarter)
        log.info("%s: parquet cached (%d rows)", quarter, sum(e.get("rows", {}).values()))
        return LoadResult(quarter, cached=True, rows=e.get("rows", {}), rejects=e.get("rejects", {}),
                          extracted_bytes=e.get("extracted_bytes", 0), extract_seconds=e.get("extract_seconds", 0.0),
                          parse_seconds=e.get("parse_seconds", 0.0), parquet_bytes=e.get("parquet_bytes", 0))

    manifest.update(quarter, parse_status="running")
    t0 = time.perf_counter()
    extracted_bytes, newlines = extract_sanitized(zip_path, extracted_dir)
    t1 = time.perf_counter()
    rows, rejects, pq_bytes = parse_quarter(quarter, extracted_dir, parquet_dir)
    t2 = time.perf_counter()

    # Cross-check: parsed + rejected must account for every data line.
    max_reject_rate = config.settings()["ingest"]["max_reject_rate"]
    for name in FILES:
        data_lines = newlines[name] - 1
        accounted = rows[name] + rejects[name]
        if accounted != data_lines:
            log.warning("%s: %s.txt line accounting differs: %d parsed + %d rejected != %d data lines",
                        quarter, name, rows[name], rejects[name], data_lines)
        if data_lines and rejects[name] / data_lines > max_reject_rate:
            manifest.update(quarter, parse_status="failed",
                            error=f"{name}.txt reject rate {rejects[name] / data_lines:.5f} exceeds {max_reject_rate}")
            raise RuntimeError(f"{quarter}: {name}.txt reject rate too high ({rejects[name]}/{data_lines})")

    if drop_extracted:
        shutil.rmtree(extracted_dir, ignore_errors=True)

    res = LoadResult(quarter, cached=False, rows=rows, rejects=rejects, extracted_bytes=extracted_bytes,
                     extract_seconds=t1 - t0, parse_seconds=t2 - t1, parquet_bytes=pq_bytes)
    manifest.update(quarter, parse_status="complete", rows=rows, rejects=rejects, newlines=newlines,
                    extracted_bytes=extracted_bytes, extract_seconds=round(res.extract_seconds, 3),
                    parse_seconds=round(res.parse_seconds, 3), parquet_bytes=pq_bytes,
                    rows_per_second=round(res.rows_per_second, 1))
    log.info("%s: parsed %s rows (%s rejected) in %.1fs extract + %.1fs parse = %.0f rows/s; parquet %.1f MB",
             quarter, f"{res.total_rows:,}", sum(rejects.values()), res.extract_seconds, res.parse_seconds,
             res.rows_per_second, pq_bytes / 1e6)
    return res
