"""Safe inventory of API-owned runtime, assets, engine, and operator tooling.

This deliberately reports only product-safe availability. It never imports GPU
code, reads provider secrets, or turns candidate workflow files into dispatchable
features. The capability document lets every first-party client explain what the
deployed product can do without coupling it to the backend filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.bootstrap import ASSETS_ROOT, ENGINE_ROOT, RUNTIME_ROOT, ensure_runtime_directories


def _exists(path: Path) -> bool:
    return path.is_file() or path.is_dir()


def _approved_workflows() -> list[str]:
    manifests = ASSETS_ROOT / "workflows" / "manifests"
    approved: list[str] = []
    for path in manifests.glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 - a bad manifest is simply unavailable
            continue
        if data.get("status") == "approved" and data.get("dispatch_enabled") is True:
            approved.append(str(data.get("id") or path.stem))
    return sorted(approved)


def product_inventory() -> dict[str, Any]:
    """Return bounded feature availability for client capability discovery."""
    ensure_runtime_directories()
    return {
        "engine": {
            "gpu_worker_required": True,
            "managed_video_facade": _exists(ENGINE_ROOT / "reelforge_engine"),
            "layers": ["acceleration", "pipelines", "k_diffusion", "models"],
        },
        "assets": {
            "fonts": _exists(ASSETS_ROOT / "resource" / "fonts"),
            "hooks": [
                language
                for language in ("en", "tr")
                if _exists(ASSETS_ROOT / "resource" / "hooks" / f"{language}.yaml")
            ],
            "voice_catalog": _exists(ASSETS_ROOT / "resource" / "voices.yaml"),
            "default_music": _exists(ASSETS_ROOT / "bgm" / "default.mp3"),
            # Candidate workflows remain inventory-only. Empty is expected until
            # an operator approves a pinned graph and license review.
            "approved_workflows": _approved_workflows(),
        },
        "runtime": {
            "storage_ready": all(
                directory.is_dir()
                for directory in (RUNTIME_ROOT / "data", RUNTIME_ROOT / "output", RUNTIME_ROOT / "temp")
            ),
            "result_delivery": "signed_r2_urls",
        },
        "operations": {
            "preflight": True,
            "deploy_smoke": True,
            "in_process_smoke": True,
        },
    }
