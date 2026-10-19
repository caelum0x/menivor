"""Apps shelf service (MH8): one input screen per app, a price first (MG3), then one run.

* ``plan`` apps answer with the normal create call (the create flow prices it
  and charges it, like a preset tile).
* ``image_edit`` apps are priced in AI-video credits at 3x the recorded image
  price times the number of images, debited at start, refunded once on failure.
* ``local`` apps cost the standard credits in their file (0 for the free tools,
  which have a per-user daily cap instead).
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import catalog, runners

JOB_KIND = "app_run"
TASK_STATE_COMPLETE = 1
TASK_STATE_FAILED = -1
TASK_STATE_PROCESSING = 4
DEBIT_REASON = "app_run"
REFUND_REASON = "app_run_refund"
MAX_TEXT = 300


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _app(app_id: str) -> catalog.App:
    app = catalog.get(app_id)
    if app is None or not catalog.visible(app):
        raise AppError(404, "not_found", "app not found")
    return app


def app_view(app: catalog.App) -> dict[str, Any]:
    return {"id": app.id, "name": app.name, "blurb": app.blurb, "input": app.input,
            "preview_url": _public_preview(catalog.previews().get(app.id, "")), "price": public_price(app)}


_INTERNAL_PRICE_KEYS = ("price_source", "price_date", "provider_usd")


def public_price(app: catalog.App) -> dict[str, Any]:
    """The price a client sees: credits only (sources name vendors and stay server-side)."""
    return {k: v for k, v in price_hint(app).items() if k not in _INTERNAL_PRICE_KEYS}


def _public_preview(key: str) -> str:
    # Same public media origin as the preset shelf (media.menivor.com unless overridden).
    from app.domains.presets_hub.previews import media_base

    base = media_base()
    return f"{base}/{key.lstrip('/')}" if base and key else ""


def shelf() -> list[dict[str, Any]]:
    # No placeholder tiles: an app is listed only with a real preview URL.
    views = (app_view(app) for app in catalog.all_apps() if catalog.visible(app))
    return [view for view in views if view["preview_url"]]


def _images(app: catalog.App) -> int:
    return len(runners.edit_prompts(app.edit, "x")) if app.runner == "image_edit" else 0


def price_hint(app: catalog.App) -> dict[str, Any]:
    """The price a tile shows before any input (plan apps defer to the create quote)."""
    from app.services.billing.premium_credits import ai_video_credits_for_usd

    price = app.price
    if app.runner == "plan":
        return {"credit_kind": "standard", "credits": None, "priced_by": "create"}
    if app.runner == "image_edit":
        usd = round(float(price["per_image_usd"]) * _images(app), 4)
        return {"credit_kind": "ai_video", "credits": max(1, ai_video_credits_for_usd(usd)), "provider_usd": usd,
                "price_source": price["source"], "price_date": price["date"]}
    return {"credit_kind": "standard", "credits": int(price.get("credits") or 0),
            "daily_cap": price.get("daily_cap")}


def _clean(text: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(text or "").split())[:limit]


def _require_owned(session: Session, user_id: str, key: str) -> None:
    from app.domains.media.service import MediaDomainError, require_owned_asset

    try:
        require_owned_asset(session, user_id=user_id, key=key)
    except MediaDomainError as exc:
        raise AppError(403, "not_yours", "that file is not in your uploads") from exc


def validate_inputs(session: Session, user_id: str, app: catalog.App, inputs: Mapping[str, Any]) -> dict[str, Any]:
    kind = app.input.get("kind")
    clean: dict[str, Any] = {}
    need_image = kind in {"image", "image_text", "image_choice", "two_images"}
    if need_image:
        key = _clean(inputs.get("image_key"), 512)
        if not key:
            raise AppError(400, "image_required", "add a photo first")
        _require_owned(session, user_id, key)
        clean["image_key"] = key
    if kind == "two_images":
        key2 = _clean(inputs.get("image_key_2"), 512)
        if not key2:
            raise AppError(400, "image_required", "add the second photo")
        _require_owned(session, user_id, key2)
        clean["image_key_2"] = key2
    if kind in {"video_music", "video_text"}:
        video = _clean(inputs.get("video_key"), 512)
        if not video:
            raise AppError(400, "video_required", "add your clip first")
        _require_owned(session, user_id, video)
        clean["video_key"] = video
    if kind == "video_music":
        from app.services.music import get_music_path

        music = _clean(inputs.get("music_id"), 120)
        if not get_music_path(music):
            raise AppError(400, "music_required", "pick a track from the library")
        clean["music_id"] = music
    if kind == "image_text":
        text = _clean(inputs.get("text"))
        if not text:
            raise AppError(400, "text_required", "describe the scene")
        clean["text"] = text
    if kind == "image_choice":
        choice = _clean(inputs.get("choice"), 60)
        if choice not in app.input.get("choices", []):
            raise AppError(400, "choice_required", "pick one of the options")
        clean["text"] = choice
    if kind == "video_text":
        clean["text"] = _clean(inputs.get("text"))
    if kind in {"link", "topic", "text"}:
        subject = _clean(inputs.get("text") or inputs.get("subject"), 600)
        if not subject:
            raise AppError(400, "text_required", "type a topic or paste a link")
        clean["text"] = subject
    return clean


def quote(session: Session, user_id: str, app_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    app = _app(app_id)
    validate_inputs(session, user_id, app, inputs)
    return {"app_id": app.id, **public_price(app)}


def plan(session: Session, user_id: str, app_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """The create call for a ``plan`` app (the create flow prices and charges it)."""
    from app.domains.presets_hub import service as presets

    app = _app(app_id)
    if app.runner != "plan":
        raise AppError(400, "not_a_plan_app", "this app runs here; start it instead")
    clean = validate_inputs(session, user_id, app, inputs)
    try:
        params = presets.subject_params(clean["text"])
    except presets.PresetInputError as exc:
        raise AppError(400, "text_required", str(exc)) from exc
    if app.plan.get("style"):
        params["style"] = app.plan["style"]
    return {"route": app.plan.get("route", "jobs"), "body": {"params": params, "variants": 1}, "app_id": app.id}


def used_today(session: Session, user_id: str, app_id: str) -> int:
    from app.models.db.models import Job

    midnight = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    rows = session.execute(select(Job.params).where(
        Job.user_id == user_id, Job.kind == JOB_KIND, Job.created_at >= midnight)).scalars().all()
    return sum(1 for params in rows if dict(params or {}).get("app_id") == app_id)


def start(session: Session, user_id: str, app_id: str, inputs: Mapping[str, Any], quoted_credits: int) -> Any:
    from app.models.db.repositories import CreditRepository, JobRepository
    from app.services.billing import premium_credits as pc

    app = _app(app_id)
    if app.runner == "plan":
        raise AppError(400, "plan_app", "this app starts from the create flow")
    clean = validate_inputs(session, user_id, app, inputs)
    price = price_hint(app)
    if int(quoted_credits) != int(price["credits"] or 0):
        raise AppError(409, "quote_changed", "the price changed; check the new price first")
    cap = price.get("daily_cap")
    if cap is not None and used_today(session, user_id, app.id) >= int(cap):
        raise AppError(429, "daily_cap", f"you can use this {cap} times a day; more tomorrow")
    params = {"app_id": app.id, "app_version": app.version, "inputs": clean, "credit_kind": price["credit_kind"],
              "credits": int(price["credits"] or 0), "credits_cost": 0, "workspace_id": None}
    if price["credit_kind"] == "standard":
        params["credits_cost"] = int(price["credits"] or 0)
    else:
        params["ai_video_credits"] = int(price["credits"])
    job = JobRepository(session).create(user_id=user_id, kind=JOB_KIND, params=params)
    if params["credits_cost"]:
        try:
            CreditRepository(session).debit(user_id, params["credits_cost"], job.id, DEBIT_REASON)
        except ValueError as exc:
            raise AppError(402, "credits_required", "not enough credits for this app") from exc
    if params.get("ai_video_credits"):
        try:
            pc.debit(session, user_id, pc.KIND_AI_VIDEO, params["ai_video_credits"], f"{pc.DEBIT_REASON}:{job.id}",
                     job.id)
        except pc.InsufficientPremiumCredits as exc:
            raise AppError(402, "ai_video_credits_required",
                           f"this needs {exc.needed} AI-video credits; you have {exc.available}") from exc
    job.state = TASK_STATE_PROCESSING
    session.flush()
    return job


def refund(session: Session, job: Any) -> dict[str, int]:
    from app.domains.reels.refunds import refund_latest_debit_once_in_session
    from app.services.billing import premium_credits as pc

    params = dict(job.params or {})
    if params.get("_refunded"):
        return {"standard_credits": 0, "ai_video_credits": 0}
    standard = int(refund_latest_debit_once_in_session(session, job.id, REFUND_REASON) or 0)
    ai = int(params.get("ai_video_credits") or 0)
    if ai:
        pc.grant(session, str(job.user_id), pc.KIND_AI_VIDEO, ai, f"{pc.REFUND_REASON}:{job.id}", job.id)
    job.params = {**params, "_refunded": True}
    session.flush()
    return {"standard_credits": standard, "ai_video_credits": ai}


def job_view(job: Any) -> dict[str, Any]:
    from app.domains.gallery.service import media_url

    params = dict(job.params or {})
    return {"job_id": job.id, "app_id": params.get("app_id"), "state": job.state,
            "outputs": [media_url(k) for k in params.get("_outputs") or []], "result": params.get("_result"),
            "error": job.error or "", "refunded": bool(params.get("_refunded"))}


__all__ = ["AppError", "JOB_KIND", "app_view", "job_view", "plan", "price_hint", "quote", "refund", "shelf", "start",
           "validate_inputs"]
