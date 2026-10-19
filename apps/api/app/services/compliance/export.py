"""GDPR data-export assembly + delivery (Art. 15 / 20 — Compliance, Epic 5).

:func:`assemble_export` builds a COMPLETE, STRICTLY requester-scoped snapshot of
a single user's data — profile, jobs, asset metadata, personal credit ledger,
their owned workspaces' subscriptions/invoices, consent trail and memberships —
reading ONLY rows keyed to that ``user_id`` (or to a workspace they own). No
path can ever include another user's rows: every select filters on the owner id.

:func:`build_export` serializes that package to JSON, writes it to a temp file,
uploads it to R2 under an OWNER-SCOPED key (``exports/<user_id>/...``) and
returns a SHORT-LIVED presigned GET URL — a private object handed back only
through that expiring link (never a permanent/public URL). The action is
recorded in the append-only audit trail.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db.models import (
    Asset,
    Job,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.db.repositories import (
    ConsentRepository,
    CreditRepository,
    InvoiceRepository,
    SubscriptionRepository,
)
from app.services import audit

#: Expiry (seconds) of the presigned GET handed back for an export archive. The
#: archive is sensitive (a user's entire data footprint) so the link is
#: deliberately short-lived — 15 minutes — rather than the 7-day result window.
EXPORT_URL_EXPIRES: int = 900

#: Owner-scoped R2 key prefix. Every archive lives under ``exports/<user_id>/``
#: so a key can never address another user's export.
_EXPORT_PREFIX: str = "exports"

#: Audit verb recorded on a successful export.
_ACTION_EXPORT: str = "compliance.data_exported"


class ExportStorage(Protocol):
    """The minimal R2 surface :func:`build_export` needs (injectable for tests)."""

    def upload_bytes(self, key: str, data: bytes, content_type: str) -> str: ...

    def presign_get(
        self, key: str, expires: int = ..., download_name: str | None = ...
    ) -> str: ...


def _dt(value: Any) -> str | None:
    """Serialize a datetime to ISO-8601, passing ``None`` through."""
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _user_dict(user: User) -> dict[str, Any]:
    """Serialize the requester's own profile row (no other user's data)."""
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "handle": user.handle,
        "bio": user.bio,
        "credits": user.credits,
        "referral_code": user.referral_code,
        "referred_by": user.referred_by,
        "is_staff": user.is_staff,
        "created_at": _dt(user.created_at),
    }


def _job_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "state": job.state,
        "progress": job.progress,
        "stages": job.stages,
        "params": job.params,
        "script": job.script,
        "result_key": job.result_key,
        "error": job.error,
        "created_at": _dt(job.created_at),
        "updated_at": _dt(job.updated_at),
    }


def _asset_dict(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "job_id": asset.job_id,
        "kind": asset.kind,
        "r2_key": asset.r2_key,
        "content_type": asset.content_type,
        "size_bytes": asset.size_bytes,
        "duration_s": asset.duration_s,
        "meta": asset.meta,
        "created_at": _dt(asset.created_at),
    }


def assemble_export(session: Session, user_id: str) -> dict[str, Any]:
    """Assemble a COMPLETE, requester-scoped data package for ``user_id``.

    Returns a JSON-serializable ``dict`` containing ONLY rows owned by
    ``user_id`` (or by a workspace they own): profile, jobs, asset metadata,
    personal credit ledger, consent trail, workspace memberships, and — for the
    workspaces this user OWNS — subscriptions and invoices. Every select is
    filtered on the owner id, so another user's rows can never appear.

    Raises:
        ValueError: when ``user_id`` is blank or no such user exists.
    """
    normalized = (user_id or "").strip()
    if not normalized:
        raise ValueError("user_id must be a non-empty string")

    user = session.get(User, normalized)
    if user is None:
        raise ValueError(f"user not found: {normalized}")

    # Jobs + assets — strictly owner-scoped selects.
    jobs = list(
        session.execute(
            select(Job)
            .where(Job.user_id == normalized)
            .order_by(Job.created_at.asc(), Job.id.asc())
        ).scalars().all()
    )
    assets = list(
        session.execute(
            select(Asset)
            .where(Asset.user_id == normalized)
            .order_by(Asset.created_at.asc(), Asset.id.asc())
        ).scalars().all()
    )

    # Personal credit ledger (workspace-pool rows are excluded by the repo).
    ledger = CreditRepository(session).list_for_user(normalized)

    # Memberships — the workspaces this user belongs to and their role.
    memberships = list(
        session.execute(
            select(WorkspaceMember)
            .where(WorkspaceMember.user_id == normalized)
            .order_by(WorkspaceMember.created_at.asc())
        ).scalars().all()
    )

    # Financial records for the workspaces this user OWNS (owner_id == user_id).
    # A member who is not the owner never receives a workspace's financials here,
    # keeping the export strictly to the requester's own data.
    owned_workspaces = list(
        session.execute(
            select(Workspace).where(Workspace.owner_id == normalized)
        ).scalars().all()
    )
    sub_repo = SubscriptionRepository(session)
    inv_repo = InvoiceRepository(session)
    subscriptions: list[dict[str, Any]] = []
    invoices: list[dict[str, Any]] = []
    for ws in owned_workspaces:
        sub = sub_repo.get_for_workspace(ws.id)
        if sub is not None:
            subscriptions.append(
                {
                    "id": sub.id,
                    "workspace_id": sub.workspace_id,
                    "plan_key": sub.plan_key,
                    "status": sub.status,
                    "interval": sub.interval,
                    "seats": sub.seats,
                    "provider": sub.provider,
                    "current_period_end": _dt(sub.current_period_end),
                    "created_at": _dt(sub.created_at),
                }
            )
        for inv in inv_repo.list_for_workspace(ws.id, limit=1000, offset=0):
            invoices.append(
                {
                    "id": inv.id,
                    "workspace_id": inv.workspace_id,
                    "amount_cents": inv.amount_cents,
                    "currency": inv.currency,
                    "status": inv.status,
                    "provider_ref": inv.provider_ref,
                    "period_start": _dt(inv.period_start),
                    "period_end": _dt(inv.period_end),
                    "created_at": _dt(inv.created_at),
                    "line_items": [
                        {
                            "id": li.id,
                            "description": li.description,
                            "quantity": li.quantity,
                            "amount_cents": li.amount_cents,
                        }
                        for li in inv_repo.list_line_items(inv.id)
                    ],
                }
            )

    consents = [
        {
            "id": c.id,
            "kind": c.kind,
            "granted": c.granted,
            "version": c.version,
            "created_at": _dt(c.created_at),
        }
        for c in ConsentRepository(session).list_for_user(normalized)
    ]

    return {
        "schema": "reelforge.compliance.export/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": normalized,
        "profile": _user_dict(user),
        "jobs": [_job_dict(j) for j in jobs],
        "assets": [_asset_dict(a) for a in assets],
        "credit_ledger": [
            {
                "id": row.id,
                "delta": row.delta,
                "reason": row.reason,
                "balance_after": row.balance_after,
                "job_id": row.job_id,
                "created_at": _dt(row.created_at),
            }
            for row in ledger
        ],
        "subscriptions": subscriptions,
        "invoices": invoices,
        "consents": consents,
        "memberships": [
            {
                "workspace_id": m.workspace_id,
                "role": m.role,
                "created_at": _dt(m.created_at),
            }
            for m in memberships
        ],
    }


def build_export(
    session: Session,
    user_id: str,
    *,
    storage: ExportStorage | None = None,
    presign_expires: int = EXPORT_URL_EXPIRES,
    actor_user_id: str | None = None,
) -> str:
    """Assemble, upload and return a short-lived signed GET URL for the export.

    Builds the requester-scoped package via :func:`assemble_export`, writes it as
    JSON to a temp file, uploads it to R2 under an OWNER-SCOPED key
    (``exports/<user_id>/<ts>-<uuid>.json``) and returns a presigned GET URL that
    expires in ``presign_expires`` seconds. The action is recorded in the audit
    trail (actor defaults to the exporting user — a self-service export).

    ``storage`` defaults to the process-wide R2 client; tests inject a fake.

    Raises:
        ValueError: when ``user_id`` is blank or unknown (from
            :func:`assemble_export`).
    """
    package = assemble_export(session, user_id)
    normalized = package["user_id"]

    payload = json.dumps(package, ensure_ascii=False, indent=2).encode("utf-8")

    # Write to a temp file (per the export contract) then upload its bytes.
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".json", delete=False
        ) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        with open(tmp_path, "rb") as fp:
            data = fp.read()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError as exc:  # pragma: no cover - best-effort cleanup
                logger.warning(f"export temp cleanup failed for {tmp_path}: {exc}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"{_EXPORT_PREFIX}/{normalized}/{ts}-{uuid4().hex}.json"

    client = storage if storage is not None else _default_storage()
    client.upload_bytes(key, data, "application/json")
    url = client.presign_get(
        key,
        expires=int(presign_expires),
        download_name=f"reelforge-export-{normalized}.json",
    )

    audit.record(
        session,
        actor_user_id=(actor_user_id or normalized),
        action=_ACTION_EXPORT,
        target_type="user",
        target_id=normalized,
        metadata={
            "key": key,
            "bytes": len(data),
            "jobs": len(package["jobs"]),
            "assets": len(package["assets"]),
        },
    )
    logger.info(
        f"compliance export built for user={normalized} key={key} "
        f"bytes={len(data)}"
    )
    return url


def _default_storage() -> ExportStorage:
    """Return the process-wide R2 client (resolved lazily so imports stay safe)."""
    from app.services.storage.r2 import get_r2_client

    return get_r2_client()


__all__ = ["EXPORT_URL_EXPIRES", "assemble_export", "build_export"]
