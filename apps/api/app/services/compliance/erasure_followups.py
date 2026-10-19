"""Delete means delete: the side effects of an account erasure (MG1).

:func:`app.services.compliance.erasure.erase_user` anonymizes rows in place.
This module runs what ACCOUNT-LIFECYCLE section 3 adds around it, in order:

4. ``cancel_billing``  cancel the live personal plan (Dodo or Creem) and any
   team plan the user alone owns, at the provider, now.
6. ``stop_work``       revoke queued or running renders and mark them failed.
7. ``delete_media``    delete every R2 object: job media, uploaded and rendered
   assets, voice samples, and everything under ``jobs/<job_id>/`` (which also
   covers objects whose keys the retention sweep already blanked).
5. ``delete_identity`` delete the Clerk user (sessions and sign-in die with it).
9. ``ledger``          keep the tax ledger; move any positive balance out with
   ``forfeited_on_delete`` (MD26: the refund was offered first; the rows stay).
10. ``confirm_mail``   one transactional confirmation to the pre-tombstone email.

Durability without a schema change: the manifest (keys, prefixes, provider
refs, Clerk ids; no email) is one append-only audit row
``compliance.erasure_manifest``; each finished step appends
``compliance.erasure_step``. A crash or a provider outage leaves steps pending;
:func:`retry_pending` (``workers/tasks_erasure.py``) re-runs only those. The
email needed for a retried Clerk lookup or confirmation mail is kept in Redis
for :data:`EMAIL_TTL_SECONDS` only, never in the database.

External calls go through :class:`Deps` so tests inject fakes. A dependency that
is not configured on this server (no R2, no Clerk key) marks its step
``skipped`` and logs it; a call that fails marks it ``failed`` for a retry.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

from loguru import logger
from sqlalchemy import select

from app.models.const import TASK_STATE_FAILED, TASK_STATE_PROCESSING
from sqlalchemy.orm import Session

ACTION_MANIFEST: str = "compliance.erasure_manifest"
ACTION_STEP: str = "compliance.erasure_step"
STEPS: tuple[str, ...] = (
    "cancel_billing", "stop_work", "delete_media", "delete_identity", "ledger", "confirm_mail",
)
DONE, SKIPPED, FAILED = "done", "skipped", "failed"
FORFEIT_REASON: str = "forfeited_on_delete"
EMAIL_TTL_SECONDS: int = 14 * 24 * 3600
_EMAIL_KEY: str = "erasure:email:"
_CLERK_API: str = "https://api.clerk.com/v1"
_SYNTHETIC_CLERK = ("clerk_", "@users.reelforge")
_LIVE_PLAN = frozenset({"active", "trialing", "past_due"})
_OPEN_JOB_STATES = frozenset({TASK_STATE_PROCESSING})  # queued or running


@dataclass(frozen=True)
class Manifest:
    """Everything the follow-ups need, captured before the rows are blanked."""

    request_id: str
    user_id: str
    media_keys: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    plans: tuple[tuple[str, str], ...] = ()  # (provider, subscription id)
    team_plans: tuple[tuple[str, str], ...] = ()
    open_jobs: tuple[tuple[str, str], ...] = ()  # (job id, celery task id)
    clerk_ids: tuple[str, ...] = ()
    store_purchases: bool = False

    def as_meta(self) -> dict[str, Any]:
        return {k: [list(v) if isinstance(v, tuple) else v for v in val] if isinstance(val, tuple) else val
                for k, val in asdict(self).items()}

    @classmethod
    def from_meta(cls, meta: dict[str, Any]) -> "Manifest":
        def pairs(key: str) -> tuple[tuple[str, str], ...]:
            return tuple((str(a), str(b)) for a, b in meta.get(key) or [])

        return cls(
            request_id=str(meta.get("request_id", "")), user_id=str(meta.get("user_id", "")),
            media_keys=tuple(meta.get("media_keys") or ()), prefixes=tuple(meta.get("prefixes") or ()),
            plans=pairs("plans"), team_plans=pairs("team_plans"), open_jobs=pairs("open_jobs"),
            clerk_ids=tuple(meta.get("clerk_ids") or ()), store_purchases=bool(meta.get("store_purchases")),
        )


# --------------------------------------------------------------------------- #
# Dependencies (real by default; tests inject fakes)
# --------------------------------------------------------------------------- #
def _r2() -> Any | None:
    try:
        from app.platform.storage import r2

        return r2.get_r2_client()
    except Exception as exc:  # noqa: BLE001 - not configured on this server
        logger.info(f"erasure: R2 unavailable ({type(exc).__name__}); media step skipped")
        return None


def list_objects(prefix: str) -> list[str]:
    client = _r2()
    if client is None:
        return []
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": client._bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = client._s3.list_objects_v2(**kwargs)
        keys += [str(item["Key"]) for item in page.get("Contents") or []]
        token = page.get("NextContinuationToken")
        if not page.get("IsTruncated") or not token:
            return keys


def _cancel_plan(provider: str, ref: str) -> None:
    if provider == "dodo":
        from app.services.billing import workspace_plans

        workspace_plans.cancel_dodo(ref)
    elif provider == "creem":
        from app.services.billing import creator_creem

        creator_creem._request("POST", f"/v1/subscriptions/{ref}/cancel", body={})  # now
    else:
        raise ValueError(f"no server-side cancel for provider {provider!r}")


def _cancel_team(provider: str, ref: str) -> None:
    from app.services.billing import subscription_providers

    if provider == "dodo":
        _cancel_plan(provider, ref)
    else:
        subscription_providers.cancel(provider, ref)


def _clerk_secret() -> str:
    from app.config import config

    section = getattr(config, "clerk", None) or {}
    return str(dict(section).get("secret_key", "") or os.environ.get("CLERK_SECRET_KEY", "")).strip()


def _clerk_request(method: str, path: str, params: dict | None = None) -> Any:
    import requests

    response = requests.request(
        method, f"{_CLERK_API}{path}", params=params, timeout=(5, 20),
        headers={"Authorization": f"Bearer {_clerk_secret()}", "User-Agent": "menivor-api/1.0"},
    )
    if response.status_code == 404 and method == "DELETE":
        return {}
    response.raise_for_status()
    return response.json() if response.content else {}


def _clerk_lookup(email: str) -> list[str]:
    if not _clerk_secret() or "@" not in email:
        return []
    found = _clerk_request("GET", "/users", params={"email_address": email})
    return [str(u["id"]) for u in (found if isinstance(found, list) else []) if u.get("id")]


def _clerk_delete(user_id: str) -> None:
    _clerk_request("DELETE", f"/users/{user_id}")


def _revoke(task_id: str) -> None:
    from app.workers.celery_app import celery_app

    celery_app.control.revoke(task_id, terminate=False)


def _send_mail(to: str, subject: str, text: str) -> bool:
    from app.services import mailer

    return mailer.send_email(to=to, subject=subject, text=text)


@dataclass(frozen=True)
class Deps:
    r2_delete: Callable[[str], Any] | None = field(default=None)
    r2_list: Callable[[str], list[str]] = list_objects
    cancel_plan: Callable[[str, str], None] = _cancel_plan
    cancel_team: Callable[[str, str], None] = _cancel_team
    clerk_configured: Callable[[], bool] = lambda: bool(_clerk_secret())
    clerk_lookup: Callable[[str], list[str]] = _clerk_lookup
    clerk_delete: Callable[[str], None] = _clerk_delete
    revoke: Callable[[str], None] = _revoke
    send_mail: Callable[[str, str, str], bool] = _send_mail

    def deleter(self) -> Callable[[str], Any] | None:
        if self.r2_delete is not None:
            return self.r2_delete
        client = _r2()
        return client.delete_object if client is not None else None


# --------------------------------------------------------------------------- #
# Capture (before erase_user blanks anything)
# --------------------------------------------------------------------------- #
def _clerk_sub(email: str) -> str:
    head, tail = _SYNTHETIC_CLERK
    return email[len(head):-len(tail)] if email.startswith(head) and email.endswith(tail) else ""


def capture(session: Session, user_id: str, request_id: str, *, deps: Deps | None = None) -> tuple[Manifest, str]:
    """Collect the manifest and the pre-tombstone email for ``user_id``."""
    from app.models.db.creator_subscription import CreatorSubscription
    from app.models.db.models import (
        Asset, CreditLedger, Job, Subscription, User, UserVoice, Workspace, WorkspaceMember,
    )

    deps = deps or Deps()
    user = session.get(User, user_id)
    email = str(getattr(user, "email", "") or "")
    jobs = session.execute(
        select(Job.id, Job.state, Job.celery_task_id, Job.result_key, Job.poster_key,
               Job.preview_key, Job.cover_key).where(Job.user_id == user_id)
    ).all()
    keys = [k for row in jobs for k in row[3:] if k]
    keys += [k for (k,) in session.execute(select(Asset.r2_key).where(Asset.user_id == user_id)).all() if k]
    keys += [k for (k,) in session.execute(select(UserVoice.sample_key).where(UserVoice.user_id == user_id)).all() if k]
    plans = [
        (str(p), str(r)) for p, r, s in session.execute(
            select(CreatorSubscription.provider, CreatorSubscription.provider_ref, CreatorSubscription.status)
            .where(CreatorSubscription.user_id == user_id)
        ).all() if r and str(s).lower() in _LIVE_PLAN
    ]
    owned = [ws for (ws,) in session.execute(select(Workspace.id).where(Workspace.owner_id == user_id)).all()]
    teams: list[tuple[str, str]] = []
    for ws in owned:
        members = session.execute(select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == ws)).all()
        if any(str(m) != user_id for (m,) in members):
            continue  # a shared team keeps its plan; the owner is alerted instead
        sub = session.execute(select(Subscription).where(Subscription.workspace_id == ws)).scalars().first()
        if sub is not None and sub.provider_ref and str(sub.status).lower() in _LIVE_PLAN:
            teams.append((str(sub.provider), str(sub.provider_ref)))
    store = session.execute(
        select(CreditLedger.id).where(CreditLedger.user_id == user_id,
                                      CreditLedger.reason.like("%revenuecat%")).limit(1)
    ).first() is not None
    clerk_ids: list[str] = [_clerk_sub(email)] if _clerk_sub(email) else []
    if not clerk_ids and deps.clerk_configured():
        try:
            clerk_ids = deps.clerk_lookup(email)
        except Exception as exc:  # noqa: BLE001 - retried from the Redis-held email
            logger.warning(f"erasure: Clerk lookup failed for {user_id}: {type(exc).__name__}")
    manifest = Manifest(
        request_id=request_id, user_id=user_id,
        media_keys=tuple(dict.fromkeys(keys)),
        prefixes=tuple(f"jobs/{row[0]}/" for row in jobs),
        plans=tuple(plans), team_plans=tuple(teams),
        open_jobs=tuple((str(r[0]), str(r[2] or "")) for r in jobs if int(r[1] or 0) in _OPEN_JOB_STATES),
        clerk_ids=tuple(clerk_ids), store_purchases=store,
    )
    return manifest, email


def record_manifest(session: Session, manifest: Manifest, email: str) -> None:
    from app.services import audit

    audit.record(session, actor_user_id=manifest.user_id, action=ACTION_MANIFEST,
                 target_type="erasure_request", target_id=manifest.request_id, metadata=manifest.as_meta())
    _stash_email(manifest.request_id, email)


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #
def _cancel_billing(session: Session, m: Manifest, deps: Deps, _email: str) -> str:
    from app.models.db.creator_subscription import CreatorSubscription

    errors = 0
    for provider, ref in m.plans:
        try:
            deps.cancel_plan(provider, ref)
        except Exception as exc:  # noqa: BLE001 - retried
            errors += 1
            logger.error(f"erasure: cancel {provider} plan {ref} failed: {exc}")
    for provider, ref in m.team_plans:
        try:
            deps.cancel_team(provider, ref)
        except Exception as exc:  # noqa: BLE001 - retried
            errors += 1
            logger.error(f"erasure: cancel {provider} team plan {ref} failed: {exc}")
    if errors:
        return FAILED
    for row in session.execute(select(CreatorSubscription).where(CreatorSubscription.user_id == m.user_id)).scalars():
        row.status, row.cancel_at_period_end = "canceled", True
    return DONE if (m.plans or m.team_plans) else SKIPPED


def _stop_work(session: Session, m: Manifest, deps: Deps, _email: str) -> str:
    from app.models.db.models import Job

    for job_id, task_id in m.open_jobs:
        if task_id:
            try:
                deps.revoke(task_id)
            except Exception as exc:  # noqa: BLE001 - the failed state stops workers anyway
                logger.warning(f"erasure: revoke {task_id} failed: {exc}")
        job = session.get(Job, job_id)
        if job is not None and int(job.state or 0) in _OPEN_JOB_STATES:
            job.state, job.error = TASK_STATE_FAILED, "account deleted"
    return DONE if m.open_jobs else SKIPPED


def _delete_media(_session: Session, m: Manifest, deps: Deps, _email: str) -> str:
    delete = deps.deleter()
    if delete is None:
        if m.media_keys:
            logger.error(f"erasure: R2 is not configured; {len(m.media_keys)} keys for {m.user_id} not deleted")
        return SKIPPED
    try:
        keys = list(m.media_keys)
        for prefix in m.prefixes:
            keys += deps.r2_list(prefix)
        for key in dict.fromkeys(keys):
            delete(key)
    except Exception as exc:  # noqa: BLE001 - retried; deletes are idempotent
        logger.error(f"erasure: media delete for {m.user_id} failed: {exc}")
        return FAILED
    return DONE


def _delete_identity(_session: Session, m: Manifest, deps: Deps, email: str) -> str:
    if not deps.clerk_configured():
        return SKIPPED
    try:
        ids = list(m.clerk_ids) or (deps.clerk_lookup(email) if email else [])
        for clerk_id in ids:
            deps.clerk_delete(clerk_id)
    except Exception as exc:  # noqa: BLE001 - retried
        logger.error(f"erasure: Clerk delete for {m.user_id} failed: {type(exc).__name__}")
        return FAILED
    if not ids and not email:
        logger.error(f"erasure: no Clerk id or email left for {m.user_id}; delete the Clerk user by hand")
        return SKIPPED
    return DONE


def _ledger(session: Session, m: Manifest, _deps: Deps, _email: str) -> str:
    from app.models.db.repositories import CreditRepository
    from app.services.billing import premium_credits as pc
    from app.services.billing import service

    service._lock_user_row(session, m.user_id)
    if service._ledger_has_reason(session, m.user_id, FORFEIT_REASON):
        return DONE
    repo = CreditRepository(session)
    balance = repo.balance(m.user_id)
    if balance > 0:
        repo.debit(m.user_id, balance, None, FORFEIT_REASON)
    for kind in pc.KINDS:
        held = pc.balance(session, m.user_id, kind)
        if held > 0 and not pc.has_reason(session, m.user_id, f"{FORFEIT_REASON}:{kind}"):
            pc.debit(session, m.user_id, kind, held, f"{FORFEIT_REASON}:{kind}")
    return DONE


def _confirm_mail(_session: Session, m: Manifest, deps: Deps, email: str) -> str:
    if "@" not in email or email.endswith(".invalid") or email.startswith(_SYNTHETIC_CLERK[0]):
        return SKIPPED
    lines = ["Your Menivor account is deleted.",
             "Your videos, uploads and voice samples are removed from our storage, "
             "and any plan you had with us is cancelled."]
    if m.store_purchases:
        lines.append("If you subscribed in the App Store or Google Play, cancel it there too.")
    lines.append("We keep payment records only as the law requires.")
    return DONE if deps.send_mail(email, "Your Menivor account is deleted", "\n\n".join(lines)) else FAILED


_RUNNERS: dict[str, Callable[[Session, Manifest, Deps, str], str]] = {
    "cancel_billing": _cancel_billing, "stop_work": _stop_work, "delete_media": _delete_media,
    "delete_identity": _delete_identity, "ledger": _ledger, "confirm_mail": _confirm_mail,
}


# --------------------------------------------------------------------------- #
# Run / retry
# --------------------------------------------------------------------------- #
def _finished_steps(session: Session, request_id: str) -> set[str]:
    from app.models.db.models import AuditLog

    rows = session.execute(
        select(AuditLog.meta).where(AuditLog.action == ACTION_STEP, AuditLog.target_id == request_id)
    ).scalars().all()
    return {str(meta.get("step")) for meta in rows if isinstance(meta, dict) and meta.get("status") in (DONE, SKIPPED)}


def run(session: Session, manifest: Manifest, *, email: str = "", deps: Deps | None = None) -> dict[str, str]:
    """Run every unfinished step once, in order. Returns ``{step: status}``."""
    from app.services import audit

    deps = deps or Deps()
    email = email or _stashed_email(manifest.request_id)
    finished = _finished_steps(session, manifest.request_id)
    results: dict[str, str] = {}
    for step in STEPS:
        if step in finished:
            results[step] = DONE
            continue
        try:
            status = _RUNNERS[step](session, manifest, deps, email)
        except Exception as exc:  # noqa: BLE001 - one step never blocks the others
            logger.error(f"erasure: step {step} for {manifest.user_id} crashed: {exc}")
            status = FAILED
        results[step] = status
        if status != FAILED:
            audit.record(session, actor_user_id=manifest.user_id, action=ACTION_STEP,
                         target_type="erasure_request", target_id=manifest.request_id,
                         metadata={"step": step, "status": status})
    session.flush()
    if all(s != FAILED for s in results.values()):
        _drop_email(manifest.request_id)
    return results


def pending(session: Session, *, limit: int = 50) -> list[Manifest]:
    """Manifests with at least one unfinished step, oldest first."""
    from app.models.db.models import AuditLog

    rows = session.execute(
        select(AuditLog.meta).where(AuditLog.action == ACTION_MANIFEST).order_by(AuditLog.created_at.asc())
    ).scalars().all()
    out: list[Manifest] = []
    for meta in rows:
        manifest = Manifest.from_meta(meta if isinstance(meta, dict) else {})
        if manifest.request_id and len(_finished_steps(session, manifest.request_id)) < len(STEPS):
            out.append(manifest)
        if len(out) >= limit:
            break
    return out


def retry_pending(*, deps: Deps | None = None) -> dict[str, int]:
    """Re-run unfinished steps for every pending erasure (Celery entry point)."""
    from app.models.db.base import get_session

    summary = {"requests": 0, "failed_steps": 0}
    with get_session() as session:
        for manifest in pending(session):
            results = run(session, manifest, deps=deps)
            summary["requests"] += 1
            summary["failed_steps"] += sum(1 for s in results.values() if s == FAILED)
    if summary["failed_steps"]:
        logger.error(f"erasure follow-ups still failing: {summary}")
    return summary


def delete_objects(keys: Iterable[str], *, deps: Deps | None = None) -> set[str]:
    """Delete R2 objects; returns the keys that are gone (for the retention sweep).

    With no R2 on this server every key counts as gone (nothing to orphan).
    """
    wanted = [k for k in dict.fromkeys(keys) if k]
    delete = (deps or Deps()).deleter()
    if delete is None:
        return set(wanted)
    gone: set[str] = set()
    for key in wanted:
        try:
            delete(key)
            gone.add(key)
        except Exception as exc:  # noqa: BLE001 - kept for the next sweep
            logger.warning(f"retention: R2 delete failed for {key!r}: {type(exc).__name__}")
    return gone


# --------------------------------------------------------------------------- #
# Delete screen (ACCOUNT-LIFECYCLE steps 1-2; MD26)
# --------------------------------------------------------------------------- #
def deletion_preview(session: Session, user_id: str) -> dict[str, Any]:
    """Balance and credit outcome to show before the user confirms delete."""
    from app.models.db.models import CreditLedger
    from app.models.db.repositories import CreditRepository

    balance = CreditRepository(session).balance(user_id)
    paid = session.execute(
        select(CreditLedger.delta).where(CreditLedger.user_id == user_id, CreditLedger.workspace_id.is_(None),
                                         CreditLedger.reason.like("purchase:%"), CreditLedger.delta > 0)
    ).scalars().all()
    paid_total = sum(int(d) for d in paid if int(d) > 0)
    return {
        "balance": max(0, balance),
        "owed": max(0, -balance),
        "paid_credit_refundable": max(0, min(balance, paid_total)),
        "outcome": {"paid": "refund_offered_then_forfeited", "allowance": "ends", "grant": "forfeited"},
    }


# --------------------------------------------------------------------------- #
# Short-lived email stash (Redis only; never the database)
# --------------------------------------------------------------------------- #
def _redis() -> Any | None:
    try:
        from app.services.billing import service

        return service._get_redis()
    except Exception:  # noqa: BLE001 - optional
        return None


def _stash_email(request_id: str, email: str) -> None:
    client = _redis()
    if client is not None and email:
        try:
            client.set(f"{_EMAIL_KEY}{request_id}", email, ex=EMAIL_TTL_SECONDS)
        except Exception:  # noqa: BLE001 - retries then skip the lookup
            logger.warning("erasure: could not stash the email for retries")


def _stashed_email(request_id: str) -> str:
    client = _redis()
    try:
        value = client.get(f"{_EMAIL_KEY}{request_id}") if client is not None else None
    except Exception:  # noqa: BLE001
        value = None
    return value.decode() if isinstance(value, bytes) else str(value or "")


def _drop_email(request_id: str) -> None:
    client = _redis()
    if client is not None:
        try:
            client.delete(f"{_EMAIL_KEY}{request_id}")
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "ACTION_MANIFEST",
    "ACTION_STEP",
    "Deps",
    "FORFEIT_REASON",
    "Manifest",
    "STEPS",
    "capture",
    "delete_objects",
    "deletion_preview",
    "list_objects",
    "pending",
    "record_manifest",
    "retry_pending",
    "run",
]
