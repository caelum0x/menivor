"""Trends HTTP facade — score + rank trending sounds/hashtags (P10).

DB-free router over ``trends.scoring``: the client submits observed usage-count
series (from the ingestion probes) and gets opportunity-scored, ranked trends to
build to before they peak. MPT envelope + :class:`HttpException`.
"""

from __future__ import annotations

from fastapi import Request
from pydantic import BaseModel, Field
from typing import Literal

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

# Guarded persistence layer — the observe/recommended endpoints degrade to 503
# when the DB layer is absent (the rank endpoint stays DB-free).
try:
    from app.core.api_dependencies import get_session, require_database as _require_db
    from app.domains.trends.repository import TrendRepository
    from app.models.db.trends import DiffusionForecastRecord, TrendObservation

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _DB_IMPORT_ERROR = exc

# Auth is shared by persistent forecast and pull routes. Keep it independent of
# the optional provider layer so a disabled scraper cannot disable forecasting.
try:
    from app.core.auth import resolve_principal

    _AUTH_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _AUTH_IMPORT_ERROR = exc

# Guarded pull layer — the NEW POST /trends/pull route enqueues a scrape job. The
# existing rank/observe/recommended/forecast endpoints do NOT depend on it.
try:
    from app.domains.trends.providers import consent as _pull_consent

    _PULL_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _PULL_IMPORT_ERROR = exc

# ``Job.kind`` discriminator + spend reason for a trend-pull ingestion job.
_TRENDS_PULL_KIND: str = "trends_pull"
_TRENDS_PULL_DEBIT_REASON: str = "trends_pull_debit"


def _trends_pull_cost() -> int:
    """Credit cost of one pull (env ``TRENDS_PULL_COST``, default 1)."""
    import os

    try:
        return max(0, int(os.getenv("TRENDS_PULL_COST") or 1))
    except ValueError:
        return 1


router = new_router()


class TrendIn(BaseModel):
    trend_id: str
    kind: str = "sound"
    counts: list[int] = Field(default_factory=list, max_length=365)
    label: str = ""


class RankBody(BaseModel):
    trends: list[TrendIn] = Field(default_factory=list, max_length=500)
    limit: int = Field(default=10, ge=1, le=100)


class DiffusionNodeIn(BaseModel):
    node_id: str = Field(min_length=1, max_length=80)
    audience_size: int = Field(ge=0, le=1_000_000_000)
    label: str = Field(default="", max_length=120)


class DiffusionEdgeIn(BaseModel):
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    probability: float = Field(ge=0, le=1)


class DiffusionBody(BaseModel):
    trend_observation_id: str = Field(min_length=1, max_length=32)
    content_type: Literal["short_video", "tutorial", "product_demo", "commentary"] = "short_video"
    nodes: list[DiffusionNodeIn] = Field(min_length=1, max_length=100)
    edges: list[DiffusionEdgeIn] = Field(default_factory=list, max_length=500)
    seeds: list[str] = Field(min_length=1, max_length=20)
    steps: int = Field(default=6, ge=1, le=20)


def _score_to_dict(s) -> dict:
    return {
        "trend_id": s.trend_id, "velocity": s.velocity, "acceleration": s.acceleration,
        "saturation": s.saturation, "opportunity": s.opportunity, "phase": s.phase,
        "recommend": s.recommend,
    }


@router.post("/trends/rank", summary="Score + rank trends by opportunity")
def rank(request: Request, body: RankBody):
    """Rank observed trends (recommended, highest-opportunity first)."""
    request_id = base.get_task_id(request)
    from app.domains.trends.scoring import TrendSignal, rank_trends

    if not body.trends:
        raise HttpException(task_id=request_id, status_code=422, message=f"{request_id}: trends required")
    signals = [TrendSignal(t.trend_id, t.kind, tuple(t.counts), t.label) for t in body.trends]
    ranked = rank_trends(signals, limit=body.limit)
    return utils.get_response(200, {"trends": [_score_to_dict(s) for s in ranked]})


@router.post("/trends/diffusion-forecast", summary="Forecast expected audience diffusion")
def diffusion_forecast(request: Request, body: DiffusionBody):
    """Persist a caller-owned forecast against an exact observed trend row."""
    request_id = base.get_task_id(request)
    if _DB_IMPORT_ERROR is not None or _AUTH_IMPORT_ERROR is not None:
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: diffusion forecast persistence unavailable",
        )
    _require_db(request_id)
    from app.domains.trends.diffusion import DiffusionEdge, DiffusionNode, forecast_diffusion

    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        observation = session.get(TrendObservation, body.trend_observation_id)
        if observation is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: trend observation not found",
            )
        try:
            result = forecast_diffusion(
                tuple(DiffusionNode(node.node_id, node.audience_size, node.label) for node in body.nodes),
                tuple(DiffusionEdge(edge.source, edge.target, edge.probability) for edge in body.edges),
                tuple(body.seeds),
                steps=body.steps,
            )
        except ValueError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=422,
                message=f"{request_id}: {exc}",
            ) from exc

        assumptions = {
            "nodes": [node.model_dump() for node in body.nodes],
            "edges": [edge.model_dump() for edge in body.edges],
            "seeds": list(body.seeds),
            "steps": body.steps,
        }
        row = DiffusionForecastRecord(
            user_id=user.id,
            trend_observation_id=observation.id,
            content_type=body.content_type,
            model=str(result["model"]),
            assumptions=assumptions,
            result=result,
        )
        session.add(row)
        session.flush()
        return utils.get_response(
            200,
            {
                **result,
                "forecast_id": row.id,
                "content_type": row.content_type,
                "trend": {
                    "observation_id": observation.id,
                    "trend_id": observation.trend_id,
                    "kind": observation.kind,
                    "label": observation.label,
                    "observed_at": observation.observed_at.isoformat()
                    if observation.observed_at is not None
                    else None,
                },
            },
        )


def _obs_view(row) -> dict:
    return {
        "id": row.id, "trend_id": row.trend_id, "kind": row.kind, "label": row.label,
        "opportunity": row.opportunity_bps / 10000.0, "saturation": row.saturation_bps / 10000.0,
        "phase": row.phase, "recommend": row.recommend,
    }


@router.post("/trends/observe", summary="Record observed trends into the durable feed")
def observe(request: Request, body: RankBody):
    """Score + persist each observed trend (append-only) for the recommended feed.

    The feed is shared by every user, so writes are operator-only (the static
    app ``x-api-key``); users contribute through the consent-gated ``/trends/pull``.
    """
    request_id = base.get_task_id(request)
    from app.controllers.v1.base import matches_static_app_key

    if not matches_static_app_key(base.get_api_key(request)):
        raise HttpException(task_id=request_id, status_code=403,
                            message=f"{request_id}: only the operator can write the shared trends feed")
    if _DB_IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: trends persistence unavailable")
    _require_db(request_id)
    if not body.trends:
        raise HttpException(task_id=request_id, status_code=422, message=f"{request_id}: trends required")
    from app.domains.trends.scoring import TrendSignal

    with get_session() as session:
        repo = TrendRepository(session)
        rows = [
            repo.record(TrendSignal(t.trend_id, t.kind, tuple(t.counts), t.label))
            for t in body.trends
        ]
        return utils.get_response(200, {"observed": [_obs_view(r) for r in rows]})


@router.get("/trends/recommended", summary="Latest recommended (rising, not-peaked) trends")
def recommended(request: Request, limit: int = 20):
    """The durable trends feed: highest-opportunity recommended trends first."""
    request_id = base.get_task_id(request)
    if _DB_IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: trends persistence unavailable")
    _require_db(request_id)
    with get_session() as session:
        rows = TrendRepository(session).recommended(limit=max(1, min(100, limit)))
        return utils.get_response(200, {"trends": [_obs_view(r) for r in rows]})


class PullBody(BaseModel):
    """Request to ingest (scrape) a trend into the durable feed."""

    target: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="hashtag")
    max_posts: int = Field(default=50, ge=1, le=500)


@router.post("/trends/pull", summary="Enqueue a ToS-gated trend scrape into the feed")
def pull(request: Request, body: PullBody):
    """Validate the target against the allowlist + consent, then enqueue a job.

    ADDITIVE route: it does not touch the existing rank/observe/recommended
    handlers. The pull itself (provider scrape → score → persist) runs on the
    worker via :func:`app.workers.tasks.run_trends_pull`; here we only enforce the
    MANDATORY ToS gate, debit the pull cost, create ``Job(kind='trends_pull')``,
    and enqueue it. The debit is committed before enqueue so a scrape can always
    be reconciled/refunded on failure (mirrors the B-roll money path).
    """
    request_id = base.get_task_id(request)
    if (
        _DB_IMPORT_ERROR is not None
        or _AUTH_IMPORT_ERROR is not None
        or _PULL_IMPORT_ERROR is not None
    ):
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: trends pull unavailable")
    _require_db(request_id)

    target = body.target.strip()
    kind = (body.kind or "hashtag").strip().lower()
    if not _pull_consent.is_target_allowed(
        _pull_consent.TRENDING_TARGET if kind in ("trending", "fyp") else target
    ):
        raise HttpException(task_id=request_id, status_code=403,
                            message=f"{request_id}: target is not on the scraping allowlist")

    from app.models.db.repositories import CreditRepository, JobRepository

    cost = _trends_pull_cost()
    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        if not _pull_consent.is_consent_granted(session, user.id):
            raise HttpException(
                task_id=request_id, status_code=403,
                message=f"{request_id}: trend scraping consent has not been granted",
            )
        params = {
            "_correlation_id": request_id,
            "target": target,
            "kind": kind,
            "max_posts": int(body.max_posts),
            "credits_cost": cost,
            "workspace_id": None,
        }
        job = JobRepository(session).create(
            user_id=user.id, kind=_TRENDS_PULL_KIND, params=params
        )
        try:
            CreditRepository(session).debit(user.id, cost, job.id, _TRENDS_PULL_DEBIT_REASON)
        except ValueError as exc:
            raise HttpException(
                task_id=request_id, status_code=402,
                message=f"{request_id}: insufficient credits: {exc}",
            )
        gid = job.id

    try:
        from app.workers.tasks import run_trends_pull

        run_trends_pull.apply_async(
            args=[{"job_id": gid, "request_id": request_id}],
            headers={"correlation_id": request_id},
        )
    except Exception as exc:  # noqa: BLE001 - enqueue failure must not orphan a paid job
        from app.domains.trends.service import refund_trends_pull

        try:
            with get_session() as session:
                JobRepository(session).mark_failed(gid, "enqueue", "failed to enqueue")
        except Exception:  # noqa: BLE001 - best-effort
            pass
        refund_trends_pull(gid)
        raise HttpException(task_id=request_id, status_code=502,
                            message=f"{request_id}: failed to enqueue trend pull") from exc

    return utils.get_response(200, {"job_id": gid, "target": target, "kind": kind, "state": "processing"})
