"""Apps shelf catalog (MH8): one data file per app under ``assets/presets/apps``.

An app is shown only when (1) its runner can run on this deployment (a key or a
package it needs is present), (2) its preview loop is uploaded (recorded in
``previews.json``) and ``APPS_PREVIEWS_LIVE`` is on, and (3) its copy names no
tool or model. No placeholder tiles: an app without a real preview stays hidden.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

ASSETS = Path(__file__).resolve().parents[3] / "assets" / "presets" / "apps"
PREVIEWS_FILE = ASSETS / "previews.json"
PREVIEWS_LIVE_ENV = "APPS_PREVIEWS_LIVE"
_FILE = re.compile(r"^(?P<id>[a-z0-9-]+)@v(?P<version>\d+)\.json$")
RUNNERS = ("plan", "image_edit", "local")
LOCAL_TOOLS = ("transition", "remove_bg", "beat_cut", "hook_score")


@dataclass(frozen=True)
class App:
    id: str
    version: int
    name: str
    blurb: str
    input: dict[str, Any]
    runner: str
    price: dict[str, Any]
    preview: str
    plan: dict[str, Any] = field(default_factory=dict)
    edit: dict[str, Any] = field(default_factory=dict)
    local: str = ""


def _load(path: Path) -> App:
    match = _FILE.match(path.name)
    if not match:
        raise ValueError(f"app file {path.name} must be named <id>@v<N>.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("id") != match["id"] or int(data.get("version", 0)) != int(match["version"]):
        raise ValueError(f"{path.name}: id or version does not match the file name")
    if data["runner"] not in RUNNERS:
        raise ValueError(f"{path.name}: unknown runner {data['runner']!r}")
    if data["runner"] == "local" and data.get("local") not in LOCAL_TOOLS:
        raise ValueError(f"{path.name}: unknown local tool {data.get('local')!r}")
    return App(id=data["id"], version=int(data["version"]), name=data["name"], blurb=data["blurb"],
               input=dict(data["input"]), runner=data["runner"], price=dict(data["price"]),
               preview=str(data.get("preview") or ""), plan=dict(data.get("plan") or {}),
               edit=dict(data.get("edit") or {}), local=str(data.get("local") or ""))


@lru_cache(maxsize=1)
def all_apps() -> tuple[App, ...]:
    newest: dict[str, App] = {}
    for path in sorted(ASSETS.glob("*@v*.json")):
        app = _load(path)
        if app.id not in newest or app.version > newest[app.id].version:
            newest[app.id] = app
    return tuple(sorted(newest.values(), key=lambda a: a.id))


def get(app_id: str) -> App | None:
    wanted = str(app_id or "").strip().lower()
    return next((a for a in all_apps() if a.id == wanted), None)


def previews() -> dict[str, str]:
    try:
        return dict(json.loads(PREVIEWS_FILE.read_text(encoding="utf-8")).get("live") or {})
    except (OSError, ValueError):
        return {}


def runner_ready(app: App, env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    if app.runner == "image_edit":
        return bool((source.get("FAL_KEY") or "").strip())
    if app.local == "remove_bg":
        return importlib.util.find_spec("rembg") is not None
    return True


def visible(app: App, env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    live = (source.get(PREVIEWS_LIVE_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}
    return live and app.id in previews() and runner_ready(app, source)


def copy_hits(app: App) -> list[str]:
    from app.domains.presets_hub.catalog import vendor_hits

    return list(vendor_hits(" ".join([app.name, app.blurb, json.dumps(app.input)])))


__all__ = ["ASSETS", "App", "all_apps", "copy_hits", "get", "previews", "runner_ready", "visible"]
