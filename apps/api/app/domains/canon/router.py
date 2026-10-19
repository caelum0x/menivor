"""Canon HTTP surface — lock brand/character values, retain versions, verify.

    POST /canon                     create a canon + lock v1
    POST /canon/{id}/lock           edit values => new immutable version (old kept)
    GET  /canon                     list the caller's canons
    GET  /canon/{id}                header + current version + version list
    GET  /canon/{id}/versions/{n}   one immutable locked snapshot
    POST /canon/{id}/verify         {asset_id} => provenance/integrity check

Auth + owner-scoping + DB reuse the shared jobs-controller helpers. Import-safe:
``_guard`` returns 503 if the domain layer fails to import.
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
    from app.domains.canon import service
    from app.domains.canon.repository import CanonRepository

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _IMPORT_ERROR = exc

router = new_router()


class CanonCreateBody(BaseModel):
    name: str = Field(..., max_length=120)
    character_id: str = Field(default="", max_length=32)
    style: str = Field(default="", max_length=200)
    palette: list[str] = Field(default_factory=list)
    typography: list[str] = Field(default_factory=list)
    voice_id: str = Field(default="", max_length=120)
    voice_tone: str = Field(default="", max_length=120)
    language: str = Field(default="", max_length=32)
    product_name: str = Field(default="", max_length=200)
    product_descriptors: list[str] = Field(default_factory=list)
    product_claims: list[str] = Field(default_factory=list)
    brand_tone: list[str] = Field(default_factory=list)
    brand_avoid: list[str] = Field(default_factory=list)


class CanonLockBody(BaseModel):
    """Same value surface as create, minus the header ``name``/binding."""

    style: str = Field(default="", max_length=200)
    palette: list[str] = Field(default_factory=list)
    typography: list[str] = Field(default_factory=list)
    voice_id: str = Field(default="", max_length=120)
    voice_tone: str = Field(default="", max_length=120)
    language: str = Field(default="", max_length=32)
    product_name: str = Field(default="", max_length=200)
    product_descriptors: list[str] = Field(default_factory=list)
    product_claims: list[str] = Field(default_factory=list)
    brand_tone: list[str] = Field(default_factory=list)
    brand_avoid: list[str] = Field(default_factory=list)


class VerifyBody(BaseModel):
    asset_id: str = Field(..., max_length=32)


def _guard(request_id: str) -> None:
    if _IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: canon layer unavailable: {_IMPORT_ERROR}")


def _values_kwargs(body: BaseModel) -> dict:
    """Value fields shared by create/lock, minus header-only fields."""
    data = body.model_dump()
    data.pop("name", None)
    character_id = (data.pop("character_id", "") or "").strip() or None
    return {"character_id": character_id, **data}


def _header_view(canon, versions) -> dict:
    return {
        "canon_id": canon.id,
        "name": canon.name,
        "character_id": canon.character_id,
        "current_canon_hash": canon.current_canon_hash,
        "current_version": canon.current_version,
        "versions": [
            {"version": v.version, "canon_hash": v.canon_hash, "locked_at": str(v.locked_at)}
            for v in versions
        ],
    }


def _version_view(v) -> dict:
    return {
        "version": v.version,
        "canon_hash": v.canon_hash,
        "values": dict(v.values or {}),
        "character_identity_key": v.character_identity_key,
        "locked_at": str(v.locked_at),
    }


def _require_owned(session, canon_id: str, user_id: str, request_id: str):
    canon = CanonRepository(session).get_owned(canon_id, user_id)
    if canon is None:
        raise HttpException(task_id=request_id, status_code=404,
                            message=f"{request_id}: canon not found")
    return canon


@router.post("/canon", summary="Create a canon and lock version 1")
def create_canon(request: Request, body: CanonCreateBody):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        kwargs = _values_kwargs(body)
        values = service.build_values(session, **kwargs)
        canon = CanonRepository(session).create_canon(
            user_id=user.id, name=body.name, values=values,
            character_id=kwargs["character_id"],
        )
        return utils.get_response(200, {
            "canon_id": canon.id, "canon_hash": canon.current_canon_hash,
            "version": canon.current_version,
        })


@router.post("/canon/{canon_id}/lock", summary="Lock a new immutable canon version")
def lock_canon(request: Request, body: CanonLockBody, canon_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        canon = _require_owned(session, canon_id, user.id, request_id)
        kwargs = _values_kwargs(body)
        # A lock inherits the header's bound character unless the body overrides.
        if kwargs["character_id"] is None:
            kwargs["character_id"] = canon.character_id
        values = service.build_values(session, **kwargs)
        version = CanonRepository(session).lock_new_version(canon_id, values)
        return utils.get_response(200, {
            "canon_id": canon_id, "canon_hash": version.canon_hash,
            "version": version.version,
        })


@router.get("/canon", summary="List the caller's canons")
def list_canons(request: Request, limit: int = 100):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = CanonRepository(session).list_for_user(user.id, limit=max(1, min(200, limit)))
        return utils.get_response(200, {"canons": [
            {"canon_id": r.id, "name": r.name, "current_canon_hash": r.current_canon_hash,
             "current_version": r.current_version} for r in rows
        ]})


@router.get("/canon/{canon_id}", summary="Get a canon header + versions")
def get_canon(request: Request, canon_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        canon = _require_owned(session, canon_id, user.id, request_id)
        versions = CanonRepository(session).list_versions(canon_id)
        return utils.get_response(200, _header_view(canon, versions))


@router.get("/canon/{canon_id}/versions/{version}", summary="Get one immutable locked snapshot")
def get_canon_version(request: Request, canon_id: str = Path(...), version: int = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _require_owned(session, canon_id, user.id, request_id)
        v = CanonRepository(session).get_version(canon_id, version)
        if v is None:
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: canon version not found")
        return utils.get_response(200, _version_view(v))


@router.post("/canon/{canon_id}/verify", summary="Verify an asset's canon provenance")
def verify_canon_asset(request: Request, body: VerifyBody, canon_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _require_owned(session, canon_id, user.id, request_id)
        result = service.verify_asset(session, body.asset_id, canon_id)
        return utils.get_response(200, {"verified": result.verified, "reason": result.reason})
