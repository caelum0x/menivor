"""Stable correlation ids at the public HTTP edge."""

from __future__ import annotations

import re
from uuid import uuid4

from fastapi import Request, Response

CORRELATION_HEADER = "X-Correlation-ID"
_LEGACY_HEADER = "x-task-id"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def request_correlation_id(request: Request) -> str:
    """Return one safe id for the full request, accepting the public header."""
    state = getattr(request, "state", None)
    existing = str(getattr(state, "correlation_id", "") or "")
    if existing:
        return existing
    candidate = str(
        request.headers.get(CORRELATION_HEADER)
        or request.headers.get(_LEGACY_HEADER)
        or ""
    ).strip()
    correlation_id = candidate if _SAFE_ID.fullmatch(candidate) else uuid4().hex
    if state is not None:
        state.correlation_id = correlation_id
    return correlation_id


async def correlation_middleware(request: Request, call_next) -> Response:
    """Make correlation available to handlers and return it on every response."""
    correlation_id = request_correlation_id(request)
    response = await call_next(request)
    response.headers[CORRELATION_HEADER] = correlation_id
    return response
