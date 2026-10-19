"""Product/brand presets for Ad Clone (``assets/brands/<id>/adclone.json``).

Presets are read-only data. Updates (e.g. a designed ElevenLabs voice id) return a NEW dict and
are saved to the override directory ``ADCLONE_PRESET_DIR`` (never into the shipped asset).
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

BRANDS_DIR = Path(__file__).resolve().parents[3] / "assets" / "brands"
PRESETS = ("oxhan",)
OVERRIDE_ENV = "ADCLONE_PRESET_DIR"
_VOICE_ID = re.compile(r"^[A-Za-z0-9]{8,40}$")


class PresetError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.status_code = 400
        self.message = message


def _override_path(name: str) -> Path | None:
    root = (os.getenv(OVERRIDE_ENV) or "").strip()
    return Path(root) / f"{name}.adclone.json" if root else None


def load(name: str) -> dict[str, Any]:
    from . import preset_store

    if preset_store.is_stored(name):  # made by the Brand Agent from the user's own product
        stored = preset_store.load(name)
        if stored is None:
            raise PresetError("that product preset no longer exists")
        return stored
    if name not in PRESETS:
        raise PresetError(f"product preset is one of {', '.join(PRESETS)}")
    over = _override_path(name)
    path = over if over and over.is_file() else BRANDS_DIR / name / "adclone.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("id") != name:
        raise PresetError(f"preset {name}: wrong id")
    return data


def project_root(preset: dict[str, Any]) -> str:
    return (os.getenv(preset.get("project_root_env") or "") or preset["project_root_default"]).rstrip("/")


def with_voice(preset: dict[str, Any], character: str, voice_id: str) -> dict[str, Any]:
    """New preset with ``character``'s locked ElevenLabs voice id (input untouched)."""
    if character not in (preset.get("characters") or {}):
        raise PresetError(f"unknown character {character!r}")
    if not _VOICE_ID.match(voice_id or ""):
        raise PresetError("voice id must be 8-40 letters/digits")
    out = copy.deepcopy(preset)
    out["characters"][character]["voice"]["elevenlabs_voice_id"] = voice_id
    return out


def with_mj_refs(preset: dict[str, Any], *, sref_url: str | None = None,
                 cref_urls: dict[str, str] | None = None) -> dict[str, Any]:
    out = copy.deepcopy(preset)
    mj = out.setdefault("midjourney", {})
    if sref_url is not None:
        mj["sref_url"] = sref_url
    if cref_urls:
        mj["cref_urls"] = {**(mj.get("cref_urls") or {}), **cref_urls}
    return out


def save(preset: dict[str, Any]) -> Path:
    """Atomically write the preset to the override dir (required; the shipped asset stays read-only)."""
    over = _override_path(str(preset.get("id")))
    if over is None:
        raise PresetError(f"set {OVERRIDE_ENV} to a writable folder to save preset changes")
    over.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(over.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(preset, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, over)
    return over


def public_view(preset: dict[str, Any]) -> dict[str, Any]:
    """What the web UI shows for "Your product" (no file paths)."""
    return {"id": preset["id"], "product": preset["product"], "brand_name": preset["brand_name"],
            "domain": preset["domain"], "cta": preset["cta"]["text"], "end_card": preset["cta"]["card"],
            "characters": [{"key": k, "name": c["name"], "role": c["role"], "persona": c.get("persona", ""),
                            "voice_locked": bool(c["voice"].get("elevenlabs_voice_id"))}
                           for k, c in preset["characters"].items()]}
