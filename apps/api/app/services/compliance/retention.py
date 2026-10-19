"""Data-retention enforcement + policy management (Compliance, Epic 5).

Two concerns:

* :func:`get_policy` / :func:`set_policy` — read/write a workspace's
  :class:`RetentionPolicy`, gated by ``workspace.settings`` (Epic 1 RBAC) so
  only an owner/admin of THAT workspace can configure it; a set writes an audit
  row.
* :func:`sweep_retention` — the periodic (Celery-beat) sweep. For each
  configured policy it SOFT-PURGES / anonymizes aged jobs and assets older than
  the workspace's own window, and NEVER anything newer than the window — so a
  fresh row is left untouched. A ``NULL`` window means keep-forever (that
  dimension is skipped).

  SCOPING CAVEAT: :class:`Job` / :class:`Asset` are personal rows keyed only on
  ``users.id`` — they carry NO ``workspace_id`` — so a member's rows cannot be
  attributed to a single tenant when that user belongs to several workspaces.
  Applying one workspace's window to such a user would irreversibly destroy data
  another workspace's window says to keep. Until Job/Asset gain a ``workspace_id``
  column, the sweep therefore only touches users for whom the policy's workspace
  is their SOLE membership (see :func:`_sole_workspace_member_ids`); any user in
  more than one workspace is skipped entirely. Full per-workspace isolation
  requires the schema change.

The sweep NEVER cascade-deletes rows: it blanks the content columns (script /
params / R2 keys / asset metadata) in place, keeping every row so foreign keys
stay valid. The R2 OBJECTS behind those keys (and everything under a purged
job's ``jobs/<id>/`` prefix) are deleted first (MG1); a key whose object could
not be deleted is kept on the row so the next sweep retries it, so the sweep
never leaves an unreachable object behind.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.db.models import Asset, Job, WorkspaceMember
from app.models.db.repositories import (
    RetentionPolicyRepository,
    WorkspaceRepository,
)
from app.services import audit, rbac
from app.services.compliance import erasure_followups

#: ``(keys) -> keys now gone``; tests replace it with a fake R2.
_delete_objects: Callable[[list[str]], set[str]] = erasure_followups.delete_objects
#: ``(prefix) -> keys``; lists stage files under ``jobs/<id>/``.
_list_prefix: Callable[[str], list[str]] = erasure_followups.list_objects

#: Audit verbs.
_ACTION_POLICY_SET: str = "compliance.retention_policy_set"
_ACTION_SWEPT: str = "compliance.retention_swept"


def _now(now: datetime | None) -> datetime:
    """Return ``now`` if provided (deterministic tests), else real UTC time."""
    return now if now is not None else datetime.now(timezone.utc)


def _validate_days(days: int | None) -> int | None:
    """Validate a retention window: ``None`` (keep-forever) or a positive int."""
    if days is None:
        return None
    value = int(days)
    if value < 0:
        raise ValueError("retention days must be non-negative or None")
    return value


def get_policy(
    session: Session, user_id: str, workspace_id: str
) -> Any:
    """Return a workspace's :class:`RetentionPolicy` (``workspace.settings``-gated).

    Raises :class:`PermissionError` when ``user_id`` is not an owner/admin of
    ``workspace_id`` (RBAC + tenant isolation). Returns ``None`` when no policy
    is configured yet.
    """
    rbac.require_permission(
        session, user_id, workspace_id, rbac.PERM_WORKSPACE_SETTINGS
    )
    return RetentionPolicyRepository(session).get(workspace_id)


def set_policy(
    session: Session,
    user_id: str,
    workspace_id: str,
    jobs_retention_days: int | None = None,
    assets_retention_days: int | None = None,
) -> Any:
    """Upsert a workspace's retention window; audit the change. RBAC-gated.

    Only an owner/admin of ``workspace_id`` (``workspace.settings``) may call
    this — a non-member or under-privileged caller raises
    :class:`PermissionError` BEFORE any write. ``None`` for a window means
    keep-forever; a negative value is rejected. Returns the persisted policy.
    """
    rbac.require_permission(
        session, user_id, workspace_id, rbac.PERM_WORKSPACE_SETTINGS
    )
    jobs_days = _validate_days(jobs_retention_days)
    assets_days = _validate_days(assets_retention_days)

    policy = RetentionPolicyRepository(session).upsert(
        workspace_id,
        jobs_retention_days=jobs_days,
        assets_retention_days=assets_days,
    )
    audit.record(
        session,
        actor_user_id=user_id,
        action=_ACTION_POLICY_SET,
        workspace_id=workspace_id,
        target_type="workspace",
        target_id=workspace_id,
        metadata={
            "jobs_retention_days": jobs_days,
            "assets_retention_days": assets_days,
        },
    )
    return policy


def _member_user_ids(session: Session, workspace_id: str) -> list[str]:
    """Return the user ids of every member of ``workspace_id`` (tenant scope)."""
    rows = session.execute(
        select(WorkspaceMember.user_id).where(
            WorkspaceMember.workspace_id == workspace_id
        )
    ).scalars().all()
    return [uid for uid in rows if uid]


def _sole_workspace_member_ids(session: Session, workspace_id: str) -> list[str]:
    """Return members of ``workspace_id`` who belong to NO OTHER workspace.

    Retention windows are configured PER WORKSPACE, but :class:`Job` / :class:`Asset`
    rows are personal (owned by ``users.id`` with no ``workspace_id`` column), so a
    row owned by a user who belongs to several workspaces cannot be attributed to
    a single tenant. Purging under one workspace's window would then irreversibly
    destroy data another workspace's (possibly keep-forever) window says to keep —
    a cross-tenant data-loss bug.

    Until Job/Asset carry a ``workspace_id`` this interim scoping only purges rows
    owned by users for whom THIS workspace is their sole membership, so every
    purged row unambiguously belongs to this tenant. Multi-workspace users are
    skipped entirely (their data is never touched by any workspace's sweep).
    """
    members = _member_user_ids(session, workspace_id)
    if not members:
        return []
    counts = dict(
        session.execute(
            select(
                WorkspaceMember.user_id, func.count(WorkspaceMember.id)
            )
            .where(WorkspaceMember.user_id.in_(members))
            .group_by(WorkspaceMember.user_id)
        ).all()
    )
    return [uid for uid in members if counts.get(uid, 0) <= 1]


def _purge_jobs(
    session: Session, user_ids: list[str], cutoff: datetime
) -> int:
    """Anonymize jobs owned by ``user_ids`` created before ``cutoff``.

    Blanks the narration script, prompt params, error text and R2 keys in place
    (the row is kept so foreign keys stay valid). Returns the count purged.
    """
    if not user_ids:
        return 0
    jobs = list(
        session.execute(
            select(Job).where(
                Job.user_id.in_(user_ids),
                Job.created_at < cutoff,
            )
        ).scalars().all()
    )
    media = [(job, [job.result_key, job.poster_key, job.preview_key, job.cover_key]) for job in jobs]
    wanted = [key for _, keys in media for key in keys if key]
    for job in jobs:
        try:
            wanted += _list_prefix(f"jobs/{job.id}/")
        except Exception as exc:  # noqa: BLE001 - the listed stage files wait for the next sweep
            logger.warning(f"retention: could not list jobs/{job.id}/: {type(exc).__name__}")
    gone = _delete_objects(wanted) if wanted else set()
    for job, _keys in media:
        job.script = ""
        job.error = ""
        job.params = {}
        job.result_key = "" if job.result_key in gone else job.result_key
        job.poster_key = "" if job.poster_key in gone else job.poster_key
        job.preview_key = "" if job.preview_key in gone else job.preview_key
        job.cover_key = "" if job.cover_key in gone else job.cover_key
    return len(jobs)


def _purge_assets(
    session: Session, user_ids: list[str], cutoff: datetime
) -> int:
    """Anonymize assets owned by ``user_ids`` created before ``cutoff``.

    Blanks the R2 key and metadata in place (the row is kept). Returns the count.
    """
    if not user_ids:
        return 0
    assets = list(
        session.execute(
            select(Asset).where(
                Asset.user_id.in_(user_ids),
                Asset.created_at < cutoff,
            )
        ).scalars().all()
    )
    gone = _delete_objects([a.r2_key for a in assets if a.r2_key])
    for asset in assets:
        if asset.r2_key and asset.r2_key not in gone:
            continue  # object still there: keep the key so the next sweep retries
        asset.r2_key = ""
        asset.meta = {}
    return len(assets)


def sweep_retention(
    session: Session, *, now: datetime | None = None
) -> dict[str, int]:
    """Enforce every workspace's retention window (the beat sweep entrypoint).

    For each configured :class:`RetentionPolicy`, resolves the workspace's
    SOLE-membership member user ids (see :func:`_sole_workspace_member_ids`) and
    soft-purges/anonymizes their jobs (older than ``jobs_retention_days``) and
    assets (older than ``assets_retention_days``). A ``NULL`` window skips that
    dimension (keep-forever). Each workspace that purged anything writes an audit
    row (actor = the workspace owner). Returns a summary
    ``{"workspaces", "jobs_purged", "assets_purged"}``.

    Cross-tenant safety (interim): because Job/Asset carry no ``workspace_id``, a
    user who belongs to more than one workspace is excluded from EVERY sweep, so
    one tenant's window can never destroy data another tenant's window would keep.
    Only rows owned by users for whom this is their sole workspace — and only
    those predating the window — are purged. Fresh rows are always untouched.
    """
    summary = {"workspaces": 0, "jobs_purged": 0, "assets_purged": 0}
    reference = _now(now)

    policy_repo = RetentionPolicyRepository(session)
    ws_repo = WorkspaceRepository(session)

    for policy in policy_repo.list_all():
        jobs_days = policy.jobs_retention_days
        assets_days = policy.assets_retention_days
        if jobs_days is None and assets_days is None:
            continue  # keep-forever on both dimensions — nothing to sweep

        user_ids = _sole_workspace_member_ids(session, policy.workspace_id)
        if not user_ids:
            continue

        jobs_purged = 0
        assets_purged = 0
        if jobs_days is not None:
            jobs_cutoff = reference - timedelta(days=jobs_days)
            jobs_purged = _purge_jobs(session, user_ids, jobs_cutoff)
        if assets_days is not None:
            assets_cutoff = reference - timedelta(days=assets_days)
            assets_purged = _purge_assets(session, user_ids, assets_cutoff)

        summary["workspaces"] += 1
        summary["jobs_purged"] += jobs_purged
        summary["assets_purged"] += assets_purged

        if jobs_purged or assets_purged:
            session.flush()
            workspace = ws_repo.get(policy.workspace_id)
            actor = workspace.owner_id if workspace is not None else None
            if actor:
                audit.record(
                    session,
                    actor_user_id=actor,
                    action=_ACTION_SWEPT,
                    workspace_id=policy.workspace_id,
                    target_type="workspace",
                    target_id=policy.workspace_id,
                    metadata={
                        "jobs_purged": jobs_purged,
                        "assets_purged": assets_purged,
                    },
                )

    if summary["workspaces"]:
        logger.info(
            f"retention sweep: workspaces={summary['workspaces']} "
            f"jobs_purged={summary['jobs_purged']} "
            f"assets_purged={summary['assets_purged']}"
        )
    return summary


def run_sweep(now: datetime | None = None) -> dict[str, int]:
    """Open a session and run :func:`sweep_retention` (Celery-beat wrapper).

    Best-effort: opens the process DB session (which commits on exit) and
    delegates. NEVER raises — a missing DB layer or an unexpected error degrades
    to a logged zeroed summary so a beat tick can never crash the worker.
    """
    empty = {"workspaces": 0, "jobs_purged": 0, "assets_purged": 0}
    try:
        from app.models.db import base
    except Exception as exc:  # noqa: BLE001 - persistence layer optional
        logger.error(f"retention run_sweep: persistence layer unavailable: {exc}")
        return dict(empty)
    try:
        with base.get_session() as session:
            return sweep_retention(session, now=now)
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash
        logger.error(f"retention run_sweep failed: {exc}")
        return dict(empty)


__all__ = [
    "get_policy",
    "run_sweep",
    "set_policy",
    "sweep_retention",
]
