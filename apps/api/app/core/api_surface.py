"""Production API surface: client allowlist, staff-only rest, frozen money routes (M3.3).

``MENIVOR_API_SURFACE`` picks the mode:

* ``allowlist`` - only the routes a first-party client (web, mobile, desktop)
  or a named third party (webhooks, OAuth callbacks, the metrics scrape, the
  developer gateway) calls are public. The list is generated from the client
  code by ``tools/ops/api_surface_audit.py`` into ``api_surface_allowlist.json``
  and explained route by route in ``docs/api/ROUTE-AUDIT.md``.
  Every other route stays mounted but answers 404 to anyone who is not a
  verified staff user and is hidden from OpenAPI, so staff tools keep working
  and nothing is deleted.
  Frozen money routes (P2P wallet transfers and the Paddle, Polar, Stripe and
  iyzico webhooks) are not mounted at all.
* ``full`` - every route is public, as before M3.3.

Default (owner decision O3, "approve freeze, not delete"): ``allowlist`` when
the launch mode is ``public`` (production), ``full`` otherwise, so local
development, the internal pilot and the test suite keep the whole surface.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute

SURFACE_ENV = "MENIVOR_API_SURFACE"
ALLOWLIST = "allowlist"
FULL = "full"
_MODES = frozenset({ALLOWLIST, FULL})
ALLOWLIST_FILE = Path(__file__).with_name("api_surface_allowlist.json")

# Money surfaces frozen by O3 (not mounted under the allowlist). The code stays
# in the tree; ``MENIVOR_API_SURFACE=full`` mounts them again.
_FROZEN = (
    re.compile(r"^/api/v1/wallet/transfers(/\{[^}]+\})?$"),
    re.compile(r"^/api/v1/wallet/transfer-challenges$"),
    re.compile(r"^/api/v1/billing/webhook/(stripe|paddle|polar|iyzico)$"),
)
# Always staff-only under the allowlist, even when a client screen names them
# (the web admin console is itself staff-only).
_STAFF_ONLY = (re.compile(r"^/api/v1/admin(/|$)"),)
_IGNORED_METHODS = frozenset({"HEAD", "OPTIONS"})


def surface_mode() -> str:
    raw = (os.getenv(SURFACE_ENV) or "").strip().lower()
    if raw in _MODES:
        return raw
    from app.core.launch.policy import launch_mode

    return ALLOWLIST if launch_mode() == "public" else FULL


def is_frozen(path: str) -> bool:
    return any(p.match(path) for p in _FROZEN)


def is_staff_only(path: str) -> bool:
    return any(p.match(path) for p in _STAFF_ONLY)


@lru_cache(maxsize=1)
def load_allowlist() -> frozenset[str]:
    """The generated ``METHOD path`` allowlist (empty when the file is missing)."""
    try:
        data = json.loads(ALLOWLIST_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    return frozenset(str(r) for r in data.get("routes", []))


def _is_staff(request: Request) -> bool:
    from app.core.api_docs import _is_staff as docs_is_staff  # same check as the staff-only docs

    return docs_is_staff(request)


def require_staff(request: Request) -> None:
    """404 (not 403) for non-staff, so a hidden route does not advertise itself."""
    if not _is_staff(request):
        raise HTTPException(status_code=404, detail="Not Found")


def _route_methods(route: APIRoute) -> set[str]:
    return set(route.methods or ()) - _IGNORED_METHODS


def _clone(route: APIRoute, *, staff_only: bool) -> dict:
    """Keyword arguments that rebuild ``route`` (optionally staff-only and hidden)."""
    deps = list(route.dependencies)
    if staff_only:
        deps.append(Depends(require_staff))
    return dict(
        path=route.path,
        endpoint=route.endpoint,
        response_model=route.response_model,
        status_code=route.status_code,
        tags=route.tags,
        dependencies=deps,
        summary=route.summary,
        description=route.description,
        response_description=route.response_description,
        responses=route.responses,
        deprecated=route.deprecated,
        methods=sorted(route.methods or ()),
        operation_id=route.operation_id,
        response_model_include=route.response_model_include,
        response_model_exclude=route.response_model_exclude,
        response_model_by_alias=route.response_model_by_alias,
        response_model_exclude_unset=route.response_model_exclude_unset,
        response_model_exclude_defaults=route.response_model_exclude_defaults,
        response_model_exclude_none=route.response_model_exclude_none,
        include_in_schema=False if staff_only else route.include_in_schema,
        response_class=route.response_class,
        name=route.name,
        callbacks=route.callbacks,
        openapi_extra=route.openapi_extra,
        generate_unique_id_function=route.generate_unique_id_function,
    )


def apply_surface(full: APIRouter, mode: str | None = None, allow: frozenset[str] | None = None) -> APIRouter:
    """Return the router for ``mode``; ``full`` is returned unchanged in full mode."""
    mode = mode or surface_mode()
    if mode == FULL:
        return full
    allow = load_allowlist() if allow is None else allow
    out = APIRouter()
    for route in full.routes:
        if not isinstance(route, APIRoute):
            out.routes.append(route)
            continue
        if is_frozen(route.path):
            continue
        public = not is_staff_only(route.path) and all(
            f"{m} {route.path}" in allow for m in _route_methods(route)
        )
        if public:
            out.routes.append(route)
        else:
            out.add_api_route(**_clone(route, staff_only=True))
    return out


def surface_report(router: APIRouter) -> dict:
    """Counts for ops and tests: public paths, staff-only routes."""
    public_paths, staff = set(), 0
    for r in router.routes:
        if isinstance(r, APIRoute):
            if r.include_in_schema:
                public_paths.add(r.path)
            else:
                staff += 1
    return {"public_paths": len(public_paths), "staff_only_routes": staff}


__all__ = [
    "ALLOWLIST", "FULL", "SURFACE_ENV", "apply_surface", "is_frozen", "is_staff_only", "load_allowlist",
    "require_staff", "surface_mode", "surface_report",
]
