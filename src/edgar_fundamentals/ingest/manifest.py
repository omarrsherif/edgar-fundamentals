"""data/manifest.json: the single source of truth for what has been downloaded and parsed."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from edgar_fundamentals import config


def _path() -> Path:
    return config.path("manifest")


def load() -> dict:
    p = _path()
    if not p.exists():
        return {"quarters": {}}
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save(m: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=2, sort_keys=True)
    os.replace(tmp, p)


def get(quarter: str) -> dict:
    return load()["quarters"].get(quarter, {})


def update(quarter: str, **fields) -> dict:
    m = load()
    entry = m["quarters"].setdefault(quarter, {})
    entry.update(fields)
    entry["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(m)
    return entry
