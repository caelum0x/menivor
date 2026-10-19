"""Character turnaround sheets: one image, three views, the identity reference for every shot.

The Very ___ Time method starts each recurring character with a turnaround sheet
(front, side profile and back, full body, neutral A-pose, flat blue-grey
background). Later stills and video shots attach that sheet as the identity
reference, so the face, build and clothes hold across a whole series.

* :func:`sheet_prompt` writes the sheet prompt (pure).
* :func:`generate_sheet` makes the sheet (house-paid image lane), stores it as a
  caller-owned ``uploads/sheets/<hex>.png`` asset and, for a saved character,
  binds it as the character's ``sheet`` reference (the existing identity lock).
  With existing references, the sheet is made by a reference image model so it
  matches them.
* :func:`sheet_key` is the newest sheet bound to a character.
* ``POST /characters/{character_id}/turnaround`` prices first: it debits
  ``CHARACTER_SHEET_CREDITS`` (default 1) standard credits before the image call
  and gives them back once if the sheet cannot be made.
"""

from __future__ import annotations

import io
import os
import uuid
from typing import Any, Callable, Sequence

from fastapi import Path, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

router = new_router()

SHEET_MODEL_ENV = "CHARACTER_SHEET_MODEL"
SHEET_REFERENCE_MODEL_ENV = "CHARACTER_SHEET_REFERENCE_MODEL"
SHEET_CREDITS_ENV = "CHARACTER_SHEET_CREDITS"
DEFAULT_SHEET_MODEL = "ideogram/ideogram-v3"
DEFAULT_SHEET_REFERENCE_MODEL = "bytedance-seed/seedream-4.5-edit"
DEFAULT_SHEET_CREDITS = 1
SHEET_SIZE = (1536, 1024)
SHEET_PREFIX = "uploads/sheets"
SHEET_ROLE = "sheet"
JOB_KIND = "character_sheet"
DEBIT_REASON = "character_sheet"
REFUND_REASON = "character_sheet_refund"
RATE_LIMIT = 6
RATE_WINDOW_S = 3600
MAX_REFERENCES = 3
MAX_STYLE = 200
TASK_STATE_COMPLETE = 1
TASK_STATE_FAILED = -1

SHEET_NEGATIVE = (
    "different person between views", "extra limbs", "extra fingers", "text", "captions", "labels",
    "watermark", "logo", "flags", "busy background", "props covering the body", "cropped feet",
)


class SheetError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def sheet_model() -> str:
    return (os.getenv(SHEET_MODEL_ENV) or "").strip() or DEFAULT_SHEET_MODEL


def sheet_reference_model() -> str:
    return (os.getenv(SHEET_REFERENCE_MODEL_ENV) or "").strip() or DEFAULT_SHEET_REFERENCE_MODEL


def sheet_credits() -> int:
    try:
        return max(0, int(os.getenv(SHEET_CREDITS_ENV) or DEFAULT_SHEET_CREDITS))
    except ValueError:
        return DEFAULT_SHEET_CREDITS


def _flat(text: Any, limit: int = 300) -> str:
    return " ".join(str(text or "").split())[:limit]


def sheet_prompt(descriptors: Sequence[str], *, style: str = "", wearing: str = "") -> tuple[str, str]:
    """The turnaround sheet prompt and its negative prompt."""
    who = ", ".join(d for d in (_flat(x, 200) for x in descriptors or ()) if d) or "one recurring character"
    parts = [
        "Character turnaround sheet: the same character shown three times side by side, full body, "
        "front view, side profile view and back view, neutral A-pose, arms slightly away from the body",
        "flat blue-grey studio background, even light, nothing else in frame",
        f"Character: {who}",
    ]
    if wearing:
        parts.append(f"wearing {_flat(wearing, 300)}, identical in all three views")
    if style:
        parts.append(_flat(style, MAX_STYLE))
    parts.append("Same face, hair, build and clothes in every view. No text other than the garment print. "
                 "No logos, no flags")
    return ". ".join(parts) + ".", ", ".join(SHEET_NEGATIVE)


# --------------------------------------------------------------------------- #
# Default seams (tests inject their own)
# --------------------------------------------------------------------------- #
def _default_image(prompt: str, *, model_id: str, reference_urls: Sequence[str] = (), negative: str = "") -> bytes:
    from app.domains.gateway.house_image import house_image

    return house_image(prompt, model_id=model_id, reference_urls=reference_urls, negative=negative,
                       correlation_id="character-sheet")


def _default_upload(key: str, data: bytes, content_type: str) -> None:
    from app.platform.storage.r2 import get_r2_client

    get_r2_client().upload_bytes(key, data, content_type=content_type)


def _default_presign(key: str) -> str:
    from app.platform.storage.r2 import get_r2_client

    return get_r2_client().presign_get(key)


def fit_sheet(image: bytes) -> bytes:
    """Cover-fit any image to a 1536x1024 landscape PNG."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(image)) as source:
        fitted = ImageOps.fit(source.convert("RGB"), SHEET_SIZE, Image.LANCZOS)
        out = io.BytesIO()
        fitted.save(out, format="PNG")
        return out.getvalue()


def _register_owned(session: Any, user_id: str, key: str, size: int) -> None:
    from app.domains.media.repository import MediaRepository

    repo = MediaRepository(session)
    if repo.reserve_owned_upload(user_id, key, content_type="image/png", size=size,
                                 filename=key.rsplit("/", 1)[-1]) is None:
        raise SheetError(409, "key_collision", "the sheet could not be stored; try again")
    repo.register_owned_upload(user_id, key, "image")


def generate_sheet(session: Any, *, user_id: str, descriptors: Sequence[str], style: str = "", wearing: str = "",
                   character_id: str | None = None, reference_keys: Sequence[str] = (),
                   image_fn: Callable[..., bytes] | None = None,
                   upload_fn: Callable[[str, bytes, str], None] | None = None,
                   presign_fn: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Make, store and (for a saved character) bind a turnaround sheet."""
    from app.domains.media.service import MediaDomainError, require_owned_asset

    prompt, negative = sheet_prompt(descriptors, style=style, wearing=wearing)
    keys = [str(k) for k in reference_keys or () if str(k or "").startswith("uploads/")][:MAX_REFERENCES]
    for key in keys:
        try:
            require_owned_asset(session, user_id=user_id, key=key)
        except MediaDomainError as exc:
            raise SheetError(403, "reference_not_owned", "a reference image is not one of your uploads") from exc
    presign = presign_fn or _default_presign
    urls = [presign(k) for k in keys]
    model_id = sheet_reference_model() if urls else sheet_model()
    if urls:
        prompt = ("The reference images show the character: copy the face, hair, build and clothes only; "
                  "do not copy their backgrounds or poses. " + prompt)
    image = (image_fn or _default_image)(prompt, model_id=model_id, reference_urls=urls, negative=negative)
    png = fit_sheet(image)
    key = f"{SHEET_PREFIX}/{uuid.uuid4().hex}.png"
    (upload_fn or _default_upload)(key, png, "image/png")
    _register_owned(session, user_id, key, len(png))
    bound = False
    if character_id:
        from app.domains.characters.references_service import bind_reference

        bind_reference(session, user_id=user_id, character_id=character_id, r2_key=key, role=SHEET_ROLE,
                       content_type="image/png", width=SHEET_SIZE[0], height=SHEET_SIZE[1])
        bound = True
    session.flush()
    return {"key": key, "character_id": character_id or None, "model": model_id, "bound": bound}


def sheet_key(session: Any, character_id: str) -> str | None:
    """The newest ``sheet`` reference bound to a character, or None."""
    from app.domains.characters.references_service import list_references

    sheets = [r for r in list_references(session, character_id) if r.get("role") == SHEET_ROLE and r.get("r2_key")]
    return str(sheets[-1]["r2_key"]) if sheets else None


# --------------------------------------------------------------------------- #
# HTTP: price first, refund once on failure
# --------------------------------------------------------------------------- #
class TurnaroundRequest(BaseModel):
    style: str = Field("", max_length=MAX_STYLE)


def _http(exc: SheetError, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}",
                         data={"code": exc.code})


def _character(session: Any, user_id: str, character_id: str) -> dict[str, Any]:
    from app.domains.characters import hub

    try:
        return hub.character_for_user(session, user_id, character_id)
    except hub.HubError as exc:
        raise SheetError(exc.status_code, exc.code, exc.message) from exc


def _debit(session: Any, user_id: str, character_id: str, credits: int) -> str:
    from app.models.db.repositories import CreditRepository, JobRepository

    job = JobRepository(session).create(user_id=user_id, kind=JOB_KIND, params={"character_id": character_id,
                                                                                "credits_cost": credits})
    if credits:
        try:
            CreditRepository(session).debit(user_id, credits, job.id, DEBIT_REASON)
        except ValueError as exc:
            raise SheetError(402, "credits_required", "not enough credits for a turnaround sheet") from exc
    session.flush()
    return job.id


def _settle(job_id: str, *, key: str = "", error: str = "") -> int:
    """Mark the ledger job done, or failed with its debit given back once. Returns credits refunded."""
    from app.controllers.v1.jobs import get_session
    from app.domains.reels.refunds import refund_latest_debit_once_in_session
    from app.models.db.models import Job

    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return 0
        if not error:
            job.state, job.progress, job.result_key = TASK_STATE_COMPLETE, 100, key
            session.flush()
            return 0
        job.state = TASK_STATE_FAILED
        job.params = {**dict(job.params or {}), "_error": error[:300]}
        refunded = int(refund_latest_debit_once_in_session(session, job_id, REFUND_REASON) or 0)
        session.flush()
        return refunded


def make_turnaround(request: Request, character_id: str, body: TurnaroundRequest, *,
                    image_fn: Callable[..., bytes] | None = None,
                    upload_fn: Callable[[str, bytes, str], None] | None = None,
                    presign_fn: Callable[[str], str] | None = None) -> dict[str, Any]:
    from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
    from app.domains.gallery.service import media_url
    from app.services.ratelimit import enforce_rate_limit

    request_id = base.get_task_id(request)
    _require_db(request_id)
    credits = sheet_credits()
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        user_id = str(user.id)
        enforce_rate_limit(request, f"character-sheet:{user_id}", limit=RATE_LIMIT, window_s=RATE_WINDOW_S)
        try:
            character = _character(session, user_id, character_id)
            job_id = _debit(session, user_id, character_id, credits)
        except SheetError as exc:
            raise _http(exc, request_id) from exc
    try:
        with get_session() as session:
            sheet = generate_sheet(
                session, user_id=user_id, descriptors=character.get("descriptors") or [character.get("name") or ""],
                style=_flat(body.style, MAX_STYLE) or str(character.get("style") or ""),
                character_id=character_id, reference_keys=character.get("reference_images") or (),
                image_fn=image_fn, upload_fn=upload_fn, presign_fn=presign_fn)
    except Exception as exc:  # noqa: BLE001 - a paid sheet that fails is refunded once
        logger.error(f"character sheet {job_id} failed: {exc}")
        refunded = _settle(job_id, error=str(exc) or type(exc).__name__)
        status, code, message = 502, "sheet_failed", "the sheet could not be made; your credits are back"
        if isinstance(exc, SheetError):
            status, code, message = exc.status_code, exc.code, f"{exc}; your credits are back"
        raise HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {message}",
                            data={"code": code, "refunded": refunded}) from exc
    _settle(job_id, key=sheet["key"])
    return {"key": sheet["key"], "image_url": media_url(sheet["key"]), "character_id": character_id,
            "credits": credits}


@router.post("/characters/{character_id}/turnaround",
             summary="Make a front, side and back turnaround sheet as the character's identity reference")
def post_turnaround(request: Request, body: TurnaroundRequest, character_id: str = Path(..., max_length=32)):
    return utils.get_response(200, make_turnaround(request, character_id, body))


__all__ = ["SheetError", "generate_sheet", "make_turnaround", "router", "sheet_key", "sheet_prompt"]
