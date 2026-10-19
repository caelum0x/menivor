"""Paths owned by the ReelForge backend.

The generation engine deliberately keeps its historical flat import layout
(``from services...``, ``from models...``).  This module is the one place that
maps that layout onto the backend-owned directory tree.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(os.getenv("REELFORGE_BACKEND_ROOT", Path(__file__).resolve().parents[1])).resolve()
ENGINE_ROOT = Path(os.getenv("REELFORGE_ENGINE_ROOT", BACKEND_ROOT / "engine")).resolve()
ASSETS_ROOT = Path(os.getenv("REELFORGE_ASSETS_ROOT", BACKEND_ROOT / "assets")).resolve()
RUNTIME_ROOT = Path(os.getenv("REELFORGE_RUNTIME_ROOT", BACKEND_ROOT / "runtime" / "storage")).resolve()


def configure_engine_imports() -> None:
    """Make the licensed engine's flattened packages importable in this process."""
    for path in (ENGINE_ROOT, BACKEND_ROOT):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def ensure_runtime_directories() -> None:
    """Create only backend-owned writable directories."""
    for directory in (RUNTIME_ROOT, RUNTIME_ROOT / "data", RUNTIME_ROOT / "output", RUNTIME_ROOT / "temp"):
        directory.mkdir(parents=True, exist_ok=True)

