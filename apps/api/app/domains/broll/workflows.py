"""Product allowlist for provider workflow/model selectors.

Clients may choose a product preset, but they may never dispatch an arbitrary
ComfyUI deployment or managed model identifier. Defaults and explicitly
configured allowlists are the only accepted upstream selectors.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from loguru import logger

from app.config import config
from app.models.exception import HttpException


def _values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        candidates = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        candidates = value
    else:
        candidates = ()
    return (str(item).strip() for item in candidates if str(item).strip())


def configured_provider_id() -> str:
    return (os.getenv("BROLL_GEN_PROVIDER") or "").strip() or "comfyui"


def approved_workflow_ids(provider_id: str | None = None) -> frozenset[str]:
    provider_id = provider_id or configured_provider_id()
    if provider_id == "none":  # free public tier: AI B-roll disabled
        return frozenset()
    if provider_id == "pixelle":
        return frozenset(
            {
                str(config.pixelle.get("model", "") or "").strip(),
                *_values(config.pixelle.get("allowed_models", ())),
            }
            - {""}
        )
    return frozenset(
        {
            str(config.comfyui.get("deployment_id", "") or "").strip(),
            str(config.comfyui.get("deployment_id_i2v", "") or "").strip(),
            *_values(config.comfyui.get("allowed_deployment_ids", ())),
        }
        - {""}
    )


def require_approved_workflow(workflow_id: str, request_id: str) -> None:
    workflow_id = (workflow_id or "").strip()
    if not workflow_id:
        return
    if workflow_id not in approved_workflow_ids():
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: B-roll workflow is not approved for this deployment",
        )


# ---------------------------------------------------------------------------
# Pinned ComfyUI workflow identity (@reelforge/comfy-workflow-schema)
# ---------------------------------------------------------------------------
# The B-roll studio dispatches a Wan 2.2 motion graph. That graph's identity —
# its node commits + weight refs + typed input contract — is pinned by an
# FNV-1a-32 hash in ``comfy-workflow-schema`` (TS + a byte-identical Python
# port under ``packages/``). Enforcing that pin AT DISPATCH is what makes the
# design guarantee real: change a pinned node commit in the catalog and the
# ``graph_hash`` changes, so every submission (and its provenance record) is
# stamped with a NEW immutable version automatically. Without this wiring the
# provider submitted graphs the schema never saw, so the pin was dead code.
#
# ``deployment_id`` is an opaque comfyui-deploy endpoint id; the catalog slug is
# the semantic workflow identity. The mode -> slug map bridges the two. Defaults
# point both motion modes at the catalog's Wan descriptor; a deployer can remap
# via ``COMFYUI_WORKFLOW_SLUGS`` (e.g. ``t2v=wan-i2v,i2v=wan-i2v``) without code.

_DEFAULT_WORKFLOW_SLUGS: dict[str, str] = {"t2v": "wan-i2v", "i2v": "wan-i2v"}


def _load_workflow_schema() -> Any | None:
    """Import ``reelforge_comfy_workflow`` (adding the monorepo path if needed).

    Mirrors ``app/services/compose/vfx.py``: the schema is a monorepo path
    dependency, not pip-installed, so fall back to inserting its source dir.
    Returns the module, or ``None`` when it cannot be located — in which case
    pin enforcement degrades to a logged no-op instead of crashing dispatch.
    """
    try:  # Installed / already importable.
        import reelforge_comfy_workflow as schema  # type: ignore

        return schema
    except ModuleNotFoundError:
        pass

    import sys as _sys
    from pathlib import Path as _Path

    # This file is apps/api/app/domains/broll/workflows.py, so parents[5] is the
    # repo root and the package source is packages/comfy-workflow-schema/python.
    pkg_root = (
        _Path(__file__).resolve().parents[5]
        / "packages"
        / "comfy-workflow-schema"
        / "python"
    )
    if pkg_root.is_dir():
        path_str = str(pkg_root)
        if path_str not in _sys.path:
            _sys.path.insert(0, path_str)
        try:
            import reelforge_comfy_workflow as schema  # type: ignore

            return schema
        except ModuleNotFoundError:
            logger.error("comfy-workflow-schema present but not importable")
            return None
    logger.warning("comfy-workflow-schema not found; B-roll pin enforcement disabled")
    return None


# Import once at module load; ``None`` means "schema unavailable" (degrade).
_SCHEMA: Any | None = _load_workflow_schema()


def _slug_overrides() -> dict[str, str]:
    """Deployer mode -> catalog-slug overrides from env/config (immutable copy)."""
    raw: Any = os.getenv("COMFYUI_WORKFLOW_SLUGS", "") or config.comfyui.get(
        "workflow_slugs", ""
    )
    mapping: dict[str, str] = {}
    if isinstance(raw, dict):
        pairs: Iterable[tuple[Any, Any]] = raw.items()
    elif isinstance(raw, str):
        pairs = (
            (part.split("=", 1)[0], part.split("=", 1)[1])
            for part in raw.split(",")
            if "=" in part
        )
    else:
        pairs = ()
    for mode, slug in pairs:
        mode_s, slug_s = str(mode).strip().lower(), str(slug).strip()
        if mode_s and slug_s:
            mapping[mode_s] = slug_s
    return mapping


def configured_workflow_slug(mode: str) -> str:
    """Resolve the pinned catalog slug for a B-roll ``mode`` (``t2v``/``i2v``)."""
    mode_s = (mode or "t2v").strip().lower() or "t2v"
    override = _slug_overrides().get(mode_s, "")
    return override or _DEFAULT_WORKFLOW_SLUGS.get(
        mode_s, _DEFAULT_WORKFLOW_SLUGS["t2v"]
    )


def pin_workflow(mode: str) -> dict[str, Any] | None:
    """Return the immutable pin for the workflow a B-roll ``mode`` dispatches.

    ``{'slug', 'pin', 'node_commits', 'weight_refs'}`` where ``pin`` is the
    FNV-1a-32 ``graph_hash`` of the pinned descriptor. Returns ``None`` when the
    schema is unavailable or the configured slug is unknown, so the provider can
    still dispatch (pin recorded as empty) rather than fail — a B-roll failure
    must never fail a reel job.
    """
    if _SCHEMA is None:
        return None
    slug = configured_workflow_slug(mode)
    try:
        descriptor = _SCHEMA.get_workflow(slug)
    except KeyError:
        logger.warning(f"broll: no pinned comfy workflow for slug {slug!r}")
        return None
    return {
        "slug": slug,
        "pin": _SCHEMA.graph_hash(descriptor),
        "node_commits": dict(descriptor.get("node_commits") or {}),
        "weight_refs": list(descriptor.get("weight_refs") or []),
    }


def validate_dispatch_inputs(
    mode: str, *, frames: int | None = None, has_image: bool = False
) -> list[str]:
    """Validate a submitted B-roll graph against its pinned input contract.

    Checks only the inputs the provider actually controls against the pinned
    descriptor's real slots: the frame count against the workflow's ``frames``
    ``min``/``max`` bounds, and (for ``i2v``) the presence of the required
    reference image. Returns the list of human-readable errors (empty when the
    submission is valid or the schema is unavailable). The provider treats a
    non-empty result as a fail-closed dispatch rejection.
    """
    if _SCHEMA is None:
        return []
    slug = configured_workflow_slug(mode)
    try:
        descriptor = _SCHEMA.get_workflow(slug)
    except KeyError:
        return []

    errors: list[str] = []
    slots = descriptor.get("inputs") or []
    if (mode or "").strip().lower() == "i2v":
        image_slot = next((s for s in slots if s.get("name") == "image"), None)
        if image_slot and image_slot.get("required") and not has_image:
            errors.append(f"{slug}: i2v dispatch requires a reference image")

    if frames is not None:
        frame_slot = next((s for s in slots if s.get("name") == "frames"), None)
        if frame_slot is not None:
            # Reuse the schema's own validator on the real slot so the accepted
            # range always tracks the pinned catalog (no bounds duplicated here).
            for err in _SCHEMA.validate_inputs(
                {"inputs": [frame_slot]}, {"frames": int(frames)}
            ):
                errors.append(f"{slug}: {err}")
    return errors


def product_engine_capability() -> dict[str, Any]:
    """Expose the bounded engine capability that clients may actually invoke.

    Web, mobile, and GPUI desktop get a stable B-roll product selector, not
    arbitrary Comfy workflows, checkpoints, diffusion schedulers, or model
    weights.  The GPU worker owns those internal choices.
    """
    provider_id = configured_provider_id()
    workflows = sorted(approved_workflow_ids(provider_id))
    return {
        "broll": {
            "provider": provider_id,
            "modes": ["t2v", "i2v"],
            "approved_workflows": workflows,
            "runtime": "gpu_worker",
        }
    }
