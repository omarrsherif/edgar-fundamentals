"""ASCII-only logging (Windows consoles default to cp1252)."""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def get_logger(name: str = "edgar") -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S")
        )
        root = logging.getLogger("edgar")
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        root.propagate = False
        _CONFIGURED = True
    return logging.getLogger(name)
