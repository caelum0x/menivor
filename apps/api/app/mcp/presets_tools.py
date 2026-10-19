"""MCP tools for the preset shelf and Recreate (MH9, Wave P PM3.0).

* ``presets.list``      the visible shelf tiles (name, blurb, credit kind, preview URLs)
* ``presets.recreate``  the Create call for a shelf preset or a public gallery item

Neither tool spends anything: both return the exact body of the normal Create
call (``POST /jobs`` or ``POST /generation/broll/generate``), which quotes and
debits through the same guards as the web app. The tools are listed and
callable only when ``MCP_PRESETS_LIVE`` is on. The same handlers back the hosted
connector (``app.domains.mcp_hosted.tools``: ``presets_list`` /
``presets_recreate``, bearer connector tokens), so the flag no longer waits for
MG4 (MCP OAuth): nothing here spends, and the hosted tokens already scope access.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

FLAG = "MCP_PRESETS_LIVE"
_ON = {"1", "true", "yes", "on"}
MAX_SUBJECT = 300


def live(env: Optional[Mapping[str, str]] = None) -> bool:
    return ((env if env is not None else os.environ).get(FLAG) or "").strip().lower() in _ON


def _error(message: str) -> Exception:
    from app.mcp.tools import MCPToolError

    return MCPToolError(message)


def _list(session: Session, user_id: str, args: dict) -> dict:
    from app.domains.presets_hub import service

    kind = str(args.get("kind") or "").strip()
    tiles = service.shelf()
    if kind:
        if kind not in ("filter", "model"):
            raise _error("kind is filter or model")
        tiles = [t for t in tiles if t["kind"] == kind]
    return {"presets": tiles}


def _recreate(session: Session, user_id: str, args: dict) -> dict:
    from app.domains.gallery import service as gallery
    from app.domains.presets_hub import service as presets

    subject = str(args.get("subject") or "")[:MAX_SUBJECT]
    image_key = str(args.get("image_key") or "").strip() or None
    item_id = str(args.get("item_id") or "").strip()
    preset_id = str(args.get("preset_id") or "").strip()
    if bool(item_id) == bool(preset_id):
        raise _error("give exactly one of item_id or preset_id")
    try:
        if item_id:
            return gallery.recreate_plan(session, item_id, subject=subject, image_key=image_key)
        presets.visible_preset(preset_id)
        return presets.resolve(preset_id, subject=subject, image_key=image_key)
    except gallery.NotFound as exc:
        raise _error("gallery item not found") from exc
    except gallery.GalleryError as exc:
        raise _error(str(exc)) from exc
    except presets.PresetNotFound as exc:
        raise _error("preset not found") from exc
    except presets.PresetInputError as exc:
        raise _error(str(exc)) from exc


TOOLS: list[dict[str, Any]] = [
    {
        "name": "presets.list",
        "description": "List the preset shelf: one-tap video looks and effects with preview loops. "
        "Optional kind: filter (standard credits) or model (AI-video credits).",
        "input_schema": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["filter", "model"]}}},
        "handler": _list,
    },
    {
        "name": "presets.recreate",
        "description": "Get the Create call for a preset (preset_id) or a public gallery item (item_id) with "
        "your own subject. Returns the route and body to post; nothing is charged by this tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "preset_id": {"type": "string"},
                "item_id": {"type": "string"},
                "subject": {"type": "string"},
                "image_key": {"type": "string"},
            },
            "required": ["subject"],
        },
        "handler": _recreate,
    },
]
NAMES = frozenset(t["name"] for t in TOOLS)
_BY_NAME: dict[str, Callable[[Session, str, dict], dict]] = {t["name"]: t["handler"] for t in TOOLS}


def specs(env: Optional[Mapping[str, str]] = None) -> list[dict]:
    if not live(env):
        return []
    return [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in TOOLS]


def dispatch(session: Session, user_id: str, name: str, args: Optional[dict] = None) -> dict:
    if not live():
        raise _error(f"unknown tool: {name}")
    return _BY_NAME[name](session, user_id, args or {})


__all__ = ["FLAG", "NAMES", "TOOLS", "dispatch", "live", "specs"]
