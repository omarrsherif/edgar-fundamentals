"""Loader: header verification, UTF-8 sanitizing, parse + parquet round trip, idempotence."""
from __future__ import annotations

import zipfile
from pathlib import Path

import duckdb
import pytest

from edgar_fundamentals.ingest import load

SUB_HEADER = "\t".join(load.EXPECTED_COLUMNS["sub"])
NUM_HEADER = "\t".join(load.EXPECTED_COLUMNS["num"])
TAG_HEADER = "\t".join(load.EXPECTED_COLUMNS["tag"])
PRE_HEADER = "\t".join(load.EXPECTED_COLUMNS["pre"])


def make_zip(path: Path, bad_bytes: bool = False, bad_header: bool = False) -> Path:
    sub_row = ["0000000001-25-000001", "1", "TEST CO", "3571"] + [""] * 20 + ["1231", "10-K", "20241231", "2024", "FY",
               "20250215", "2025-02-15 10:00:00.0", "0", "1", "t-20241231.htm", "1", ""]
    assert len(sub_row) == len(load.EXPECTED_COLUMNS["sub"])
    name_bytes = b"TEST\xff CO" if bad_bytes else b"TEST CO"
    sub_line = "\t".join(sub_row).encode("utf-8").replace(b"TEST CO", name_bytes)
    num_lines = [
        b"0000000001-25-000001\tAssets\tus-gaap/2024\t20241231\t0\tUSD\t\t\t1000.0000\t",
        b"0000000001-25-000001\tRevenues\tus-gaap/2024\t20241231\t4\tUSD\t\t\t500.0000\tsome footnote",
        b"0000000001-25-000001\tRevenues\tus-gaap/2024\t20241231\t4\tUSD\tSegment=A;\t\t200.0000\t",
    ]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("sub.txt", (("bad" if bad_header else SUB_HEADER) + "\n").encode() + sub_line + b"\n")
        z.writestr("num.txt", (NUM_HEADER + "\n").encode() + b"\n".join(num_lines) + b"\n")
        z.writestr("tag.txt", (TAG_HEADER + "\n").encode() + b"Assets\tus-gaap/2024\t0\t0\tmonetary\tI\tD\tAssets\tdoc\n"
                   b"Revenues\tus-gaap/2024\t0\t0\tmonetary\tD\tC\tRevenues\tdoc\n")
        z.writestr("pre.txt", (PRE_HEADER + "\n").encode() + b"0000000001-25-000001\t1\t1\tBS\t0\tH\tAssets\tus-gaap/2024\tTotal assets\t0\n")
    return path


def test_extract_and_parse_round_trip(tmp_path):
    z = make_zip(tmp_path / "2024q4.zip", bad_bytes=True)
    total, newlines = load.extract_sanitized(z, tmp_path / "ext")
    assert newlines == {"sub": 2, "num": 4, "tag": 3, "pre": 2}
    text = (tmp_path / "ext" / "sub.txt").read_text(encoding="utf-8")
    assert "�" in text  # invalid byte replaced, not dropped
    rows, rejects, pq_bytes = load.parse_quarter("2024q4", tmp_path / "ext", tmp_path / "pq")
    assert rows == {"sub": 1, "num": 3, "tag": 2, "pre": 1}
    assert sum(rejects.values()) == 0
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM read_parquet('{(tmp_path / 'pq' / 'num.parquet').as_posix()}') ORDER BY value").df()
    assert list(df["value"]) == [200.0, 500.0, 1000.0]
    assert df["segments"].isna().sum() == 2  # empty fields become NULL
    assert df["dataset_quarter"].unique().tolist() == ["2024q4"]
    assert df["qtrs"].dtype.kind == "i"


def test_header_mismatch_is_rejected(tmp_path):
    z = make_zip(tmp_path / "2024q4.zip", bad_header=True)
    with pytest.raises(load.HeaderMismatch):
        load.extract_sanitized(z, tmp_path / "ext")


def test_load_quarter_is_idempotent(tmp_path, monkeypatch):
    from edgar_fundamentals import config

    monkeypatch.setitem(config.settings()["paths"], "parquet_dir", str(tmp_path / "pq"))
    monkeypatch.setitem(config.settings()["paths"], "extracted_dir", str(tmp_path / "ext"))
    monkeypatch.setitem(config.settings()["paths"], "manifest", str(tmp_path / "manifest.json"))
    z = make_zip(tmp_path / "2024q4.zip")
    first = load.load_quarter("2024q4", zip_path=z)
    assert not first.cached and first.total_rows == 7
    second = load.load_quarter("2024q4", zip_path=z)
    assert second.cached and second.rows == first.rows
    assert load.is_loaded("2024q4")
    third = load.load_quarter("2024q4", zip_path=z, force=True)
    assert not third.cached and third.rows == first.rows
