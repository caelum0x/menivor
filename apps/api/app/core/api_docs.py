"""Who may read the interactive API docs and the OpenAPI schema.

``MENIVOR_API_DOCS`` picks the mode (default ``staff``):

* ``public`` - FastAPI's normal ``/docs``, ``/redoc`` and ``/openapi.json``
  (local development only).
* ``staff``  - ``/docs`` and ``/openapi.json`` answer only a verified staff
  principal (``User.is_staff``); everyone else, including anonymous callers
  and ordinary users, gets a plain 404 so the surface does not advertise
  itself. ``/redoc`` is off.
* ``off``    - no docs routes at all.

The default is ``staff`` so a deploy that forgets the variable never publishes
the full internal route map.
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger

PUBLIC: str = "public"
STAFF: str = "staff"
OFF: str = "off"
_MODES: frozenset[str] = frozenset({PUBLIC, STAFF, OFF})
_SWAGGER_CDN: str = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5"
_NOT_FOUND = {"detail": "Not Found"}


def docs_mode() -> str:
    mode = (os.getenv("MENIVOR_API_DOCS") or STAFF).strip().lower()
    return mode if mode in _MODES else STAFF


def fastapi_docs_kwargs(mode: str) -> dict[str, str | None]:
    """``FastAPI(...)`` docs arguments: built-in routes only in public mode."""
    if mode == PUBLIC:
        return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


def _is_staff(request: Request) -> bool:
    """Whether the request resolves to a staff user (never raises)."""
    try:
        from app.core.auth.principal import resolve_principal
        from app.core.observability import request_correlation_id
        from app.models.db.base import get_session

        with get_session() as session:
            user = resolve_principal(request, session, request_correlation_id(request))
            return bool(getattr(user, "is_staff", False))
    except Exception as exc:  # noqa: BLE001 - unknown identity is not staff
        logger.debug(f"api docs: staff check failed: {type(exc).__name__}")
        return False


def _swagger_html(title: str, spec: dict) -> str:
    # The schema is inlined so the browser never needs a second authenticated
    # fetch. ``</`` is escaped so the JSON cannot close the script element.
    payload = json.dumps(spec).replace("</", "<\\/")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title} API</title>
<link rel="stylesheet" href="{_SWAGGER_CDN}/swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script src="{_SWAGGER_CDN}/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({{spec: {payload}, dom_id: "#swagger-ui"}});</script>
</body></html>"""


def install(app: FastAPI, mode: str) -> None:
    """Add the staff-only docs routes (no-op for ``public`` and ``off``)."""
    if mode != STAFF:
        return

    @app.get("/openapi.json", include_in_schema=False)
    def staff_openapi(request: Request):
        if not _is_staff(request):
            return JSONResponse(status_code=404, content=_NOT_FOUND)
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False)
    def staff_docs(request: Request):
        if not _is_staff(request):
            return JSONResponse(status_code=404, content=_NOT_FOUND)
        return HTMLResponse(_swagger_html(app.title, app.openapi()))


__all__ = ["OFF", "PUBLIC", "STAFF", "docs_mode", "fastapi_docs_kwargs", "install"]
