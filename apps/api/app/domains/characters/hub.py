"""My characters and brands (MH4): one facade over the existing character code.

Create once, reuse in every preset:

* **Original character**: picked from Menivor's own narrator roster
  (``narrators.py``); nothing to verify, nothing to train.
* **Your own face**: 10-20 of your own uploads, a one-off consent phrase you
  read aloud (checked by speech recognition, ``voice_verification``) and a
  locked Identity Lock passport. It fails closed when Identity Lock is not
  configured. There is no third-party face path and no face swap anywhere;
  no face-recognition library is used (the identity score below is an
  appearance similarity, not biometrics).
* **LoRA training** runs only on AI-video credits, quoted before it starts;
  a failed run is refunded once from the ledger (``refund_failed_trainings``).
* **Identity score**: each render of a character (preset x model) records a
  CPU appearance similarity between the character's first reference and the
  render's poster frame.
* **Brand kit**: the existing ``UserPreset`` brand kit (logo, colours, voice,
  captions, music) plus product shots; every preset accepts it
  (``presets_hub.service.resolve(..., brand=...)``).

The existing files (consistency, training_service, references_service,
repository, narrators, router) are used as they are.
"""

from __future__ import annotations

import io
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from fastapi import Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Float, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.db.base import Base
from app.models.exception import HttpException
from app.utils import utils

router = new_router()

KIND_ORIGINAL = "original"
KIND_REAL_FACE = "real_face"
MIN_PHOTOS = 10
MAX_PHOTOS = 20
MAX_PRODUCT_SHOTS = 12
SCORE_METHOD = "appearance-v1"
LORA_USD_ENV = "CHARACTER_LORA_PROVIDER_USD"
DEFAULT_LORA_USD = 1.0
LORA_KIND = "character_lora"
TASK_STATE_COMPLETE = 1
TASK_STATE_FAILED = -1
_LORA_STEPS = 1000
_LORA_RANK = 16
_LORA_BASE = "wan-2.2"


# --------------------------------------------------------------------------- #
# Tables (migration f3b5d7e9a1c2)
# --------------------------------------------------------------------------- #
class CharacterHubProfile(Base):
    """What kind of character this is and, for a real face, its consent record."""

    __tablename__ = "character_hub_profiles"

    character_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    narrator_id: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    consent_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_words_heard: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consent_words_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passport_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    passport_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CharacterIdentityScore(Base):
    """One render of a character: how close it looks to the character's reference."""

    __tablename__ = "character_identity_scores"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: os.urandom(16).hex())
    character_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    job_id: Mapped[str] = mapped_column(String(32), nullable=False)
    preset_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    score: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False, default=SCORE_METHOD)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HubError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# Seams to the rest of the product (replaced in tests)
# --------------------------------------------------------------------------- #
def require_owned(session: Session, user_id: str, key: str) -> bool:
    """Whether ``key`` is one of the caller's own uploads."""
    from app.domains.media.service import MediaDomainError, require_owned_asset

    if not str(key or "").startswith("uploads/"):
        return False
    try:
        require_owned_asset(session, user_id=user_id, key=key)
        return True
    except MediaDomainError:
        return False


def locked_passports(session: Session, user_id: str) -> list[dict]:
    """The caller's locked Identity Lock passports ([] when not configured)."""
    from app.domains.gateway.media_gateway import list_identity_options

    try:
        return list(list_identity_options(session, user_id=user_id))
    except Exception:  # noqa: BLE001 - fail closed: no passport means no real-face character
        return []


def _download(key: str) -> str:
    from app.platform.storage.r2 import get_r2_client

    fd, path = tempfile.mkstemp(prefix="hub-", suffix=os.path.splitext(key)[1] or ".bin")
    os.close(fd)
    get_r2_client().download_file(key, path)
    return path


def transcribe_key(key: str) -> str:
    """Speech recognition over the caller's consent recording."""
    from app.domains.compliance.voice_verification import _transcribe

    path = _download(key)
    try:
        return _transcribe(path)
    finally:
        os.remove(path)


def fetch_bytes(key: str) -> bytes:
    path = _download(key)
    try:
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        os.remove(path)


def enqueue_training(job_id: str, request_id: str) -> str:
    from app.workers.tasks import train_character_lora_task

    result = train_character_lora_task.apply_async(args=[{"job_id": job_id, "request_id": request_id}],
                                                   headers={"correlation_id": request_id})
    return str(result.id)


# --------------------------------------------------------------------------- #
# Characters
# --------------------------------------------------------------------------- #
def _profile_row(session: Session, character_id: str) -> CharacterHubProfile | None:
    return session.get(CharacterHubProfile, character_id)


def _owned_character(session: Session, user_id: str, character_id: str):
    from app.domains.characters.repository import CharacterRepository

    row = CharacterRepository(session).get_owned(character_id, user_id)
    if row is None:
        raise HubError(404, "not_found", "character not found")
    return row


def character_view(row: Any, meta: CharacterHubProfile | None) -> dict[str, Any]:
    kind = meta.kind if meta else "described"
    view: dict[str, Any] = {
        "id": row.id,
        "name": row.name,
        "kind": kind,
        "reference_count": len(row.reference_images or []),
        "trained": bool(row.lora_ref),
    }
    if meta and meta.kind == KIND_REAL_FACE:
        view["consent"] = {"verified": meta.consent_verified_at is not None,
                           "words_heard": meta.consent_words_heard, "words_total": meta.consent_words_total}
        view["identity_lock"] = {"passport_id": meta.passport_id, "version": meta.passport_version}
    if meta and meta.narrator_id:
        view["narrator_id"] = meta.narrator_id
    return view


def list_characters(session: Session, user_id: str) -> list[dict[str, Any]]:
    from app.domains.characters.repository import CharacterRepository

    rows = CharacterRepository(session).list_for_user(user_id)
    return [character_view(row, _profile_row(session, row.id)) for row in rows]


def create_original(session: Session, user_id: str, narrator_id: str) -> dict[str, Any]:
    from app.domains.characters.consistency import CharacterProfile
    from app.domains.characters.narrators import get_narrator
    from app.domains.characters.repository import CharacterRepository

    narrator = get_narrator(narrator_id)
    if narrator is None:
        raise HubError(404, "not_found", "that original character does not exist")
    look = narrator.look
    descriptors = tuple(str(v) for v in (getattr(look, "__dict__", {}) or {}).values() if isinstance(v, str))[:8]
    profile = CharacterProfile(character_id="", name=narrator.name, descriptors=descriptors,
                               style="original Menivor narrator, flat cartoon")
    repo = CharacterRepository(session)
    row = repo.find_duplicate(user_id, profile) or repo.create(user_id=user_id, profile=profile)
    meta = _profile_row(session, row.id) or CharacterHubProfile(character_id=row.id, user_id=user_id,
                                                                kind=KIND_ORIGINAL, narrator_id=narrator.id)
    session.add(meta)
    session.flush()
    return character_view(row, meta)


def consent_challenge(user_id: str) -> dict[str, Any]:
    from app.domains.compliance.voice_verification import issue_phrase

    challenge = issue_phrase(user_id)
    return {"token": challenge.token, "phrase": challenge.phrase, "expires_at": challenge.expires_at}


def create_real_face(session: Session, user_id: str, body: "RealFaceRequest") -> dict[str, Any]:
    from app.domains.characters.consistency import CharacterProfile
    from app.domains.characters.repository import CharacterRepository
    from app.domains.compliance import voice_verification as vv
    from app.models.db.character_refs import CharacterReference

    if not body.self_declared:
        raise HubError(400, "self_declaration", "confirm these photos are of you")
    keys = list(dict.fromkeys(k.strip() for k in body.reference_keys if k.strip()))
    if not MIN_PHOTOS <= len(keys) <= MAX_PHOTOS:
        raise HubError(400, "photo_count", f"add {MIN_PHOTOS} to {MAX_PHOTOS} photos of yourself")
    if not all(require_owned(session, user_id, key) for key in [*keys, body.recording_key]):
        raise HubError(403, "not_your_upload", "use only photos and recordings you uploaded")
    try:
        phrase = vv.phrase_from_token(user_id, body.consent_token)
    except vv.VoiceVerificationError as exc:
        raise HubError(400, "consent_phrase", str(exc)) from exc
    heard, total = vv.phrase_matches(phrase, transcribe_key(body.recording_key))
    if heard < vv.PHRASE_MIN_MATCH:
        raise HubError(400, "consent_phrase", "we could not hear the consent phrase; record it again")
    passports = {(str(p.get("passport_id")), int(p.get("version") or 0)) for p in locked_passports(session, user_id)}
    if (body.passport_id, body.passport_version) not in passports:
        raise HubError(409, "identity_lock", "lock your identity first, then pick that passport")
    profile = CharacterProfile(character_id="", name=body.name.strip()[:120] or "Me", reference_images=tuple(keys))
    row = CharacterRepository(session).create(user_id=user_id, profile=profile)
    for key in keys:
        session.add(CharacterReference(character_id=row.id, user_id=user_id, r2_key=key, role="sheet"))
    meta = CharacterHubProfile(character_id=row.id, user_id=user_id, kind=KIND_REAL_FACE,
                               consent_verified_at=datetime.now(timezone.utc), consent_words_heard=heard,
                               consent_words_total=total, passport_id=body.passport_id,
                               passport_version=body.passport_version)
    session.add(meta)
    session.flush()
    return character_view(row, meta)


def character_for_user(session: Session, user_id: str, character_id: str) -> dict[str, Any]:
    """The character as a preset input (ownership checked)."""
    row = _owned_character(session, user_id, character_id)
    meta = _profile_row(session, row.id)
    if meta and meta.kind == KIND_REAL_FACE and meta.consent_verified_at is None:
        raise HubError(409, "consent_required", "this character has no verified consent")
    return {"id": row.id, "name": row.name, "descriptors": list(row.descriptors or []), "style": row.style,
            "reference_images": list(row.reference_images or []), "lora_ref": row.lora_ref,
            "negative": list(row.negative or []), "kind": meta.kind if meta else "described"}


# --------------------------------------------------------------------------- #
# LoRA training on AI-video credits
# --------------------------------------------------------------------------- #
def lora_provider_usd() -> float:
    try:
        return max(0.01, float(os.environ.get(LORA_USD_ENV) or DEFAULT_LORA_USD))
    except ValueError:
        return DEFAULT_LORA_USD


def training_quote(session: Session, user_id: str, character_id: str) -> dict[str, Any]:
    from app.services.billing.premium_credits import ai_video_credits_for_usd

    row = _owned_character(session, user_id, character_id)
    meta = _profile_row(session, row.id)
    if meta is None or meta.kind != KIND_REAL_FACE:
        raise HubError(400, "training_not_needed", "original characters are ready to use; no training needed")
    if meta.consent_verified_at is None:
        raise HubError(409, "consent_required", "verify consent before training")
    return {"character_id": row.id, "credit_kind": "ai_video",
            "credits": ai_video_credits_for_usd(lora_provider_usd()), "references": len(row.reference_images or [])}


def _refund_held(session: Session, job_id: str) -> int:
    from app.services.billing import premium_credits as pc

    user_id, held = pc.job_net_debit(session, job_id, pc.KIND_AI_VIDEO)
    if user_id is None or held <= 0:
        return 0
    # Re-read under the user lock so two concurrent sweeps cannot both refund.
    pc._lock_user(session, user_id)
    user_id, held = pc.job_net_debit(session, job_id, pc.KIND_AI_VIDEO)
    if user_id is None or held <= 0:
        return 0
    pc.grant(session, user_id, pc.KIND_AI_VIDEO, held, f"{pc.REFUND_REASON}:{job_id}", job_id)
    return held


def _training_in_flight(session: Session, user_id: str, character_id: str) -> bool:
    """Whether a hub training of this character is still queued or running."""
    from app.models.db.models import Job

    jobs = session.execute(
        select(Job).where(Job.user_id == user_id, Job.kind == LORA_KIND,
                          Job.state.not_in((TASK_STATE_COMPLETE, TASK_STATE_FAILED)))
    ).scalars().all()
    return any(dict(job.params or {}).get("character_id") == character_id
               and dict(job.params or {}).get("hub_funding") == "ai_video" for job in jobs)


def start_training(session: Session, user_id: str, character_id: str, quoted_credits: int,
                   request_id: str) -> str:
    from app.models.db.repositories import JobRepository
    from app.services.billing import premium_credits as pc

    quote = training_quote(session, user_id, character_id)
    if int(quoted_credits) != quote["credits"]:
        raise HubError(409, "quote_changed", "the price changed; check the new price first")
    row = _owned_character(session, user_id, character_id)
    # One training at a time per character: a double tap must not charge twice.
    pc._lock_user(session, user_id)
    if _training_in_flight(session, user_id, row.id):
        raise HubError(409, "training_in_progress", "this character is already training")
    params = {
        "_correlation_id": request_id, "character_id": row.id,
        "reference_keys": sorted(set(row.reference_images or [])), "steps": _LORA_STEPS, "rank": _LORA_RANK,
        "base_model": _LORA_BASE, "credits_cost": 0, "workspace_id": None,
        "hub_funding": "ai_video", "ai_video_credits": quote["credits"],
    }
    job = JobRepository(session).create(user_id=user_id, kind=LORA_KIND, params=params)
    try:
        pc.debit(session, user_id, pc.KIND_AI_VIDEO, quote["credits"], f"{pc.DEBIT_REASON}:{job.id}", job.id)
    except pc.InsufficientPremiumCredits as exc:
        raise HubError(402, "ai_video_credits_required", "not enough AI-video credits for training") from exc
    from app.integrations.railyard.meters import lora_train

    lora_train(session, job_id=job.id, customer=str(user_id), credits=quote["credits"])  # Wave P PM1.5
    session.flush()
    return job.id


def refund_failed_trainings(session: Session, *, limit: int = 200) -> int:
    """Return AI-video credits held by failed hub trainings, once per job."""
    from app.models.db.models import Job

    from app.models.db.premium_credit import PremiumCreditLedger
    from app.services.billing import premium_credits as pc

    # Only failed trainings that still hold AI-video credits, so old refunded or
    # legacy failures can never crowd a new one out of the batch.
    holding = (
        select(PremiumCreditLedger.job_id)
        .where(PremiumCreditLedger.kind == pc.KIND_AI_VIDEO, PremiumCreditLedger.job_id.is_not(None))
        .group_by(PremiumCreditLedger.job_id)
        .having(func.sum(PremiumCreditLedger.delta) < 0)
    )
    jobs = session.execute(
        select(Job).where(Job.kind == LORA_KIND, Job.state == TASK_STATE_FAILED, Job.id.in_(holding))
        .order_by(Job.id).limit(limit)
    ).scalars().all()
    refunded = 0
    for job in jobs:
        params = dict(job.params or {})
        if params.get("hub_funding") != "ai_video" or params.get("hub_refunded"):
            continue
        if _refund_held(session, job.id) > 0:
            refunded += 1
        job.params = {**params, "hub_refunded": True}
    session.flush()
    return refunded


# --------------------------------------------------------------------------- #
# Identity score (appearance similarity on CPU, not biometrics)
# --------------------------------------------------------------------------- #
def _square(image_bytes: bytes, size: int):
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    side = min(image.size)
    left, top = (image.width - side) // 2, (image.height - side) // 2
    return image.crop((left, top, left + side, top + side)).resize((size, size))


def appearance_score(reference: bytes, frame: bytes) -> float:
    """0..1: half colour-histogram intersection (HSV), half structural correlation."""
    import numpy as np

    ref, cur = _square(reference, 64), _square(frame, 64)

    def hist(image) -> Any:
        hsv = np.asarray(image.convert("HSV"), dtype=np.int32)
        h, s, v = hsv[..., 0] * 8 // 256, hsv[..., 1] * 4 // 256, hsv[..., 2] * 4 // 256
        counts = np.bincount((h * 16 + s * 4 + v).ravel(), minlength=128).astype(float)
        return counts / counts.sum()

    colour = float(np.minimum(hist(ref), hist(cur)).sum())
    a = np.asarray(ref.convert("L").resize((32, 32)), dtype=float).ravel()
    b = np.asarray(cur.convert("L").resize((32, 32)), dtype=float).ravel()
    a, b = a - a.mean(), b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    structure = 1.0 if denom == 0 and np.allclose(a, b) else (float(a @ b) / denom if denom else 0.0)
    return round(max(0.0, min(1.0, 0.5 * colour + 0.5 * (structure + 1.0) / 2.0)), 4)


def video_frame(video: bytes, at_s: float = 1.0) -> bytes:
    """One PNG frame from a rendered clip (FFmpeg, CPU)."""
    import subprocess

    with tempfile.TemporaryDirectory(prefix="hub-frame-") as tmp:
        src, dst = os.path.join(tmp, "in.mp4"), os.path.join(tmp, "frame.png")
        with open(src, "wb") as handle:
            handle.write(video)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at_s:.2f}", "-i", src, "-frames:v", "1", dst],
                       check=True, timeout=60)
        with open(dst, "rb") as handle:
            return handle.read()


def record_score(session: Session, user_id: str, character_id: str, *, job_id: str, preset_id: str,
                 model: str) -> dict[str, Any]:
    from app.models.db.models import Job

    row = _owned_character(session, user_id, character_id)
    refs = list(row.reference_images or [])
    if not refs:
        raise HubError(400, "no_reference", "this character has no reference image to compare with")
    job = session.get(Job, job_id)
    if job is None or str(job.user_id) != str(user_id):
        raise HubError(404, "not_found", "render not found")
    frame_key = job.poster_key or job.preview_key or job.result_key
    if job.state != TASK_STATE_COMPLETE or not frame_key:
        raise HubError(409, "not_finished", "score a finished render")
    frame = fetch_bytes(frame_key)
    if not (job.poster_key or job.preview_key) or frame_key.endswith((".mp4", ".mov", ".webm")):
        frame = video_frame(frame)
    score = appearance_score(fetch_bytes(refs[0]), frame)
    entry = CharacterIdentityScore(character_id=row.id, user_id=user_id, job_id=job.id,
                                   preset_id=preset_id[:80], model=model[:80], score=score)
    session.add(entry)
    session.flush()
    return {"job_id": job.id, "preset_id": entry.preset_id, "model": entry.model, "score": score,
            "method": SCORE_METHOD}


def list_scores(session: Session, user_id: str, character_id: str) -> dict[str, Any]:
    row = _owned_character(session, user_id, character_id)
    rows = session.execute(select(CharacterIdentityScore).where(CharacterIdentityScore.character_id == row.id)
                           .order_by(CharacterIdentityScore.created_at)).scalars().all()
    scores = [{"job_id": r.job_id, "preset_id": r.preset_id, "model": r.model, "score": r.score,
               "method": r.method} for r in rows]
    values = [r.score for r in rows]
    summary = {"count": len(rows), "presets": len({r.preset_id for r in rows}), "models": len({r.model for r in rows}),
               "min": min(values) if values else None,
               "mean": round(sum(values) / len(values), 4) if values else None}
    return {"character_id": row.id, "scores": scores, "summary": summary}


# --------------------------------------------------------------------------- #
# Brand kits
# --------------------------------------------------------------------------- #
def _brand_view(kit: Any) -> dict[str, Any]:
    config = dict(kit.config or {})
    brand = dict(config.get("brand") or {})
    colors = brand.get("colors") or brand.get("colours") or []
    return {
        "id": kit.id, "name": brand.get("name") or kit.name, "logo": brand.get("logo") or "",
        "colors": [str(c) for c in colors][:6], "fonts": list(brand.get("fonts") or [])[:4],
        "voice_name": config.get("voice_name") or "", "caption_style": config.get("caption_style") or "",
        "music_id": config.get("music_id") or "", "language": config.get("language") or "",
        "product_shots": list(brand.get("product_shots") or [])[:MAX_PRODUCT_SHOTS],
    }


def _owned_kit(session: Session, user_id: str, kit_id: str):
    from app.models.db.models import UserPreset

    kit = session.get(UserPreset, kit_id)
    if kit is None or str(kit.user_id) != str(user_id):
        raise HubError(404, "not_found", "brand kit not found")
    return kit


def list_brands(session: Session, user_id: str) -> list[dict[str, Any]]:
    from app.models.db.models import UserPreset

    kits = session.execute(select(UserPreset).where(UserPreset.user_id == user_id)
                           .order_by(UserPreset.created_at.desc())).scalars().all()
    return [_brand_view(kit) for kit in kits]


def brand_for_user(session: Session, user_id: str, kit_id: str) -> dict[str, Any]:
    return _brand_view(_owned_kit(session, user_id, kit_id))


def set_product_shots(session: Session, user_id: str, kit_id: str, keys: list[str]) -> dict[str, Any]:
    kit = _owned_kit(session, user_id, kit_id)
    clean = list(dict.fromkeys(k.strip() for k in keys if k.strip()))[:MAX_PRODUCT_SHOTS]
    if not all(require_owned(session, user_id, key) for key in clean):
        raise HubError(403, "not_your_upload", "use only product shots you uploaded")
    config = dict(kit.config or {})
    kit.config = {**config, "brand": {**dict(config.get("brand") or {}), "product_shots": clean}}
    session.flush()
    return _brand_view(kit)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
class OriginalRequest(BaseModel):
    narrator_id: str = Field(..., min_length=1, max_length=40)


class RealFaceRequest(BaseModel):
    name: str = Field("Me", max_length=120)
    reference_keys: list[str] = Field(..., max_length=40)
    consent_token: str = Field(..., min_length=10, max_length=200)
    recording_key: str = Field(..., min_length=1, max_length=512)
    passport_id: str = Field(..., min_length=1, max_length=80)
    passport_version: int = Field(..., ge=1)
    self_declared: bool = False


class TrainRequest(BaseModel):
    quoted_credits: int = Field(..., ge=1)


class ScoreRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=32)
    preset_id: str = Field("", max_length=80)
    model: str = Field("", max_length=80)


class ProductShotsRequest(BaseModel):
    keys: list[str] = Field(default_factory=list, max_length=MAX_PRODUCT_SHOTS)


def _http(exc: HubError, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc.message}",
                         data={"code": exc.code})


def _run(request: Request, fn) -> Any:
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            return fn(session, str(user.id), request_id)
        except HubError as exc:
            raise _http(exc, request_id) from exc


@router.get("/my/characters", summary="My characters")
def get_characters(request: Request):
    return utils.get_response(200, {"characters": _run(request, lambda s, u, r: list_characters(s, u))})


@router.post("/my/characters/original", summary="Add an original Menivor character")
def post_original(request: Request, body: OriginalRequest):
    return utils.get_response(200, _run(request, lambda s, u, r: create_original(s, u, body.narrator_id)))


@router.post("/my/characters/consent-phrase", summary="A one-off phrase to read aloud for consent")
def post_consent_phrase(request: Request):
    return utils.get_response(200, _run(request, lambda s, u, r: consent_challenge(u)))


@router.post("/my/characters/real-face", summary="Create a character of yourself (consent + Identity Lock)")
def post_real_face(request: Request, body: RealFaceRequest):
    return utils.get_response(200, _run(request, lambda s, u, r: create_real_face(s, u, body)))


@router.post("/my/characters/{character_id}/train/quote", summary="Price a LoRA training before it starts")
def post_train_quote(request: Request, character_id: str = Path(..., max_length=32)):
    return utils.get_response(200, _run(request, lambda s, u, r: training_quote(s, u, character_id)))


@router.post("/my/characters/{character_id}/train", summary="Train a LoRA on AI-video credits")
def post_train(request: Request, body: TrainRequest, character_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    job_id = _run(request, lambda s, u, r: start_training(s, u, character_id, body.quoted_credits, r))
    try:
        enqueue_training(job_id, request_id)
    except Exception as exc:  # noqa: BLE001 - a paid job must never be orphaned
        from app.models.db.models import Job

        with get_session() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.state = TASK_STATE_FAILED
                job.params = {**dict(job.params or {}), "hub_refunded": True}
            _refund_held(session, job_id)
        raise HttpException(task_id=request_id, status_code=502, message=f"{request_id}: training could not start",
                            data={"code": "enqueue_failed"}) from exc
    return utils.get_response(200, {"job_id": job_id, "character_id": character_id, "state": "processing"})


@router.post("/my/characters/{character_id}/identity-scores", summary="Record a render's identity score")
def post_score(request: Request, body: ScoreRequest, character_id: str = Path(..., max_length=32)):
    return utils.get_response(200, _run(request, lambda s, u, r: record_score(
        s, u, character_id, job_id=body.job_id, preset_id=body.preset_id, model=body.model)))


@router.get("/my/characters/{character_id}/identity-scores", summary="A character's identity scores")
def get_scores(request: Request, character_id: str = Path(..., max_length=32)):
    return utils.get_response(200, _run(request, lambda s, u, r: list_scores(s, u, character_id)))


@router.get("/my/brands", summary="My brand kits")
def get_brands(request: Request):
    return utils.get_response(200, {"brands": _run(request, lambda s, u, r: list_brands(s, u))})


@router.put("/my/brands/{kit_id}/product-shots", summary="Set a brand kit's product shots")
def put_product_shots(request: Request, body: ProductShotsRequest, kit_id: str = Path(..., max_length=32)):
    return utils.get_response(200, _run(request, lambda s, u, r: set_product_shots(s, u, kit_id, body.keys)))
