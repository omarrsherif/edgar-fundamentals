"""Resumable, rate-limited download of SEC FSDS quarterly ZIPs.

Each quarter is fetched into <raw_dir>/<quarter>.zip.part; an existing .part file is resumed with an
HTTP Range request (restarted if the server ignores it). The completed file is renamed atomically and
its size + sha256 recorded in the manifest so later runs skip it.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from edgar_fundamentals import config
from edgar_fundamentals.ingest import manifest
from edgar_fundamentals.log import get_logger

log = get_logger("edgar.download")


class RateLimiter:
    """Minimum-interval limiter. SEC allows 10 req/s; we stay far below."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delta = now - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


_limiter: RateLimiter | None = None


def limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(config.settings()["http"]["min_interval_seconds"])
    return _limiter


def headers(extra: dict | None = None) -> dict:
    h = {
        "User-Agent": config.user_agent(),
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }
    if extra:
        h.update(extra)
    return h


def sha256_of(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class DownloadResult:
    quarter: str
    path: Path
    bytes_total: int
    bytes_downloaded: int  # bytes transferred in THIS run (0 when cached)
    seconds: float
    cached: bool
    sha256: str


def _discover_url_from_index(quarter: str, session: requests.Session) -> str | None:
    """Fallback if the URL template stops working: scrape the index page for the quarter's link."""
    idx = config.settings()["dataset"]["index_page"]
    limiter().wait()
    r = session.get(idx, headers=headers(), timeout=60)
    if r.status_code != 200:
        return None
    m = re.search(r'href="([^"]*' + re.escape(quarter) + r'\.zip)"', r.text, re.I)
    if not m:
        return None
    href = m.group(1)
    return href if href.startswith("http") else "https://www.sec.gov" + href


def download_quarter(
    quarter: str,
    raw_dir: Path | None = None,
    force: bool = False,
    session: requests.Session | None = None,
    url: str | None = None,
) -> DownloadResult:
    http = config.settings()["http"]
    raw_dir = raw_dir or config.path("raw_dir")
    raw_dir.mkdir(parents=True, exist_ok=True)
    final = raw_dir / f"{quarter}.zip"
    part = raw_dir / f"{quarter}.zip.part"
    session = session or requests.Session()

    entry = manifest.get(quarter)
    if final.exists() and not force:
        size = final.stat().st_size
        if entry.get("zip_bytes") == size and entry.get("zip_sha256"):
            log.info("%s: cached (%d bytes)", quarter, size)
            return DownloadResult(quarter, final, size, 0, 0.0, True, entry["zip_sha256"])
        digest = sha256_of(final)
        manifest.update(quarter, zip_bytes=size, zip_sha256=digest, zip_path=str(final),
                        download_status="complete")
        log.info("%s: present on disk, manifest refreshed (%d bytes)", quarter, size)
        return DownloadResult(quarter, final, size, 0, 0.0, True, digest)

    url = url or config.Quarter.parse(quarter).url()
    t0 = time.perf_counter()
    transferred = 0
    attempts = 0
    while True:
        attempts += 1
        resume_from = part.stat().st_size if part.exists() else 0
        req_headers = headers({"Range": f"bytes={resume_from}-"} if resume_from else None)
        try:
            limiter().wait()
            with session.get(url, headers=req_headers, stream=True, timeout=http["timeout_seconds"]) as r:
                if r.status_code == 404 and attempts == 1:
                    alt = _discover_url_from_index(quarter, session)
                    if alt and alt != url:
                        log.warning("%s: template URL 404, using index link %s", quarter, alt)
                        url = alt
                        continue
                if r.status_code in (403, 429) or r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                if r.status_code == 416:
                    log.warning("%s: 416 on resume, restarting from scratch", quarter)
                    part.unlink(missing_ok=True)
                    continue
                r.raise_for_status()
                if resume_from and r.status_code == 200:
                    log.warning("%s: server ignored Range, restarting", quarter)
                    part.unlink(missing_ok=True)
                    resume_from = 0
                mode = "ab" if (resume_from and r.status_code == 206) else "wb"
                content_len = r.headers.get("Content-Length")
                expected_total = None
                if content_len is not None:
                    expected_total = int(content_len) + (resume_from if r.status_code == 206 else 0)
                log.info("%s: GET %s (status %d, resume_from=%d, expected_total=%s)",
                         quarter, url, r.status_code, resume_from, expected_total)
                with open(part, mode) as fh:
                    for chunk in r.iter_content(chunk_size=http["chunk_bytes"]):
                        if chunk:
                            fh.write(chunk)
                            transferred += len(chunk)
                size = part.stat().st_size
                if expected_total is not None and size != expected_total:
                    raise IOError(f"size mismatch: got {size}, expected {expected_total}")
            break
        except (requests.RequestException, IOError) as exc:
            if attempts >= http["max_retries"]:
                manifest.update(quarter, download_status="failed", error=str(exc))
                raise
            delay = http["backoff_base_seconds"] ** attempts
            log.warning("%s: attempt %d failed (%s); retrying in %.0fs", quarter, attempts, exc, delay)
            time.sleep(delay)

    shutil.move(str(part), str(final))
    seconds = time.perf_counter() - t0
    size = final.stat().st_size
    digest = sha256_of(final)
    manifest.update(quarter, zip_bytes=size, zip_sha256=digest, zip_path=str(final),
                    download_status="complete", download_seconds=round(seconds, 3),
                    download_bytes_transferred=transferred, download_url=url)
    log.info("%s: downloaded %d bytes in %.1fs (%.1f MB/s)",
             quarter, size, seconds, size / 1e6 / max(seconds, 1e-9))
    return DownloadResult(quarter, final, size, transferred, seconds, False, digest)


def download_all(quarters: list[str], force: bool = False) -> list[DownloadResult]:
    session = requests.Session()
    return [download_quarter(q, force=force, session=session) for q in quarters]


if __name__ == "__main__":
    download_all([str(q) for q in config.quarters()])
