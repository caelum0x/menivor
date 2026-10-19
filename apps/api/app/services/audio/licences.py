"""Licence records for every audio asset the API ships (M2.4).

``asset_licences.json`` (next to this module) holds one record per audio file
under ``apps/api/assets``: path, SHA-256, where it came from, the licence, and
whether it is cleared for commercial output. A test walks the assets tree and
fails if any audio file lacks a record, or if a record's hash no longer matches
the file, so a new track cannot ship without one.

Honesty rule: a record says ``"cleared_for_output": false`` unless the licence
is verified. The upstream MoneyPrinterTurbo songs and the bundled default BGM
are recorded as not cleared; the owner decides what replaces them.

``MENIVOR_MUSIC_CLEARED_ONLY=1`` hides uncleared tracks from the music library
(off by default, so no current feature disappears without the owner's call).
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Iterator, Mapping, Optional

__all__ = [
    "AUDIO_EXTENSIONS",
    "MANIFEST_PATH",
    "assets_root",
    "cleared_only_enabled",
    "file_sha256",
    "is_cleared",
    "iter_audio_assets",
    "licence_for",
    "load_manifest",
]

AUDIO_EXTENSIONS: tuple[str, ...] = (
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma",
)
MANIFEST_PATH: Path = Path(__file__).resolve().with_name("asset_licences.json")
_REQUIRED_FIELDS = ("path", "sha256", "source", "licence", "cleared_for_output")
_CLEARED_ONLY_ENV = "MENIVOR_MUSIC_CLEARED_ONLY"


def assets_root() -> Path:
    """``apps/api/assets`` (this file is ``apps/api/app/services/audio/``)."""
    return Path(__file__).resolve().parents[3] / "assets"


def iter_audio_assets(root: Optional[Path] = None) -> Iterator[str]:
    """Assets-relative POSIX paths of every audio file, sorted."""
    base = root or assets_root()
    if not base.is_dir():
        return iter(())
    found = sorted(
        p.relative_to(base).as_posix()
        for p in base.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )
    return iter(found)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def load_manifest() -> Mapping[str, Mapping[str, object]]:
    """Path -> record (read-only). Raises ``ValueError`` on a malformed file."""
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    records = raw.get("assets") if isinstance(raw, dict) else None
    if not isinstance(records, list):
        raise ValueError("asset_licences.json: 'assets' must be a list")
    out: dict[str, Mapping[str, object]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("asset_licences.json: every record must be an object")
        missing = [f for f in _REQUIRED_FIELDS if f not in record]
        if missing:
            raise ValueError(f"asset_licences.json: {record.get('path')!r} missing {missing}")
        out[str(record["path"])] = MappingProxyType(dict(record))
    return MappingProxyType(out)


def _relative(path: str) -> Optional[str]:
    try:
        return Path(path).resolve().relative_to(assets_root().resolve()).as_posix()
    except (ValueError, OSError):
        return None


def licence_for(path: str) -> Optional[Mapping[str, object]]:
    """The licence record for an absolute or assets-relative path, if any."""
    try:
        manifest = load_manifest()
    except (OSError, ValueError):
        return None
    key = path if path in manifest else _relative(path)
    return manifest.get(key) if key else None


def is_cleared(path: str) -> bool:
    record = licence_for(path)
    return bool(record and record.get("cleared_for_output") is True)


def cleared_only_enabled() -> bool:
    flag = os.environ.get(_CLEARED_ONLY_ENV, "").strip().lower()
    return flag in {"1", "true", "yes", "on"}
