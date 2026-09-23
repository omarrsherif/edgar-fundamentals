"""Settings, paths and quarter enumeration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
PACKAGE_DIR = Path(__file__).resolve().parent
SQL_DIR = PACKAGE_DIR / "warehouse" / "sql"
RULES_DIR = PACKAGE_DIR / "quality" / "rules"

load_dotenv(PROJECT_ROOT / ".env")


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def settings() -> dict:
    return load_yaml("settings.yaml")


def path(key: str) -> Path:
    """Resolve a path from settings.paths relative to the project root."""
    p = Path(settings()["paths"][key])
    return p if p.is_absolute() else PROJECT_ROOT / p


def contact_email() -> str:
    return os.environ.get("EDGAR_CONTACT_EMAIL", "you@example.com")


def user_agent() -> str:
    return settings()["http"]["user_agent_template"].format(email=contact_email())


@dataclass(frozen=True, order=True)
class Quarter:
    year: int
    q: int

    @classmethod
    def parse(cls, s: str) -> "Quarter":
        s = s.lower().strip()
        year, q = s.split("q")
        return cls(int(year), int(q))

    def __str__(self) -> str:
        return f"{self.year}q{self.q}"

    def prev(self) -> "Quarter":
        return Quarter(self.year - 1, 4) if self.q == 1 else Quarter(self.year, self.q - 1)

    def url(self) -> str:
        return settings()["dataset"]["url_template"].format(quarter=str(self))


def quarters(n: int | None = None, latest: str | None = None) -> list[Quarter]:
    """The ingest window, oldest first."""
    ds = settings()["dataset"]
    n = n or ds["n_quarters"]
    q = Quarter.parse(latest or ds["latest_quarter"])
    out = [q]
    for _ in range(n - 1):
        q = q.prev()
        out.append(q)
    return sorted(out)


def in_scope_forms() -> list[str]:
    return list(settings()["dataset"]["in_scope_forms"])
