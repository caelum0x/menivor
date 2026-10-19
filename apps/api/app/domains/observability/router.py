"""Prometheus scrape endpoint — ``GET /metrics``.

Exposes the in-process metrics registry (``app.telemetry.metrics``) in the
Prometheus text-exposition format so the OTel collector / Prometheus can scrape
the series the SLO + alert rules reference (notably the wallet
success-only-billing invariant). Unauthenticated by design (a scrape target) and
returns ``text/plain``; it carries no user data — only aggregate counters.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import PlainTextResponse

from app.controllers.v1.base import new_router

router = new_router()

_PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@router.get("/metrics", summary="Prometheus metrics exposition", include_in_schema=False)
def metrics(request: Request) -> PlainTextResponse:
    from app.telemetry.metrics import render_metrics

    return PlainTextResponse(render_metrics(), media_type=_PROM_CONTENT_TYPE)
