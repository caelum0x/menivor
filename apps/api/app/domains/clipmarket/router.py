"""Clipping marketplace HTTP surface (P11).

    POST /clipmarket/campaigns                  brand creates a CPM campaign (budget escrowed)
    GET  /clipmarket/campaigns                  list active campaigns (clipper discovery)
    GET  /clipmarket/me/campaigns               the caller's own campaigns (any status)
    GET  /clipmarket/me/submissions             the caller's own submissions
    GET  /clipmarket/campaigns/{id}/submissions a campaign's submissions (brand only)
    POST /clipmarket/campaigns/{id}/status      pause / resume / end (end releases escrow)
    POST /clipmarket/campaigns/{id}/submit      clipper submits a clip
    POST /clipmarket/submissions/{id}/review    brand attests views -> fraud-gate + payout
    POST /clipmarket/submissions/{id}/reject    brand rejects without payout

Auth + owner-scoping + DB reuse the shared jobs-controller helpers. Import-safe:
the persistence layer is guarded (clean 503 when absent).
"""

from __future__ import annotations

from fastapi import Path, Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

try:
    from app.core.api_dependencies import (
        get_session,
        require_database as _require_db,
        resolve_principal as _resolve_user,
    )
    from app.domains.clipmarket import service as svc
    from app.domains.clipmarket.payout import ViewSignals
    from app.models.db.clipmarket import ClipCampaign

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _IMPORT_ERROR = exc

router = new_router()


class CampaignBody(BaseModel):
    title: str = Field(default="", max_length=200)
    cpm_micros: int = Field(..., gt=0)
    budget_micros: int = Field(..., gt=0)
    min_views: int = Field(default=0, ge=0)


class SubmitBody(BaseModel):
    clip_url: str = Field(..., max_length=500)


class ReviewBody(BaseModel):
    views: int = Field(..., ge=0)
    # Pay a submission the fraud gate held, after the brand checked it manually.
    override_hold: bool = False
    velocity_zscore: float = 0.0
    avg_watch_frac: float = 0.0
    engagement_rate: float = 0.0
    geo_concentration: float = 0.0
    retention_cliff: float = 0.0


def _error(exc: Exception, request_id: str) -> HttpException:
    return HttpException(
        task_id=request_id,
        status_code=int(getattr(exc, "status_code", 422) or 422),
        message=f"{request_id}: {exc}",
    )


def _guard(request_id: str) -> None:
    if _IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: clipmarket layer unavailable: {_IMPORT_ERROR}")


def _campaign_view(c) -> dict:
    return {
        "id": c.id, "brand_id": c.brand_id, "title": c.title, "cpm_micros": c.cpm_micros,
        "budget_micros": c.budget_micros, "spent_micros": c.spent_micros,
        "min_views": c.min_views, "status": c.status,
    }


def _submission_view(s) -> dict:
    return {
        "id": s.id, "campaign_id": s.campaign_id, "clipper_id": s.clipper_id,
        "clip_url": s.clip_url, "verified_views": s.verified_views,
        "payable_micros": s.payable_micros, "status": s.status,
        "fraud_score": s.fraud_score, "fraud_flags": s.fraud_flags,
    }


@router.post("/clipmarket/campaigns", summary="Create a CPM clipping campaign")
def create_campaign(request: Request, body: CampaignBody):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = svc.create_campaign(
                session, brand_id=user.id, cpm_micros=body.cpm_micros,
                budget_micros=body.budget_micros, title=body.title, min_views=body.min_views,
            )
        except svc.ClipmarketError as exc:
            raise _error(exc, request_id) from exc
        return utils.get_response(200, _campaign_view(row))


@router.get("/clipmarket/campaigns", summary="List active campaigns")
def list_campaigns(request: Request, limit: int = 50):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        _resolve_user(request, session, request_id)
        rows = (
            session.query(ClipCampaign)
            .filter(ClipCampaign.status == "active")
            .order_by(ClipCampaign.created_at.desc())
            .limit(max(1, min(200, limit)))
            .all()
        )
        return utils.get_response(200, {"campaigns": [_campaign_view(c) for c in rows]})


@router.post("/clipmarket/campaigns/{campaign_id}/status", summary="Pause / resume / end a campaign")
def set_status(request: Request, body: dict, campaign_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        status = str((body or {}).get("status", "")).strip()
        try:
            row = svc.set_campaign_status(
                session, campaign_id=campaign_id, brand_id=user.id, status=status
            )
        except svc.ClipmarketError as exc:
            raise _error(exc, request_id) from exc
        return utils.get_response(200, _campaign_view(row))


@router.post("/clipmarket/campaigns/{campaign_id}/submit", summary="Submit a clip to a campaign")
def submit(request: Request, body: SubmitBody, campaign_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = svc.submit_clip(session, campaign_id=campaign_id, clipper_id=user.id, clip_url=body.clip_url)
        except svc.ClipmarketError as exc:
            raise _error(exc, request_id) from exc
        return utils.get_response(200, _submission_view(row))


@router.post("/clipmarket/submissions/{submission_id}/review", summary="Review a submission (fraud-gate + payout)")
def review(request: Request, body: ReviewBody, submission_id: str = Path(...)):
    """Brand-only: attest the clip's verified views, fraud-gate it, and pay out.

    The views come from the paying brand (never the clipper), so a clipper can
    not inflate their own payout; an approved payout moves from the campaign
    escrow to the clipper's wallet in the same transaction.
    """
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        payload = body.model_dump()
        override_hold = bool(payload.pop("override_hold", False))
        signals = ViewSignals(**payload)
        try:
            row = svc.review_submission(
                session,
                submission_id=submission_id,
                reviewer_id=str(user.id),
                signals=signals,
                override_hold=override_hold,
            )
        except svc.ClipmarketError as exc:
            raise _error(exc, request_id) from exc
        return utils.get_response(200, _submission_view(row))


@router.post("/clipmarket/submissions/{submission_id}/reject", summary="Reject a submission")
def reject(request: Request, submission_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = svc.reject_submission(
                session, submission_id=submission_id, reviewer_id=str(user.id)
            )
        except svc.ClipmarketError as exc:
            raise _error(exc, request_id) from exc
        return utils.get_response(200, _submission_view(row))


@router.get("/clipmarket/campaigns/{campaign_id}/submissions", summary="List a campaign's submissions (brand)")
def campaign_submissions(request: Request, campaign_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            rows = svc.list_campaign_submissions(
                session, campaign_id=campaign_id, brand_id=str(user.id)
            )
        except svc.ClipmarketError as exc:
            raise _error(exc, request_id) from exc
        return utils.get_response(200, {"submissions": [_submission_view(s) for s in rows]})


@router.get("/clipmarket/me/submissions", summary="List the caller's own submissions")
def my_submissions(request: Request, limit: int = 100):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = svc.list_my_submissions(session, clipper_id=str(user.id), limit=limit)
        return utils.get_response(200, {"submissions": [_submission_view(s) for s in rows]})


@router.get("/clipmarket/me/campaigns", summary="List the caller's own campaigns")
def my_campaigns(request: Request, limit: int = 100):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = svc.list_my_campaigns(session, brand_id=str(user.id), limit=limit)
        return utils.get_response(200, {"campaigns": [_campaign_view(c) for c in rows]})
