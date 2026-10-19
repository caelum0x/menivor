"""Read-only launch status endpoint for first-party clients.

``GET /api/v1/launch/status`` returns the current launch mode, feature gates,
the payments mode and which reel formats this deployment can make
(``available_formats`` / ``locked_formats``, with a plain reason), so clients
can gate format pickers and show an honest "what's open" answer.

The answer is public, so it carries no environment variable names, vendor
names or internal checklist (claims rules 3 and 7, surface ``api-public``).
Staff callers (pilot allow-list or ``is_staff`` users) also get the operator
detail: the full readiness checklist under ``readiness`` and the env NAMES that
unlock each locked format (``unlock_env``). Values are never included.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from loguru import logger

from app.controllers.v1.base import new_router
from app.core.launch.policy import launch_status, request_is_pilot_staff
from app.utils import utils

router = new_router()

#: Free formats a signed-out visitor may read about (the /beta page).
_PUBLIC_FREE_PATH_IDS: frozenset[str] = frozenset({"captions_only_byov", "faceless_tts_free_voice"})


def _caller_is_staff(request: Request) -> bool:
    """Pilot staff, or an authenticated ``is_staff`` user. Never raises."""
    if request_is_pilot_staff():
        return True
    headers = request.headers
    if not (headers.get("authorization") or headers.get("x-api-key")):
        return False
    from app.core.api_docs import _is_staff

    return _is_staff(request)


def _public_formats(items: list[dict[str, Any]] | None, *, locked: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items or []:
        row = {"id": item.get("id", ""), "label": item.get("label", "")}
        if locked:
            row["code"] = item.get("code", "")
            row["reason"] = item.get("reason", "")
        out.append(row)
    return out


def _public_readiness(doc: dict[str, Any]) -> dict[str, Any]:
    """The part of the readiness document anyone may see (no names, no notes)."""
    paths = []
    for item in doc.get("free_paths") or []:
        if item.get("id") not in _PUBLIC_FREE_PATH_IDS:
            continue
        paths.append(
            {
                "id": item["id"],
                "label": item.get("label", ""),
                "available": bool(item.get("available")),
                "paid_keys": [],
            }
        )
    return {
        "tier": doc.get("tier", "full"),
        "public_launch_ready": bool(doc.get("public_launch_ready")),
        "free_paths": paths,
    }


def build_launch_status(*, staff: bool) -> dict[str, Any]:
    """The ``/launch/status`` document for a public or a staff caller."""
    data = dict(launch_status())
    try:
        from app.core.launch.readiness import readiness_document

        full = readiness_document()
    except Exception as exc:  # noqa: BLE001 - the gate document must always answer
        logger.warning(f"launch readiness unavailable: {type(exc).__name__}")
        full = None
    readiness = full or {}
    data["readiness"] = (full if staff else _public_readiness(full)) if full is not None else None
    data["tier"] = readiness.get("tier", "full")
    if staff:
        data["available_formats"] = readiness.get("available_formats", [])
        data["locked_formats"] = readiness.get("locked_formats", [])
    else:
        data["available_formats"] = _public_formats(readiness.get("available_formats"), locked=False)
        data["locked_formats"] = _public_formats(readiness.get("locked_formats"), locked=True)
    data["phase"] = "public" if data.get("public_access") else "private_beta"
    data["beta"] = {
        "request_endpoint": "/api/v1/beta/request",
        "signup_for_approved_emails": not data.get("features", {}).get("signup", False),
    }
    return data


@router.get("/launch/status", summary="Get non-sensitive launch capabilities")
def get_launch_status(request: Request):
    return utils.get_response(200, build_launch_status(staff=_caller_is_staff(request)))
