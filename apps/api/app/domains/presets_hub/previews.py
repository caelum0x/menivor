"""Preview loops for the preset shelf (MH2).

``assets/presets/previews.json`` maps a preset id to its preview entry::

    {"loop": "presets/<id>.mp4", "poster": "presets/<id>.jpg",
     "status": "staged" | "published", "rendered_at": "YYYY-MM-DD",
     "source": "...", "spend_usd": 0.0, "funded_by": "owner-promo-M1"}

A tile is shown only with a real preview: ``published``, or ``staged`` once
the deploy step has uploaded the loops and set ``PRESET_PREVIEWS_LIVE=1``.
Model presets also need ``funded_by = owner-promo-M1`` (their previews are
paid renders, owner item M1); there is never placeholder art.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from .catalog import ASSETS, KIND_MODEL, Preset

MANIFEST = ASSETS / "previews.json"
LIVE_ENV = "PRESET_PREVIEWS_LIVE"
OWNER_PROMO = "owner-promo-M1"
#: Weekly drop previews (MH9) are paid from the weekly promo budget, owner item M2.
OWNER_PROMO_DROP = "owner-promo-M2"
DEFAULT_MEDIA_BASE = "https://media.menivor.com"
_ON = {"1", "true", "yes", "on"}


def load_manifest() -> dict[str, dict]:
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(data.get("previews") or {})


def _staged_live() -> bool:
    return (os.environ.get(LIVE_ENV) or "").strip().lower() in _ON


def visible(preset: Preset, entry: Mapping | None) -> bool:
    if not entry or not entry.get("loop") or not entry.get("poster"):
        return False
    status = str(entry.get("status") or "")
    if status != "published" and not (status == "staged" and _staged_live()):
        return False
    if preset.kind == KIND_MODEL and entry.get("funded_by") not in (OWNER_PROMO, OWNER_PROMO_DROP):
        return False
    # Wave P PM3.0 (MH9): a preset planned for a weekly drop stays hidden until that drop is released.
    if entry.get("drop") and not _drop_released(preset.id):
        return False
    return True


def _drop_released(preset_id: str) -> bool:
    from app.services.loops import preset_drop

    return preset_drop.released(preset_id)


def media_base() -> str:
    return (os.environ.get("R2_PUBLIC_MEDIA_BASE_URL") or DEFAULT_MEDIA_BASE).rstrip("/")


def public_urls(entry: Mapping) -> dict[str, str]:
    base = media_base()
    return {"loop_url": f"{base}/{str(entry['loop']).lstrip('/')}",
            "poster_url": f"{base}/{str(entry['poster']).lstrip('/')}"}
