"""Bridge to the shared ``reelforge_caption_engine`` package.

The web caption preview (``apps/web`` → ``@reelforge/caption-engine``) and this
API render the SAME ASS from the SAME preset registry so the previewed caption
and the burned-in subtitle match. This module centralises the (monorepo path,
not pip-installed) import of the Python port — mirroring how
``services/compose/vfx`` reaches ``reelforge_effects_core`` — and exposes small,
failure-tolerant helpers the captions service builds on.

Everything here degrades gracefully: if the shared package cannot be imported
(a stripped deploy that only ships ``apps/api``), the helpers return ``None`` /
empty and callers fall back to the self-contained ``ass_karaoke`` builder, so a
missing sibling package can never break caption rendering.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
from types import ModuleType
from typing import Optional


def _load_engine() -> Optional[ModuleType]:
    """Import ``reelforge_caption_engine`` (adding the monorepo path if needed)."""
    try:  # Installed / already importable.
        import reelforge_caption_engine as engine  # type: ignore

        return engine
    except ModuleNotFoundError:
        pass

    # Monorepo path dependency (mirrors services/compose/vfx.py). This file lives
    # at apps/api/app/services/captions/_engine.py, so parents[5] is the repo
    # root and the package source is packages/caption-engine/python.
    pkg_root = (
        _Path(__file__).resolve().parents[5]
        / "packages"
        / "caption-engine"
        / "python"
    )
    if pkg_root.is_dir():
        path_str = str(pkg_root)
        if path_str not in _sys.path:
            _sys.path.insert(0, path_str)
        try:
            import reelforge_caption_engine as engine  # type: ignore

            return engine
        except ModuleNotFoundError:
            return None
    return None


# Import once at module load; ``None`` means "shared engine unavailable".
_ENGINE: Optional[ModuleType] = _load_engine()


def caption_engine() -> Optional[ModuleType]:
    """Return the shared ``reelforge_caption_engine`` module, or ``None``."""
    return _ENGINE


def preset_ids() -> tuple[str, ...]:
    """Return the shared-engine preset ids (empty tuple if unavailable)."""
    if _ENGINE is None:
        return ()
    return tuple(_ENGINE.list_presets())


def shared_preset(name: str):
    """Return the shared ``CaptionStyle`` for ``name``, or ``None`` if unavailable.

    Never raises: an unknown preset id or a missing package both yield ``None``
    so callers can fall back to their built-in defaults.
    """
    if _ENGINE is None:
        return None
    try:
        return _ENGINE.get_preset(name)
    except Exception:  # noqa: BLE001 - unknown id / broken package → fall back
        return None
