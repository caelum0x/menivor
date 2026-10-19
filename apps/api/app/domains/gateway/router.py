"""Gateway (API-resale) HTTP surface (P11).

    POST /gateway/keys            mint a provisioning key (secret returned ONCE)
    GET  /gateway/keys            list the caller's keys (no secrets)
    POST /gateway/keys/{id}/quote preview markup + remaining daily allowance for a base cost

Auth + owner-scoping + DB reuse the shared jobs-controller helpers. Secrets are
write-once (only the SHA-256 hash is stored), so ``GET`` never returns them.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
    from app.domains.gateway import service as svc
    from app.domains.gateway.provisioning import MarkupPolicy, apply_markup
    from app.models.db.gateway import ProvisioningKey

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _IMPORT_ERROR = exc

router = new_router()


class KeyBody(BaseModel):
    label: str = Field(default="", max_length=120)
    daily_cap_micros: int = Field(default=0, ge=0)
    markup_bps: int = Field(default=0, ge=0)
    min_fee_micros: int = Field(default=0, ge=0)


class QuoteBody(BaseModel):
    base_cost_micros: int = Field(..., ge=0)


def _guard(request_id: str) -> None:
    if _IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: gateway layer unavailable: {_IMPORT_ERROR}")


def _key_view(row) -> dict:
    return {
        "id": row.id, "label": row.label, "daily_cap_micros": row.daily_cap_micros,
        "markup_bps": row.markup_bps, "min_fee_micros": row.min_fee_micros,
        "disabled": str(row.disabled) == "1",
    }


@router.post("/gateway/keys", summary="Mint a provisioning key (secret returned once)")
def create_key(request: Request, body: KeyBody):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        row, secret = svc.create_key(
            session, owner_id=user.id, daily_cap_micros=body.daily_cap_micros,
            label=body.label, markup_bps=body.markup_bps, min_fee_micros=body.min_fee_micros,
        )
        # The plaintext secret is shown exactly once, here.
        return utils.get_response(200, {**_key_view(row), "secret": secret})


@router.get("/gateway/keys", summary="List the caller's provisioning keys (no secrets)")
def list_keys(request: Request, limit: int = 100):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = (
            session.query(ProvisioningKey)
            .filter(ProvisioningKey.owner_id == user.id)
            .order_by(ProvisioningKey.created_at.desc())
            .limit(max(1, min(200, limit)))
            .all()
        )
        return utils.get_response(200, {"keys": [_key_view(r) for r in rows]})


@router.post("/gateway/keys/{key_id}/revoke", summary="Disable (revoke) a provisioning key")
def revoke_key(request: Request, key_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = svc.set_key_disabled(session, key_id=key_id, owner_id=user.id, disabled=True)
        except svc.GatewayServiceError as exc:
            raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: {exc}") from exc
        return utils.get_response(200, _key_view(row))


@router.post("/gateway/keys/{key_id}/quote", summary="Preview marked-up price + remaining daily allowance")
def quote(request: Request, body: QuoteBody, key_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        row = session.get(ProvisioningKey, key_id)
        if row is None or str(row.owner_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: key not found")
        now = datetime.now(timezone.utc)
        customer_price = apply_markup(
            body.base_cost_micros, MarkupPolicy(markup_bps=row.markup_bps, min_fee_micros=row.min_fee_micros)
        )
        spent = svc.spent_today(session, row.id, now=now)
        remaining = -1 if row.daily_cap_micros <= 0 else max(0, row.daily_cap_micros - spent)
        return utils.get_response(200, {
            "base_cost_micros": body.base_cost_micros,
            "customer_price_micros": customer_price,
            "spent_today_micros": spent,
            "remaining_micros": remaining,
            "would_allow": remaining < 0 or customer_price <= remaining,
        })
