"""Characters HTTP surface (P9) — save + list + reuse identity-locked characters.

    POST /characters            save a reusable character (dedupes by identity)
    GET  /characters            list the caller's characters
    GET  /characters/narrators  the original narrator roster (M2.3)
    GET  /characters/{id}       one owned character (rebuildable profile)
    POST /characters/{id}/shot-prompt   produce a locked shot prompt from it

Auth + owner-scoping + DB reuse the shared jobs-controller helpers. Import-safe.
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
    from app.domains.characters.consistency import CharacterProfile, build_shot_prompt
    from app.domains.characters.references_service import (
        ReferenceBindingError,
        bind_reference,
        list_references,
    )
    from app.domains.characters.repository import CharacterRepository, to_profile
    from app.domains.media.service import MediaDomainError

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _IMPORT_ERROR = exc

# ``Job.kind`` discriminator for a character LoRA training generation.
_CHARACTER_LORA_KIND: str = "character_lora"
# Minimum owned references a training run needs to lock an identity.
_MIN_TRAIN_REFERENCES: int = 1
_DEFAULT_LORA_TRAIN_COST: int = 40
_DEFAULT_LORA_TRAIN_STEPS: int = 1000
_DEFAULT_LORA_RANK: int = 16
_LORA_BASE_MODEL: str = "wan-2.2"

router = new_router()


class CharacterBody(BaseModel):
    name: str = Field(..., max_length=120)
    descriptors: list[str] = Field(default_factory=list)
    reference_images: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)
    style: str = Field(default="", max_length=200)
    lora_ref: str = Field(default="", max_length=200)


class ShotPromptBody(BaseModel):
    action: str = Field(..., max_length=1000)
    shot_index: int = Field(default=0, ge=0)
    scene: str = Field(default="", max_length=300)


class ReferenceBody(BaseModel):
    r2_key: str = Field(..., max_length=512)
    role: str = Field(default="sheet", max_length=16)
    content_type: str = Field(default="", max_length=80)
    width: int = Field(default=0, ge=0)
    height: int = Field(default=0, ge=0)


class TrainBody(BaseModel):
    steps: int = Field(default=_DEFAULT_LORA_TRAIN_STEPS, ge=1, le=10000)
    rank: int = Field(default=_DEFAULT_LORA_RANK, ge=1, le=256)
    workspace_id: str = Field(default="", max_length=64)


def _guard(request_id: str) -> None:
    if _IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: characters layer unavailable: {_IMPORT_ERROR}")


def _view(row) -> dict:
    return {
        "id": row.id, "name": row.name, "descriptors": list(row.descriptors or []),
        "reference_images": list(row.reference_images or []), "style": row.style,
        "lora_ref": row.lora_ref, "identity_key": row.identity_key,
    }


def _profile_from_body(body: CharacterBody) -> "CharacterProfile":
    return CharacterProfile(
        character_id="", name=body.name, descriptors=tuple(body.descriptors),
        reference_images=tuple(body.reference_images), style=body.style,
        lora_ref=body.lora_ref, negative=tuple(body.negative),
    )


@router.post("/characters", summary="Save a reusable identity-locked character")
def create_character(request: Request, body: CharacterBody):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = CharacterRepository(session)
        profile = _profile_from_body(body)
        existing = repo.find_duplicate(user.id, profile)
        if existing is not None:
            return utils.get_response(200, {**_view(existing), "deduped": True})
        row = repo.create(user_id=user.id, profile=profile)
        return utils.get_response(200, _view(row))


@router.get("/characters", summary="List the caller's characters")
def list_characters(request: Request, limit: int = 100):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = CharacterRepository(session).list_for_user(user.id, limit=max(1, min(200, limit)))
        return utils.get_response(200, {"characters": [_view(r) for r in rows]})


@router.get("/characters/narrators", summary="List Menivor's original narrator characters")
def list_original_narrators(request: Request):
    """The fixed roster of original narrators (M2.3), with each look's lock hash.

    ``available`` is false until the owner approves the art (O9); the story
    style keeps its still narrator until then.
    """
    request_id = base.get_task_id(request)
    try:
        from app.domains.characters.narrators import list_narrators, load_lock
        from app.services.styles.narrator_rig import rig_enabled
    except Exception as exc:  # pragma: no cover - import-safe surface
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: narrators unavailable: {exc}")
    lock = load_lock()
    return utils.get_response(200, {
        "available": rig_enabled(),
        "narrators": [
            {**n.public_view(), "sheet_sha256": lock.get(n.id, "")} for n in list_narrators()
        ],
    })


@router.get("/characters/{character_id}", summary="Get one owned character")
def get_character(request: Request, character_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        row = CharacterRepository(session).get_owned(character_id, user.id)
        if row is None:
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: character not found")
        return utils.get_response(200, _view(row))


@router.delete("/characters/{character_id}", summary="Delete an owned character")
def delete_character(request: Request, character_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if not CharacterRepository(session).delete_owned(character_id, user.id):
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: character not found")
        return utils.get_response(200, {"deleted": True, "id": character_id})


@router.post("/characters/{character_id}/shot-prompt", summary="Locked shot prompt from a character")
def shot_prompt(request: Request, body: ShotPromptBody, character_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        row = CharacterRepository(session).get_owned(character_id, user.id)
        if row is None:
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: character not found")
        sp = build_shot_prompt(to_profile(row), body.action, shot_index=body.shot_index, scene=body.scene)
        return utils.get_response(200, {
            "prompt": sp.prompt, "negative_prompt": sp.negative_prompt,
            "seed": sp.seed, "reference_images": list(sp.reference_images), "lora_ref": sp.lora_ref,
        })


def _require_owned_character(session, character_id: str, user_id: str, request_id: str):
    row = CharacterRepository(session).get_owned(character_id, user_id)
    if row is None:
        raise HttpException(task_id=request_id, status_code=404,
                            message=f"{request_id}: character not found")
    return row


@router.post("/characters/{character_id}/references", summary="Bind an owned uploads/ image as a reference")
def add_reference(request: Request, body: ReferenceBody, character_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _require_owned_character(session, character_id, user.id, request_id)
        try:
            view = bind_reference(
                session, user_id=user.id, character_id=character_id,
                r2_key=body.r2_key, role=body.role, content_type=body.content_type,
                width=body.width, height=body.height,
            )
        except ReferenceBindingError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc.message}") from exc
        except MediaDomainError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc.message}") from exc
        return utils.get_response(200, view)


@router.get("/characters/{character_id}/references", summary="List a character's reference images")
def get_references(request: Request, character_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _require_owned_character(session, character_id, user.id, request_id)
        refs = list_references(session, character_id)
        return utils.get_response(200, {"references": list(refs)})


@router.post("/characters/{character_id}/train", summary="Train a character LoRA (async generation)")
def train_character(request: Request, body: TrainBody, character_id: str = Path(...)):
    """Start one async character-LoRA training job; returns the job id to poll.

    Order: auth -> verify >=N owned bound references -> atomic credit debit
    committed BEFORE enqueue -> Job(kind='character_lora') -> enqueue -> return the
    job id. The debit is committed before enqueue so training can never run for
    free; an enqueue failure refunds it. Poll via the existing GET /jobs/{id}.
    """
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)

    from app.models.db.repositories import CreditRepository, JobRepository

    cost = _DEFAULT_LORA_TRAIN_COST
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _require_owned_character(session, character_id, user.id, request_id)
        refs = list_references(session, character_id)
        reference_keys = sorted({r["r2_key"] for r in refs if r["r2_key"]})
        if len(reference_keys) < _MIN_TRAIN_REFERENCES:
            raise HttpException(
                task_id=request_id, status_code=400,
                message=f"{request_id}: at least {_MIN_TRAIN_REFERENCES} bound "
                        f"reference image(s) are required to train",
            )
        workspace_id = (body.workspace_id or "").strip() or None
        params = {
            "_correlation_id": request_id,
            "character_id": character_id,
            "reference_keys": reference_keys,
            "steps": int(body.steps),
            "rank": int(body.rank),
            "base_model": _LORA_BASE_MODEL,
            "credits_cost": cost,
            "workspace_id": workspace_id,
        }
        job = JobRepository(session).create(
            user_id=user.id, kind=_CHARACTER_LORA_KIND, params=params
        )
        try:
            CreditRepository(session).debit(
                user.id, cost, job.id, "character_lora_debit"
            )
        except ValueError as exc:
            raise HttpException(task_id=request_id, status_code=402,
                                message=f"{request_id}: insufficient credits: {exc}")
        job_id = job.id

    # Debit committed — safe to enqueue. An enqueue failure refunds + fails.
    try:
        from app.workers.tasks import train_character_lora_task

        async_result = train_character_lora_task.apply_async(
            args=[{"job_id": job_id, "request_id": request_id}],
            headers={"correlation_id": request_id},
        )
        with get_session() as session:
            JobRepository(session).set_celery_task_id(job_id, async_result.id)
    except Exception as exc:  # noqa: BLE001 - enqueue failure must not orphan a paid job
        _reconcile_failed_training(job_id, request_id)
        raise HttpException(task_id=request_id, status_code=502,
                            message=f"{request_id}: failed to enqueue training") from exc

    return utils.get_response(200, {"job_id": job_id, "state": "processing",
                                    "character_id": character_id})


def _reconcile_failed_training(job_id: str, request_id: str) -> None:
    """Mark a training job failed and refund its debit after an enqueue failure."""
    try:
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            JobRepository(session).mark_failed(job_id, "enqueue", "failed to enqueue")
    except Exception:  # noqa: BLE001 - best-effort
        pass
    try:
        from app.domains.characters.training_service import (
            refund_character_lora_training,
        )

        refund_character_lora_training(job_id)
    except Exception:  # noqa: BLE001 - best-effort refund
        pass
