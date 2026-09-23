"""Capture dashboard screenshots with Playwright (best effort; requires `playwright install chromium`)."""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

from edgar_fundamentals import config
from edgar_fundamentals.log import get_logger

log = get_logger("edgar.screenshots")

TABS = ["Company", "Compare", "Sector", "Data quality"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def capture(out_dir: Path | None = None) -> list[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("playwright not installed; skipping screenshots (uv sync --extra dev; playwright install chromium)")
        return []
    out_dir = out_dir or (config.PROJECT_ROOT / "docs" / "screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)
    app = Path(__file__).with_name("app.py")
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(port), "--server.headless", "true",
         "--browser.gatherUsageStats", "false", "--theme.base", "light"],
        cwd=str(config.PROJECT_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    written: list[Path] = []
    try:
        url = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(1)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(url, wait_until="networkidle", timeout=120_000)
            page.wait_for_timeout(8000)
            for tab in TABS:
                page.get_by_role("tab", name=tab).click()
                page.wait_for_timeout(6000)
                target = out_dir / f"{tab.lower().replace(' ', '_')}.png"
                page.screenshot(path=str(target), full_page=False)
                written.append(target)
                log.info("screenshot -> %s", target)
            browser.close()
    except Exception as exc:  # noqa: BLE001 - best effort
        log.warning("screenshot capture failed: %s", exc)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return written
