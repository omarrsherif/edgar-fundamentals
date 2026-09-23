"""Download: caching, Range resume, size verification and retry, against a local HTTP server."""
from __future__ import annotations

import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import requests

from edgar_fundamentals import config
from edgar_fundamentals.ingest import download, manifest

PAYLOAD = bytes(range(256)) * 4000  # ~1 MB deterministic body


class Handler(BaseHTTPRequestHandler):
    """Serves PAYLOAD at any path; honours Range; can fail the first N requests; can ignore Range."""

    state = {"fail_first": 0, "ignore_range": False, "requests": []}

    def log_message(self, *a):  # silence
        pass

    def do_GET(self):
        st = Handler.state
        st["requests"].append(dict(self.headers))
        if st["fail_first"] > 0:
            st["fail_first"] -= 1
            self.send_response(503)
            self.end_headers()
            return
        rng = self.headers.get("Range")
        if rng and not st["ignore_range"]:
            start = int(rng.split("=")[1].rstrip("-"))
            body = PAYLOAD[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}")
        else:
            body = PAYLOAD
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    Handler.state = {"fail_first": 0, "ignore_range": False, "requests": []}
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setitem(config.settings()["paths"], "manifest", str(tmp_path / "manifest.json"))
    monkeypatch.setitem(config.settings()["http"], "min_interval_seconds", 0.0)
    monkeypatch.setitem(config.settings()["http"], "backoff_base_seconds", 0.01)
    download._limiter = None
    return tmp_path


def test_user_agent_contains_contact(monkeypatch):
    monkeypatch.setenv("EDGAR_CONTACT_EMAIL", "qa@example.com")
    assert "qa@example.com" in config.user_agent()
    h = download.headers()
    assert h["Host"] == "www.sec.gov" and "gzip" in h["Accept-Encoding"]


def test_rate_limiter_enforces_interval():
    import time

    rl = download.RateLimiter(0.05)
    t0 = time.monotonic()
    rl.wait(); rl.wait(); rl.wait()
    assert time.monotonic() - t0 >= 0.09


def test_full_download_records_manifest(server, env):
    r = download.download_quarter("2024q3", raw_dir=env / "raw", url=f"{server}/2024q3.zip")
    assert not r.cached and r.bytes_total == len(PAYLOAD) and r.bytes_downloaded == len(PAYLOAD)
    assert (env / "raw" / "2024q3.zip").read_bytes() == PAYLOAD
    e = manifest.get("2024q3")
    assert e["download_status"] == "complete" and e["zip_bytes"] == len(PAYLOAD) and e["zip_sha256"] == r.sha256
    # second call is served from cache without any HTTP request
    n_before = len(Handler.state["requests"])
    r2 = download.download_quarter("2024q3", raw_dir=env / "raw", url=f"{server}/2024q3.zip")
    assert r2.cached and r2.bytes_downloaded == 0 and len(Handler.state["requests"]) == n_before


def test_resume_from_partial_file(server, env):
    raw = env / "raw"; raw.mkdir()
    (raw / "2024q4.zip.part").write_bytes(PAYLOAD[:300_000])
    r = download.download_quarter("2024q4", raw_dir=raw, url=f"{server}/2024q4.zip")
    assert (raw / "2024q4.zip").read_bytes() == PAYLOAD
    assert r.bytes_downloaded == len(PAYLOAD) - 300_000
    assert Handler.state["requests"][0]["Range"] == "bytes=300000-"


def test_server_ignoring_range_triggers_restart(server, env):
    raw = env / "raw"; raw.mkdir()
    (raw / "2025q1.zip.part").write_bytes(b"garbage")
    Handler.state["ignore_range"] = True
    r = download.download_quarter("2025q1", raw_dir=raw, url=f"{server}/2025q1.zip")
    assert (raw / "2025q1.zip").read_bytes() == PAYLOAD and r.bytes_downloaded == len(PAYLOAD)


def test_retries_then_succeeds(server, env):
    Handler.state["fail_first"] = 2
    r = download.download_quarter("2025q2", raw_dir=env / "raw", url=f"{server}/2025q2.zip")
    assert r.bytes_total == len(PAYLOAD) and len(Handler.state["requests"]) == 3


def test_gives_up_after_max_retries(server, env, monkeypatch):
    monkeypatch.setitem(config.settings()["http"], "max_retries", 2)
    Handler.state["fail_first"] = 5
    with pytest.raises(requests.HTTPError):
        download.download_quarter("2025q3", raw_dir=env / "raw", url=f"{server}/2025q3.zip")
    assert manifest.get("2025q3")["download_status"] == "failed"


def test_quarter_window_and_urls():
    qs = config.quarters(3, "2025q1")
    assert [str(q) for q in qs] == ["2024q3", "2024q4", "2025q1"]
    assert qs[0].url().endswith("/2024q3.zip")
    assert config.Quarter.parse("2026Q2").prev() == config.Quarter(2026, 1)
