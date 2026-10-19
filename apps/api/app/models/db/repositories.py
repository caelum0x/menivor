"""Repository layer for ReelForge persistence (INTEGRATION_CONTRACT.md §4.3).

Business logic (API controllers, Celery tasks, telemetry) depends on these
repositories rather than on SQLAlchemy directly, per the repo's Repository
Pattern convention. Each repository is constructed with an active
``Session`` and never commits on its own unless a method's contract needs
row-level atomicity — transaction boundaries are owned by ``get_session()``
or the caller.

Immutability rules honored here:

* ``job_events`` and ``credit_ledger`` rows are only ever INSERTed.
* JSON maps (``Job.stages``) are replaced with a new dict rather than mutated
  in place so SQLAlchemy reliably detects the change and dirty state stays
  explicit.
"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import String, cast, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError, NotSupportedError
from sqlalchemy.orm import Session

from app.models import const
from app.models.db.models import (
    ApiKeyUsage,
    Asset,
    AuditLog,
    BrollPreset,
    ConsentRecord,
    CreatorFollow,
    CreditLedger,
    ErasureRequest,
    ExternalIdentity,
    Invoice,
    InvoiceLineItem,
    Job,
    JobPerformance,
    MarketplaceTemplate,
    MeteredUsage,
    Notification,
    PushToken,
    RetentionPolicy,
    SavedIdea,
    ScheduledPublish,
    ScimToken,
    SecurityPolicy,
    ShareLink,
    SocialAccount,
    StoreConnection,
    SSOConnection,
    Subscription,
    TemplateRating,
    User,
    UserApiKey,
    UserBrand,
    UserPreset,
    UserVoice,
    JobRequest,
    WebhookDelivery,
    WebhookSubscription,
    Workspace,
    WorkspaceMember,
)


class JobRequestRepository:
    """Durable request-idempotency records for the job creation money path."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: str, idempotency_key: str) -> JobRequest | None:
        """Return a caller-scoped idempotency record, if one exists."""
        return self._session.execute(
            select(JobRequest).where(
                JobRequest.user_id == user_id,
                JobRequest.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()

    def create(
        self, user_id: str, idempotency_key: str, request_hash: str
    ) -> JobRequest:
        """Reserve a key in the caller's current transaction.

        The database unique constraint is the cross-process concurrency guard.
        Callers that lose that race must fetch the winning row and replay it.
        """
        row = JobRequest(
            user_id=user_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def delete_created_before(self, before: datetime, limit: int = 1000) -> int:
        """Delete a bounded oldest-first set of expired idempotency records.

        Idempotency keys are intentionally durable long enough for a client to
        retry safely, but they are not financial records.  Selecting IDs first
        makes the deletion portable across SQLite and Postgres while capping a
        beat tick's lock and transaction footprint.
        """
        if not isinstance(before, datetime):
            raise ValueError("before must be a datetime")
        batch_size = max(1, min(int(limit), 10_000))
        ids = list(
            self._session.execute(
                select(JobRequest.id)
                .where(JobRequest.created_at < before)
                .order_by(JobRequest.created_at.asc())
                .limit(batch_size)
            ).scalars()
        )
        if not ids:
            return 0
        result = self._session.execute(
            delete(JobRequest).where(JobRequest.id.in_(ids))
        )
        return int(result.rowcount or 0)


class JobRepository:
    """CRUD + lifecycle transitions for :class:`Job` rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        user_id: str,
        kind: str,
        params: dict,
        batch_id: str | None = None,
    ) -> Job:
        """Insert a new job in the PROCESSING state and flush to obtain its id.

        ``batch_id`` links the job to a batch-variant request (Phase-10 batch
        variant review). It is optional and defaults to ``None`` so a
        single-variant job belongs to no batch; the N jobs of an N-variant
        request share one ``batch_id`` so they can be reviewed together via
        :meth:`list_by_batch`.
        """
        job = Job(
            user_id=user_id,
            kind=kind or "avatar_reel",
            state=const.TASK_STATE_PROCESSING,
            progress=0,
            stages={},
            params=dict(params or {}),
            batch_id=batch_id or None,
        )
        self._session.add(job)
        self._session.flush()  # populate job.id without ending the transaction
        return job

    def get(self, job_id: str) -> Job | None:
        """Return the job by id, or ``None`` if it does not exist."""
        return self._session.get(Job, job_id)

    def list_for_user(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        archived: bool | None = None,
        kind: str | None = None,
    ) -> list[Job]:
        """Return the user's jobs, newest first, paginated.

        Soft-deleted jobs are never returned. ``archived`` filters the library
        view: ``False`` -> active only, ``True`` -> archived only, ``None`` -> both.
        """
        stmt = select(Job).where(Job.user_id == user_id, Job.deleted_at.is_(None))
        if archived is True:
            stmt = stmt.where(Job.archived_at.isnot(None))
        elif archived is False:
            stmt = stmt.where(Job.archived_at.is_(None))
        if kind:
            stmt = stmt.where(Job.kind == kind)
        stmt = (
            stmt.order_by(Job.created_at.desc())
            .limit(max(1, limit))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_visible(self, job_id: str, user_id: str) -> Job | None:
        """Owner-scoped, not-deleted job lookup (``None`` otherwise)."""
        job = self._session.get(Job, job_id)
        if job is None or job.user_id != user_id or job.deleted_at is not None:
            return None
        return job

    def update_library_fields(
        self,
        job_id: str,
        *,
        title: str | None = None,
        archived: bool | None = None,
    ) -> Job | None:
        """Rename and/or archive/unarchive a job (scalar updates only)."""
        job = self._session.get(Job, job_id)
        if job is None:
            return None
        if title is not None:
            job.title = title.strip()[:200]
        if archived is True and job.archived_at is None:
            job.archived_at = datetime.now(timezone.utc)
        elif archived is False:
            job.archived_at = None
        self._session.flush()
        return job

    def soft_delete(self, job_id: str) -> Job | None:
        """Hide a job everywhere (row kept for FK integrity + audit)."""
        job = self._session.get(Job, job_id)
        if job is None:
            return None
        if job.deleted_at is None:
            job.deleted_at = datetime.now(timezone.utc)
        self._session.flush()
        return job

    def list_for_user_by_kind(
        self, user_id: str, kind: str, limit: int = 50, offset: int = 0
    ) -> list[Job]:
        """Return the user's jobs of one ``kind``, newest first, paginated.

        Owner-scoped (filters on ``user_id``) and kind-scoped, so e.g. the studio
        can list a caller's ``broll_gen`` generations without sweeping up their
        reel jobs. A blank ``kind`` never matches.
        """
        normalized = (kind or "").strip()
        if not normalized:
            return []
        stmt = (
            select(Job)
            .where(
                Job.user_id == user_id,
                Job.kind == normalized,
                Job.deleted_at.is_(None),
            )
            .order_by(Job.created_at.desc())
            .limit(max(1, limit))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_by_batch(self, batch_id: str, user_id: str) -> list[Job]:
        """Return all jobs of a batch owned by ``user_id`` (oldest first).

        Phase-10 batch variant review: the N jobs a single ``variants`` request
        fanned out to share one ``batch_id``; this returns them together so a
        user can review every variant side by side.

        Owner-scoped by design — the query filters on BOTH ``batch_id`` *and*
        ``user_id`` so a caller can never read another user's batch by guessing
        its id. An empty / whitespace-only ``batch_id`` never matches (single
        jobs store NULL, so a blank filter must not sweep them up). Ordered
        oldest-first so ``job_id`` (the first created variant) leads.
        """
        normalized = (batch_id or "").strip()
        if not normalized:
            return []
        stmt = (
            select(Job)
            .where(
                Job.batch_id == normalized,
                Job.user_id == user_id,
                Job.deleted_at.is_(None),
            )
            .order_by(Job.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def update_stage(
        self, job_id: str, stage: str, status: str
    ) -> Job | None:
        """Atomically set one stage's status in the ``stages`` map.

        Replaces the JSON map with a new dict (immutable update) so concurrent
        workers touching *different* stages do not silently clobber the whole
        map. The row is locked FOR UPDATE for the duration of the read-modify-
        write to serialize concurrent writers on the same job.
        """
        job = self._locked_job(job_id)
        if job is None:
            return None
        job.stages = {**(job.stages or {}), stage: status}
        self._session.flush()
        return job

    def set_progress(self, job_id: str, progress: int) -> None:
        """Set the coarse-grained 0-100 progress value (clamped)."""
        job = self._session.get(Job, job_id)
        if job is None:
            return
        job.progress = max(0, min(100, int(progress)))
        self._session.flush()

    def mark_failed(
        self, job_id: str, stage: str, error: str
    ) -> Job | None:
        """Mark a job failed, honoring the **first-failure guard**.

        Mirrors ``task.py::_mark_task_failed``: if the job is already FAILED
        with a non-empty error, the earliest root cause wins and the row is
        returned unchanged. Preserves the progress reached before failure.
        """
        job = self._locked_job(job_id)
        if job is None:
            return None

        if job.state == const.TASK_STATE_FAILED and (job.error or "").strip():
            # Earliest root cause already recorded — do not overwrite it.
            return job

        # Default AFTER stripping so a whitespace-only error still yields a
        # non-empty root cause; otherwise the first-failure guard below would
        # be silently defeated on the next mark_failed call.
        message = str(error or "").strip() or "unknown job error"
        logger.error(
            f"job failed, job_id: {job_id}, stage: {stage}, error: {message}"
        )
        job.state = const.TASK_STATE_FAILED
        job.failed_stage = stage
        job.error = message
        job.stages = {**(job.stages or {}), stage: "failed"}
        self._session.flush()
        return job

    def mark_complete(
        self, job_id: str, result_key: str
    ) -> Job | None:
        """Mark a job complete with its final R2 result key at 100% progress."""
        job = self._locked_job(job_id)
        if job is None:
            return None
        job.state = const.TASK_STATE_COMPLETE
        job.progress = 100
        job.result_key = result_key or ""
        self._session.flush()
        return job

    def set_celery_task_id(
        self, job_id: str, celery_task_id: str
    ) -> Job | None:
        """Persist the Celery async-result id used to track/cancel the chain."""
        job = self._session.get(Job, job_id)
        if job is None:
            return None
        job.celery_task_id = celery_task_id or ""
        self._session.flush()
        return job

    def set_artifacts(
        self,
        job_id: str,
        poster_key: str | None = None,
        preview_key: str | None = None,
    ) -> Job | None:
        """Persist the Phase-6 poster/preview R2 keys on a job.

        Each argument is optional: passing ``None`` leaves the corresponding
        column untouched so callers can update the poster and preview keys
        independently as they become available. Empty strings are stored as-is
        (used to clear a previously set key). Returns the job, or ``None`` when
        it does not exist.
        """
        job = self._session.get(Job, job_id)
        if job is None:
            return None
        if poster_key is not None:
            job.poster_key = poster_key
        if preview_key is not None:
            job.preview_key = preview_key
        self._session.flush()
        return job

    def set_result_media(self, job_id: str, media: dict) -> Job | None:
        """Persist the finished reel's WolfCut clip descriptor (generate->edit).

        Stashed under the private ``_result_media`` key of the ``stages`` JSON
        map (no schema migration): the URL-less base of the WolfCut
        ``GeneratedClip`` descriptor — exact width/height/frame-rate/codecs plus
        job-side caption timing — so ``GET /jobs/{id}`` can surface it with a
        freshly-presigned ``src`` and the desktop opens the reel straight in the
        editor. The key is namespaced and stripped from the public ``stages``
        map by the read path, so it never collides with a real stage name.

        A blank/non-dict ``media`` is ignored. Returns the job, or ``None`` when
        it does not exist. The dict is reassigned (not mutated in place) so
        SQLAlchemy's JSON change tracking always flushes the update.
        """
        job = self._session.get(Job, job_id)
        if job is None:
            return None
        if not isinstance(media, dict) or not media:
            return job
        stages = dict(job.stages or {})
        stages["_result_media"] = media
        job.stages = stages
        self._session.flush()
        return job

    def set_webhook_url(self, job_id: str, webhook_url: str) -> Job | None:
        """Persist the optional completion-notification callback URL."""
        job = self._session.get(Job, job_id)
        if job is None:
            return None
        job.webhook_url = webhook_url or ""
        self._session.flush()
        return job

    def set_script(self, job_id: str, script: str) -> Job | None:
        """Persist the job's finalized narration script.

        Stored so an existing job can later be re-run, displayed, or dubbed
        into other languages (multi-language dubbing translates this script and
        re-runs the pipeline). A blank/``None`` value is coerced to ``""`` so
        the column is never written as SQL ``NULL`` by this setter. Returns the
        updated job, or ``None`` when it does not exist.
        """
        job = self._session.get(Job, job_id)
        if job is None:
            return None
        job.script = script or ""
        self._session.flush()
        return job

    def set_cover(self, job_id: str, cover_key: str) -> Job | None:
        """Persist the R2 key of the job's latest generated cover/thumbnail.

        The Cover / Thumbnail Generator renders a headline over the job's poster
        frame and uploads the result to R2; this records the resulting key so
        the UI can display and re-download it. Regenerating with a different
        headline/style overwrites the key. A blank/``None`` value is coerced to
        ``""`` so the column is never written as SQL ``NULL`` by this setter.
        Returns the updated job, or ``None`` when it does not exist.
        """
        job = self._session.get(Job, job_id)
        if job is None:
            return None
        job.cover_key = cover_key or ""
        self._session.flush()
        return job

    def _locked_job(self, job_id: str) -> Job | None:
        """SELECT ... FOR UPDATE a job to serialize concurrent state writes.

        Falls back to a plain get only when the backend does not support row
        locking (SQLite in tests raises ``NotSupportedError``); any other
        backend error is a real failure and propagates unchanged.
        """
        try:
            stmt = select(Job).where(Job.id == job_id).with_for_update()
            return self._session.execute(stmt).scalars().first()
        except NotSupportedError:
            if self._session.get_bind().dialect.name != "sqlite":
                raise
            # SQLite (tests): no row locks — degrade to an unlocked read.
            return self._session.get(Job, job_id)


class AssetRepository:
    """CRUD for :class:`Asset` artifact rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: str,
        kind: str,
        r2_key: str,
        job_id: str | None = None,
        content_type: str = "",
        size_bytes: int = 0,
        duration_s: float = 0.0,
        meta: dict | None = None,
    ) -> Asset:
        """Insert an asset row and flush to obtain its id."""
        asset = Asset(
            user_id=user_id,
            job_id=job_id,
            kind=kind,
            r2_key=r2_key,
            content_type=content_type,
            size_bytes=int(size_bytes or 0),
            duration_s=float(duration_s or 0.0),
            meta=dict(meta or {}),
        )
        self._session.add(asset)
        self._session.flush()
        return asset

    def get(self, asset_id: str) -> Asset | None:
        """Return an asset by id, or ``None``."""
        return self._session.get(Asset, asset_id)

    def list_for_job(self, job_id: str) -> list[Asset]:
        """Return all assets for a job, oldest first."""
        stmt = (
            select(Asset)
            .where(Asset.job_id == job_id)
            .order_by(Asset.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())


class BrollPresetRepository:
    """Read access to curated + user AI B-roll motion presets."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_available(self, user_id: str) -> list[BrollPreset]:
        """Return the presets ``user_id`` may use: global/public + their own.

        A preset is visible when it is active AND (global — ``user_id`` NULL — OR
        marked ``is_public`` OR owned by the caller). Strictly scoped: another
        user's PRIVATE preset is never returned. Global curated presets lead
        (NULL ``user_id`` sorts first), then newest first — a stable order for the
        studio picker.
        """
        normalized = (user_id or "").strip()
        stmt = (
            select(BrollPreset)
            .where(
                BrollPreset.is_active.is_(True),
                or_(
                    BrollPreset.user_id.is_(None),
                    BrollPreset.is_public.is_(True),
                    BrollPreset.user_id == normalized,
                ),
            )
            .order_by(
                BrollPreset.user_id.is_(None).desc(),
                BrollPreset.created_at.desc(),
            )
        )
        return list(self._session.execute(stmt).scalars().all())


class CreditRepository:
    """Append-only credit ledger with atomic debit/grant + running balance."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def balance(self, user_id: str) -> int:
        """Return the latest *personal* balance for a user (newest balance_after).

        Only personal-pool rows (``workspace_id IS NULL``) are considered, so a
        workspace-pool row that records this user as its actor can never bleed
        into the personal balance. Returns 0 when no personal rows exist yet.
        """
        stmt = (
            select(CreditLedger.balance_after)
            .where(
                CreditLedger.user_id == user_id,
                CreditLedger.workspace_id.is_(None),
            )
            .order_by(CreditLedger.id.desc())
            .limit(1)
        )
        latest = self._session.execute(stmt).scalars().first()
        return int(latest) if latest is not None else 0

    def workspace_balance(self, workspace_id: str) -> int:
        """Return a workspace shared-pool balance as ``SUM(delta)``.

        The pool balance is the running sum of every ledger row tagged with this
        ``workspace_id`` (grants add, debits subtract). Computed as an aggregate
        rather than read from the newest ``balance_after`` so it is correct even
        if rows were ever inserted out of id order. Returns 0 for an empty pool.
        """
        stmt = select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
            CreditLedger.workspace_id == workspace_id
        )
        total = self._session.execute(stmt).scalar_one()
        return int(total or 0)

    def list_for_user(self, user_id: str) -> list[CreditLedger]:
        """Return a user's PERSONAL ledger rows, oldest first (owner-scoped).

        Only personal-pool rows (``workspace_id IS NULL``) owned by ``user_id``
        are returned so a workspace-pool row (which merely records this user as
        its actor) can never leak into a personal data export. A blank
        ``user_id`` never matches. Used by the GDPR data-export assembly to
        include the requester's own financial ledger — and only theirs.
        """
        normalized = (user_id or "").strip()
        if not normalized:
            return []
        stmt = (
            select(CreditLedger)
            .where(
                CreditLedger.user_id == normalized,
                CreditLedger.workspace_id.is_(None),
            )
            .order_by(CreditLedger.id.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def debit(
        self, user_id: str, amount: int, job_id: str, reason: str
    ) -> CreditLedger:
        """Atomically deduct ``amount`` credits, recording ``balance_after``.

        Positive ``amount`` is subtracted (stored as a negative delta). Raises
        ``ValueError`` on non-positive amounts or insufficient balance so the
        caller can surface a 402. The user row is locked to serialize
        concurrent debits.
        """
        if amount <= 0:
            raise ValueError("debit amount must be positive")

        current = self._locked_balance(user_id)
        if current < amount and job_id:
            current = self._grant_plan_overage(user_id, amount - current, job_id, reason, current)
        if current < amount:
            raise ValueError(
                f"insufficient credits: balance={current}, required={amount}"
            )

        new_balance = current - amount
        entry = self._append(
            user_id=user_id,
            delta=-amount,
            reason=reason,
            balance_after=new_balance,
            job_id=job_id,
        )
        return entry

    def _grant_plan_overage(
        self, user_id: str, shortfall: int, job_id: str, reason: str, current: int
    ) -> int:
        """Cover a reel debit's shortfall for a metered Dodo plan (billed as usage).

        Returns the balance after the overage grant, or ``current`` unchanged
        when overage does not apply (the caller then raises as before).
        """
        try:
            from app.services.billing import dodo_usage

            if not dodo_usage.overage_allowance(
                self._session, user_id, shortfall, job_id, reason
            ):
                return current
        except Exception as exc:  # noqa: BLE001 - overage is optional; fail closed
            from loguru import logger

            logger.warning(f"plan overage check failed for job {job_id}: {exc}")
            return current
        entry = self._append(
            user_id=user_id,
            delta=int(shortfall),
            reason=dodo_usage.overage_reason(job_id),
            balance_after=current + int(shortfall),
            job_id=job_id,
        )
        return int(entry.balance_after)

    def grant(
        self, user_id: str, amount: int, reason: str, job_id: str | None = None
    ) -> CreditLedger:
        """Atomically add ``amount`` credits, recording ``balance_after``."""
        if amount <= 0:
            raise ValueError("grant amount must be positive")

        current = self._locked_balance(user_id)
        new_balance = current + amount
        return self._append(
            user_id=user_id,
            delta=amount,
            reason=reason,
            balance_after=new_balance,
            job_id=job_id,
        )

    def workspace_grant(
        self,
        workspace_id: str,
        amount: int,
        reason: str,
        actor_user_id: str | None = None,
        job_id: str | None = None,
    ) -> CreditLedger:
        """Atomically add ``amount`` credits to a workspace shared pool.

        ``actor_user_id`` (the member who funded the pool, if any) is recorded on
        the row for audit only — it never affects any personal balance because
        the row is tagged with ``workspace_id`` and personal reads exclude such
        rows. Raises ``ValueError`` on a non-positive amount.
        """
        if amount <= 0:
            raise ValueError("grant amount must be positive")

        current = self._locked_workspace_balance(workspace_id)
        new_balance = current + amount
        return self._append_workspace(
            workspace_id=workspace_id,
            user_id=actor_user_id,
            delta=amount,
            reason=reason,
            balance_after=new_balance,
            job_id=job_id,
        )

    def workspace_debit(
        self, workspace_id: str, amount: int, job_id: str | None, reason: str
    ) -> CreditLedger:
        """Atomically deduct ``amount`` from a workspace shared pool.

        Mirrors :meth:`debit` exactly but against the workspace pool: the
        ``Workspace`` row is locked (``FOR UPDATE``, degrading gracefully on
        SQLite) to serialize concurrent debits, the pool balance is recomputed
        under the lock, and a negative row is appended only when the pool can
        cover it. Raises ``ValueError`` on a non-positive amount or when the pool
        balance is below ``amount`` so the caller can surface a 402 — the pool
        can never go negative.
        """
        if amount <= 0:
            raise ValueError("debit amount must be positive")

        current = self._locked_workspace_balance(workspace_id)
        if current < amount:
            raise ValueError(
                f"insufficient workspace credits: "
                f"balance={current}, required={amount}"
            )

        new_balance = current - amount
        return self._append_workspace(
            workspace_id=workspace_id,
            user_id=None,
            delta=-amount,
            reason=reason,
            balance_after=new_balance,
            job_id=job_id,
        )

    def _append(
        self,
        *,
        user_id: str,
        delta: int,
        reason: str,
        balance_after: int,
        job_id: str | None,
    ) -> CreditLedger:
        """INSERT one immutable ledger row and refresh the User.credits cache."""
        entry = CreditLedger(
            user_id=user_id,
            job_id=job_id,
            delta=delta,
            reason=reason,
            balance_after=balance_after,
        )
        self._session.add(entry)
        # Keep the denormalized User.credits cache in sync.
        from app.models.db.models import User

        user = self._session.get(User, user_id)
        if user is not None:
            user.credits = balance_after
        self._session.flush()
        return entry

    def _locked_balance(self, user_id: str) -> int:
        """Lock the user row (FOR UPDATE) then read the current balance.

        Locking the ``User`` row serializes concurrent debit/grant operations
        for the same user so ``balance_after`` stays monotonic and correct.
        Only SQLite's lack of ``FOR UPDATE`` (raised as ``NotSupportedError``)
        is tolerated; any other backend error — including real Postgres/Neon
        locking failures — propagates instead of being silently swallowed.
        """
        from app.models.db.models import User

        try:
            stmt = select(User).where(User.id == user_id).with_for_update()
            self._session.execute(stmt).scalars().first()
        except NotSupportedError:
            if self._session.get_bind().dialect.name != "sqlite":
                raise
            # SQLite (tests): no row locks — proceed with an unlocked read.
        return self.balance(user_id)

    def _append_workspace(
        self,
        *,
        workspace_id: str,
        user_id: str | None,
        delta: int,
        reason: str,
        balance_after: int,
        job_id: str | None,
    ) -> CreditLedger:
        """INSERT one immutable workspace-pool ledger row.

        Unlike :meth:`_append` this never touches a ``User.credits`` cache — a
        workspace shared pool has no per-user cache column; its balance is always
        derived from ``SUM(delta)`` via :meth:`workspace_balance`.
        """
        entry = CreditLedger(
            user_id=user_id,
            workspace_id=workspace_id,
            job_id=job_id,
            delta=delta,
            reason=reason,
            balance_after=balance_after,
        )
        self._session.add(entry)
        self._session.flush()
        return entry

    def _locked_workspace_balance(self, workspace_id: str) -> int:
        """Lock the ``Workspace`` row (FOR UPDATE) then read the pool balance.

        Locking the ``Workspace`` row serializes concurrent workspace
        debit/grant operations so the shared pool stays consistent. Mirrors
        :meth:`_locked_balance`: only SQLite's missing ``FOR UPDATE`` support
        (``NotSupportedError``) is tolerated; every other backend error —
        including real Postgres/Neon locking failures — propagates.
        """
        try:
            stmt = (
                select(Workspace)
                .where(Workspace.id == workspace_id)
                .with_for_update()
            )
            self._session.execute(stmt).scalars().first()
        except NotSupportedError:
            if self._session.get_bind().dialect.name != "sqlite":
                raise
            # SQLite (tests): no row locks — proceed with an unlocked read.
        return self.workspace_balance(workspace_id)


class UserRepository:
    """Read/update helpers for :class:`User` growth (referral) columns."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: str) -> User | None:
        """Return a user by id, or ``None``."""
        return self._session.get(User, user_id)

    def get_by_referral_code(self, code: str) -> User | None:
        """Return the user owning ``code`` (case-insensitive), or ``None``.

        Empty / whitespace-only input never matches. Matching is
        case-insensitive so a code shared in any casing resolves to the same
        owner regardless of how it was persisted.
        """
        normalized = (code or "").strip()
        if not normalized:
            return None
        stmt = (
            select(User)
            .where(func.upper(User.referral_code) == normalized.upper())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def set_referral_code(self, user_id: str, code: str) -> User | None:
        """Persist a user's ``referral_code`` (populated on demand).

        Returns the updated user, or ``None`` when the user does not exist.
        Raises ``ValueError`` on an empty code so a blank value never silently
        clears the unique column.
        """
        normalized = (code or "").strip()
        if not normalized:
            raise ValueError("referral_code must be a non-empty string")
        user = self._session.get(User, user_id)
        if user is None:
            return None
        user.referral_code = normalized
        self._session.flush()
        return user


class UserPresetRepository:
    """CRUD for :class:`UserPreset` "brand kit" rows with ownership checks."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        user_id: str,
        name: str,
        config: dict | None = None,
        workspace_id: str | None = None,
    ) -> UserPreset:
        """Insert a new brand-kit preset and flush to obtain its id.

        The ``config`` mapping is copied (immutable update) so later mutation of
        the caller's dict cannot bleed into the persisted row. When
        ``workspace_id`` is provided the preset is SHARED to that workspace so
        every member sees it via :meth:`list_for_user_and_workspaces`; when
        ``None`` (the default) it stays private to ``user_id``.
        """
        preset = UserPreset(
            user_id=user_id,
            name=name,
            config=dict(config or {}),
            workspace_id=workspace_id,
        )
        self._session.add(preset)
        self._session.flush()
        return preset

    def list_for_user(self, user_id: str) -> list[UserPreset]:
        """Return the user's presets, newest first."""
        stmt = (
            select(UserPreset)
            .where(UserPreset.user_id == user_id)
            .order_by(UserPreset.created_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_for_user_and_workspaces(
        self, user_id: str, workspace_ids: list[str]
    ) -> list[UserPreset]:
        """Return the user's own presets UNION presets shared to their workspaces.

        A member sees every preset they own (private *and* the ones they shared)
        plus every preset any teammate shared to a workspace in ``workspace_ids``
        — the caller passes the workspaces the user is actually a member of, so a
        non-member never receives another team's shared presets. De-duplicated
        (a preset the user owns *and* shared appears once) and ordered newest
        first. An empty / falsy ``workspace_ids`` narrows the result to the
        user's own presets.
        """
        conditions = [UserPreset.user_id == user_id]
        valid_ids = [ws_id for ws_id in (workspace_ids or []) if ws_id]
        if valid_ids:
            conditions.append(UserPreset.workspace_id.in_(valid_ids))

        stmt = (
            select(UserPreset)
            .where(or_(*conditions))
            .order_by(UserPreset.created_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def get(self, preset_id: str, user_id: str) -> UserPreset | None:
        """Return the preset only when it exists *and* belongs to ``user_id``.

        Ownership is enforced here so a caller cannot read another user's
        preset by guessing its id; a foreign or missing id returns ``None``.
        """
        preset = self._session.get(UserPreset, preset_id)
        if preset is None or preset.user_id != user_id:
            return None
        return preset

    def delete(self, preset_id: str, user_id: str) -> bool:
        """Delete a preset owned by ``user_id``; return whether a row was removed.

        Returns ``False`` (without deleting) when the preset does not exist or
        belongs to a different user, so ownership is never bypassed.
        """
        preset = self.get(preset_id, user_id)
        if preset is None:
            return False
        self._session.delete(preset)
        self._session.flush()
        return True


class UserVoiceRepository:
    """CRUD for :class:`UserVoice` cloned "brand voice" rows with ownership checks.

    Phase-11 brand voice / voice cloning: a creator uploads a voice sample which
    ElevenLabs Instant Voice Clone turns into a private voice, selectable as a
    reel narrator via ``voice_name = "elevenlabs:<provider_voice_id>"``. Consent
    (ownership/authorization attestation) is mandatory and stored per row.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: str,
        name: str,
        provider_voice_id: str = "",
        provider: str = "elevenlabs",
        sample_key: str = "",
        consent: bool = False,
        status: str = "ready",
    ) -> UserVoice:
        """Insert a new cloned-voice row and flush to obtain its id.

        ``consent`` records the creator's mandatory attestation that they own or
        are authorized to use the sampled voice; it defaults to ``False`` so a
        row is never implicitly treated as consented. ``provider_voice_id`` may
        be empty when the row is created before the clone completes
        (``status == "processing"``).
        """
        voice = UserVoice(
            user_id=user_id,
            name=name or "",
            provider=provider or "elevenlabs",
            provider_voice_id=provider_voice_id or "",
            sample_key=sample_key or "",
            consent=bool(consent),
            status=status or "ready",
        )
        self._session.add(voice)
        self._session.flush()  # populate voice.id without ending the transaction
        return voice

    def list_for_user(self, user_id: str) -> list[UserVoice]:
        """Return the user's cloned voices, newest first."""
        stmt = (
            select(UserVoice)
            .where(UserVoice.user_id == user_id)
            .order_by(UserVoice.created_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def get(self, voice_id: str) -> UserVoice | None:
        """Return a cloned voice by id, or ``None`` if it does not exist.

        Not ownership-scoped — use :meth:`get_owned` when the caller must be the
        owner. This unscoped lookup exists so a worker can resolve a job's
        narrator voice regardless of which request thread owns it.
        """
        return self._session.get(UserVoice, voice_id)

    def get_owned(self, voice_id: str, user_id: str) -> UserVoice | None:
        """Return the voice only when it exists *and* belongs to ``user_id``.

        Ownership is enforced here so a caller cannot read another user's voice
        by guessing its id; a foreign or missing id returns ``None``.
        """
        voice = self._session.get(UserVoice, voice_id)
        if voice is None or voice.user_id != user_id:
            return None
        return voice

    def delete(self, voice_id: str, user_id: str) -> bool:
        """Delete a voice owned by ``user_id``; return whether a row was removed.

        Returns ``False`` (without deleting) when the voice does not exist or
        belongs to a different user, so ownership is never bypassed.
        """
        voice = self.get_owned(voice_id, user_id)
        if voice is None:
            return False
        self._session.delete(voice)
        self._session.flush()
        return True


#: Valid inclusive bounds for a :class:`UserBrand` overlay opacity. FFmpeg's
#: ``colorchannelmixer aa=<opacity>`` expects a fraction in [0.0, 1.0]; an
#: out-of-range value is clamped here so an untrusted API payload can never
#: produce an invalid filtergraph or a fully-transparent/over-bright overlay.
WATERMARK_OPACITY_MIN = 0.0
WATERMARK_OPACITY_MAX = 1.0

#: Default overlay corner for a brand watermark when none is chosen. Mirrors the
#: ``UserBrand.position`` column default.
WATERMARK_DEFAULT_POSITION = "bottom_right"

#: The overlay corners the compositor understands. An unknown corner falls back
#: to :data:`WATERMARK_DEFAULT_POSITION` so a bad value never breaks the render.
WATERMARK_POSITIONS: frozenset[str] = frozenset(
    {"bottom_right", "bottom_left", "top_right", "top_left"}
)


def _clamp_opacity(value: float) -> float:
    """Clamp a watermark opacity into the valid ``[0.0, 1.0]`` range."""
    return max(WATERMARK_OPACITY_MIN, min(WATERMARK_OPACITY_MAX, float(value)))


def _normalize_position(value: str) -> str:
    """Normalize an overlay corner, falling back to the default on an unknown one."""
    normalized = (str(value or "")).strip().lower()
    return normalized if normalized in WATERMARK_POSITIONS else WATERMARK_DEFAULT_POSITION


class UserBrandRepository:
    """Read + upsert for the per-user :class:`UserBrand` watermark singleton.

    Brand Watermark feature: a creator uploads a transparent PNG logo (stored in
    R2) which the compose stage overlays on their reels at a chosen corner +
    opacity. Exactly ONE row exists per user (``user_id`` is UNIQUE), so
    :meth:`upsert` updates the existing row in place rather than inserting a
    duplicate, and :meth:`get` resolves the singleton by owner id.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: str) -> UserBrand | None:
        """Return the user's brand settings, or ``None`` when unset.

        A blank ``user_id`` never matches (returns ``None``) so an empty owner
        id can never sweep up an unrelated row.
        """
        normalized = (user_id or "").strip()
        if not normalized:
            return None
        stmt = select(UserBrand).where(UserBrand.user_id == normalized).limit(1)
        return self._session.execute(stmt).scalars().first()

    def upsert(self, user_id: str, **fields: object) -> UserBrand:
        """Create or update the user's brand settings, returning the row.

        Only the recognized keys (``logo_key``, ``position``, ``opacity``,
        ``enabled``) are applied and only when their value is not ``None`` — a
        partial update leaves the untouched columns as they were (or at their
        column default on first insert). Values are coerced/validated at this
        boundary: ``opacity`` is clamped to ``[0.0, 1.0]``, ``position`` is
        normalized to a known corner, ``enabled`` is coerced to ``bool`` and
        ``logo_key`` to ``str`` — so an untrusted API payload can never persist
        an invalid setting. Raises ``ValueError`` on a blank ``user_id``.
        """
        normalized = (user_id or "").strip()
        if not normalized:
            raise ValueError("user_id must be a non-empty string")

        brand = self.get(normalized)
        if brand is None:
            brand = UserBrand(user_id=normalized)
            self._session.add(brand)

        if fields.get("logo_key") is not None:
            brand.logo_key = str(fields["logo_key"])
        if fields.get("position") is not None:
            brand.position = _normalize_position(str(fields["position"]))
        if fields.get("opacity") is not None:
            brand.opacity = _clamp_opacity(float(fields["opacity"]))  # type: ignore[arg-type]
        if fields.get("enabled") is not None:
            brand.enabled = bool(fields["enabled"])

        self._session.flush()
        return brand


#: Character cap for the denormalized ``SavedIdea.title`` / ``SavedIdea.hook``
#: columns, which are ``mapped_column(String(300))`` (VARCHAR(300) on
#: PostgreSQL). Caller-supplied idea dicts are untrusted (typed
#: ``dict[str, Any]`` at the API boundary), so an oversized title/hook must be
#: truncated to this length before the INSERT. Without the cap PostgreSQL
#: raises ``StringDataRightTruncation`` and the controller's bare
#: ``except Exception`` turns it into a confusing 502 instead of a clean 4xx.
#: Kept in sync with ``SavedIdea.title``/``SavedIdea.hook`` String() length.
SAVED_IDEA_TEXT_MAX_LEN = 300


def _truncate(value: object, max_len: int) -> str:
    """Coerce ``value`` to ``str`` and cap it at ``max_len`` characters.

    Untrusted payloads may carry non-string or oversized values; this both
    coerces the type (so a ``String`` column never receives a bad type) and
    bounds the length (so a VARCHAR column never raises a truncation
    ``DataError``). ``None``/empty coerces to ``""``.
    """
    text = str(value or "")
    return text[:max_len]


class SavedIdeaRepository:
    """CRUD for :class:`SavedIdea` SPARK concepts with ownership checks.

    Phase-18 (SPARK — AI Idea Engine): a creator generates N viral UGC video
    concepts and can save any of them for later. The full concept dict is stored
    opaquely; ``title`` and ``hook`` are denormalized out of it for cheap list
    rendering. All reads/deletes are owner-scoped so a caller can never touch
    another user's saved idea by guessing its id.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, user_id: str, idea: dict) -> SavedIdea:
        """Persist a saved idea and flush to obtain its id.

        The ``idea`` mapping is copied (immutable update) so later mutation of
        the caller's dict cannot bleed into the persisted row. ``title`` and
        ``hook`` are denormalized out of the idea (coerced to ``str`` and empty
        when absent) as indexed/displayable columns; the untouched idea is kept
        whole in ``payload`` so nothing is lost.

        ``title`` and ``hook`` are truncated to
        :data:`SAVED_IDEA_TEXT_MAX_LEN` (the ``String(300)`` column limit)
        because the caller-supplied idea dict is untrusted and unbounded in
        length. Truncating here keeps an oversized value from reaching the DB
        as a ``StringDataRightTruncation`` on PostgreSQL — which the
        controller's bare ``except`` would surface as a 502 — while the full,
        untouched idea is still preserved in the unlimited JSON ``payload``.
        """
        payload = dict(idea or {})
        return self._create_row(
            user_id=user_id,
            title=_truncate(payload.get("title"), SAVED_IDEA_TEXT_MAX_LEN),
            hook=_truncate(payload.get("hook"), SAVED_IDEA_TEXT_MAX_LEN),
            payload=payload,
        )

    def _create_row(
        self, *, user_id: str, title: str, hook: str, payload: dict
    ) -> SavedIdea:
        """INSERT one saved-idea row and flush to populate its id."""
        row = SavedIdea(
            user_id=user_id,
            title=title,
            hook=hook,
            payload=payload,
        )
        self._session.add(row)
        self._session.flush()  # populate row.id without ending the transaction
        return row

    def list_for_user(self, user_id: str, limit: int = 50) -> list[SavedIdea]:
        """Return the user's saved ideas, newest first, capped at ``limit``."""
        stmt = (
            select(SavedIdea)
            .where(SavedIdea.user_id == user_id)
            .order_by(SavedIdea.created_at.desc())
            .limit(max(1, limit))
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_owned(self, idea_id: str, user_id: str) -> SavedIdea | None:
        """Return the idea only when it exists *and* belongs to ``user_id``.

        Ownership is enforced here so a caller cannot read another user's saved
        idea by guessing its id; a foreign or missing id returns ``None``.
        """
        idea = self._session.get(SavedIdea, idea_id)
        if idea is None or idea.user_id != user_id:
            return None
        return idea

    def delete(self, idea_id: str, user_id: str) -> bool:
        """Delete an idea owned by ``user_id``; return whether a row was removed.

        Returns ``False`` (without deleting) when the idea does not exist or
        belongs to a different user, so ownership is never bypassed.
        """
        idea = self.get_owned(idea_id, user_id)
        if idea is None:
            return False
        self._session.delete(idea)
        self._session.flush()
        return True


#: Character cap for the denormalized ``Notification.title`` column
#: (``mapped_column(String(300))`` == VARCHAR(300) on PostgreSQL). Notification
#: content is assembled from untrusted, unbounded sources (job errors, referral
#: metadata), so an oversized title must be truncated before the INSERT or
#: PostgreSQL raises ``StringDataRightTruncation``. Kept in sync with
#: ``Notification.title``'s ``String()`` length.
NOTIFICATION_TITLE_MAX_LEN = 300


class NotificationRepository:
    """CRUD + unread bookkeeping for :class:`Notification` rows.

    The in-app counterpart to the external webhook: the server best-effort emits
    a notification on lifecycle / growth events (``job_complete``,
    ``job_failed``, ``low_credits``, ``referral_earned``) and the client renders
    an unread badge + list. All reads/mutations are owner-scoped so a caller can
    never read or flip another user's notification by guessing its id.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        user_id: str,
        kind: str,
        title: str,
        body: str = "",
        data: dict | None = None,
    ) -> Notification:
        """Insert a new (unread) notification and flush to obtain its id.

        The ``data`` mapping is copied (immutable update) so later mutation of
        the caller's dict cannot bleed into the persisted row. ``title`` is
        coerced to ``str`` and truncated to :data:`NOTIFICATION_TITLE_MAX_LEN`
        (the ``String(300)`` column limit) because notification content is
        assembled from untrusted, unbounded sources (job errors, referral
        metadata) — truncating here keeps an oversized value from reaching the
        DB as a ``StringDataRightTruncation`` on PostgreSQL.
        """
        notification = Notification(
            user_id=user_id,
            kind=kind or "",
            title=_truncate(title, NOTIFICATION_TITLE_MAX_LEN),
            body=str(body or ""),
            data=dict(data or {}),
            read=False,
        )
        self._session.add(notification)
        self._session.flush()  # populate id without ending the transaction
        return notification

    def list_for_user(
        self, user_id: str, limit: int = 50, unread_only: bool = False
    ) -> list[Notification]:
        """Return the user's notifications, newest first, capped at ``limit``.

        When ``unread_only`` is ``True`` only unread rows are returned (backed by
        the composite ``(user_id, read)`` index). ``limit`` is clamped to at
        least 1 so a non-positive value never yields an invalid page.
        """
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.read.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc()).limit(max(1, limit))
        return list(self._session.execute(stmt).scalars().all())

    def unread_count(self, user_id: str) -> int:
        """Return the number of unread notifications for the bell badge.

        Uses ``COUNT(*)`` over the ``(user_id, read)`` index so the badge query
        never materializes rows.
        """
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.read.is_(False),
            )
        )
        return int(self._session.execute(stmt).scalar_one() or 0)

    def mark_read(self, notification_id: str, user_id: str) -> bool:
        """Flip one notification to read; return whether a row changed.

        Owner-scoped: returns ``False`` (without touching any row) when the
        notification does not exist or belongs to a different user, so a caller
        can never flip another user's notification by guessing its id. An
        already-read notification is a no-op that still returns ``True`` (the
        desired end state holds).
        """
        notification = self._session.get(Notification, notification_id)
        if notification is None or notification.user_id != user_id:
            return False
        if not notification.read:
            notification.read = True
            self._session.flush()
        return True

    def mark_all_read(self, user_id: str) -> int:
        """Mark every unread notification for ``user_id`` read; return the count.

        Owner-scoped bulk UPDATE — only the caller's own unread rows are
        touched. Returns the number of rows flipped (0 when already all read).
        """
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.read.is_(False),
            )
            .values(read=True)
        )
        result = self._session.execute(stmt)
        self._session.flush()
        return int(result.rowcount or 0)


class PushTokenRepository:
    """UPSERT + owner-scoped lookup / invalidation for :class:`PushToken` rows.

    Backs out-of-app push delivery: the mobile client registers one Expo push
    token per install (keyed by the stable ``install_id``) and the
    job-completion path looks up an owner's *active* tokens to notify every
    signed-in device. Re-registration UPSERTS by ``install_id`` so a rotated
    token refreshes the single row instead of accumulating duplicates. All
    lookups/invalidations are owner-scoped so a caller can never read or flip
    another user's token by guessing its install id.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(
        self,
        install_id: str,
        token: str,
        platform: str = "",
        user_id: str | None = None,
    ) -> PushToken:
        """Insert or refresh the single row for ``install_id`` and return it.

        Keyed by the UNIQUE ``install_id`` so a re-registration (same install,
        rotated token) updates the existing row — token, platform, owner (when
        known) and ``last_seen`` — and re-activates it, rather than creating a
        duplicate. The row is always left ``is_active=True`` because a client that
        just minted and posted a token is, by definition, reachable again.
        """
        row = self._session.execute(
            select(PushToken).where(PushToken.install_id == install_id)
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if row is None:
            row = PushToken(
                install_id=install_id,
                token=token,
                platform=platform or "",
                user_id=user_id,
                is_active=True,
                last_seen=now,
            )
            self._session.add(row)
        else:
            row.token = token
            row.platform = platform or ""
            # Only ever *set* the owner (never clear it) so a token seen before
            # its account resolved adopts the owner once known.
            if user_id:
                row.user_id = user_id
            row.is_active = True
            row.last_seen = now
        self._session.flush()  # populate id / defaults without ending the txn
        return row

    def list_active_for_user(self, user_id: str) -> list[PushToken]:
        """Return the owner's active push tokens, most-recently-seen first."""
        if not user_id:
            return []
        stmt = (
            select(PushToken)
            .where(
                PushToken.user_id == user_id,
                PushToken.is_active.is_(True),
            )
            .order_by(PushToken.last_seen.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def deactivate_by_token(self, token: str) -> int:
        """Flip every active row carrying ``token`` inactive; return the count.

        Called when Expo reports a token as ``DeviceNotRegistered`` so a dead
        token is dropped from every future send (self-healing). Idempotent — a
        second call touches no rows.
        """
        if not token:
            return 0
        stmt = (
            update(PushToken)
            .where(PushToken.token == token, PushToken.is_active.is_(True))
            .values(is_active=False)
        )
        result = self._session.execute(stmt)
        self._session.flush()
        return int(result.rowcount or 0)

    def deactivate_for_install(self, install_id: str, user_id: str) -> bool:
        """Owner-scoped invalidation of one install's token; report if it existed.

        Returns ``False`` (touching no row) when the install is unknown or its
        row belongs to a different user, so a guessed install id can neither flip
        — nor confirm the existence of — another user's token. Flipping an
        already-inactive row is an idempotent success.
        """
        row = self._session.execute(
            select(PushToken).where(PushToken.install_id == install_id)
        ).scalar_one_or_none()
        if row is None or (row.user_id and user_id and row.user_id != user_id):
            return False
        if row.is_active:
            row.is_active = False
            self._session.flush()
        return True


#: Terminal ``ScheduledPublish.status`` values a due-claim / cancel must never
#: touch. Only a ``pending`` row is claimable by the runner or cancelable by its
#: owner; the rest are already resolved.
SCHEDULE_STATUS_PENDING = "pending"
SCHEDULE_STATUS_PUBLISHING = "publishing"
SCHEDULE_STATUS_PUBLISHED = "published"
SCHEDULE_STATUS_FAILED = "failed"
SCHEDULE_STATUS_CANCELED = "canceled"
# A publish was dispatched but at least one platform is still ingesting the
# video (Instagram container / TikTok publish_id). The publish-status sweep
# re-polls these rows until every platform resolves to published or failed.
SCHEDULE_STATUS_PROCESSING = "processing"


class ScheduledPublishRepository:
    """CRUD + due-claim / lifecycle transitions for :class:`ScheduledPublish`.

    Backs Scheduled Publishing: a creator queues a finished job to auto-publish
    at a future UTC time, a background runner claims due rows and publishes them,
    and the owner can list / cancel still-pending schedules. All owner-facing
    reads (``get_owned``, ``list_for_user``) and the ``cancel`` mutation are
    owner-scoped so a caller can never touch another user's schedule by guessing
    its id.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: str,
        job_id: str,
        platforms: list[str],
        scheduled_at,
        youtube_privacy_status: str = "private",
    ) -> ScheduledPublish:
        """Insert a new ``pending`` schedule and flush to obtain its id.

        The ``platforms`` list is copied (immutable update) so later mutation of
        the caller's list cannot bleed into the persisted row.
        """
        row = ScheduledPublish(
            user_id=user_id,
            job_id=job_id,
            platforms=list(platforms or []),
            scheduled_at=scheduled_at,
            youtube_privacy_status=(youtube_privacy_status or "private"),
            status=SCHEDULE_STATUS_PENDING,
            attempts=0,
            result={},
            error="",
        )
        self._session.add(row)
        self._session.flush()  # populate row.id without ending the transaction
        return row

    def get_owned(self, schedule_id: str, user_id: str) -> ScheduledPublish | None:
        """Return the schedule only when it exists *and* belongs to ``user_id``.

        Ownership is enforced here so a caller cannot read another user's
        schedule by guessing its id; a foreign or missing id returns ``None``.
        """
        row = self._session.get(ScheduledPublish, schedule_id)
        if row is None or row.user_id != user_id:
            return None
        return row

    def list_for_user(
        self, user_id: str, status: str | None = None
    ) -> list[ScheduledPublish]:
        """Return the user's schedules (optionally filtered by ``status``).

        Ordered by ``scheduled_at`` ascending so the soonest-due schedule leads.
        A blank ``status`` means "any status".
        """
        stmt = select(ScheduledPublish).where(ScheduledPublish.user_id == user_id)
        normalized = (status or "").strip()
        if normalized:
            stmt = stmt.where(ScheduledPublish.status == normalized)
        stmt = stmt.order_by(ScheduledPublish.scheduled_at.asc())
        return list(self._session.execute(stmt).scalars().all())

    def cancel(self, schedule_id: str, user_id: str) -> bool:
        """Cancel a still-``pending`` schedule owned by ``user_id``.

        Returns ``True`` when a pending row was flipped to ``canceled``. Returns
        ``False`` (without changing anything) when the schedule does not exist,
        belongs to a different user, or is no longer pending (already publishing
        / published / failed / canceled) — so a schedule the runner has already
        claimed can never be canceled out from under it.

        Uses a **guarded** ``UPDATE ... WHERE id=:id AND user_id=:user_id AND
        status='pending'`` (the same atomic pattern :meth:`claim_due` uses)
        rather than an ORM read-modify-write. A stale identity-map read would
        still report ``status='pending'`` for a row the due-runner has already
        committed to ``publishing`` in another session — a read-modify-write
        would then blindly overwrite the claim with ``canceled`` (a false
        cancellation). The status predicate lives in the UPDATE itself, so the
        cancel matches zero rows (rowcount == 0 → ``False``) once the runner has
        claimed the row, no matter what the session cache holds.
        """
        stmt = (
            update(ScheduledPublish)
            .where(
                ScheduledPublish.id == schedule_id,
                ScheduledPublish.user_id == user_id,
                ScheduledPublish.status == SCHEDULE_STATUS_PENDING,
            )
            .values(status=SCHEDULE_STATUS_CANCELED)
        )
        result = self._session.execute(stmt)
        self._session.flush()
        return (result.rowcount or 0) == 1

    def get_for_user(
        self, schedule_id: str, user_id: str
    ) -> ScheduledPublish | None:
        """Return the schedule only when it exists *and* belongs to ``user_id``.

        Owner-scoped alias of :meth:`get_owned` used by the publishing-calendar
        read / reschedule path: a foreign or missing id returns ``None`` so a
        caller can never resolve another user's schedule by guessing its id.
        """
        return self.get_owned(schedule_id, user_id)

    def list_in_range(
        self,
        user_id: str,
        start_utc,
        end_utc,
        statuses: list[str] | None = None,
    ) -> list[ScheduledPublish]:
        """Return the caller's schedules whose ``scheduled_at`` is in [start, end].

        Owner-scoped (filters ``ScheduledPublish.user_id == user_id``) and
        **inclusive** on both bounds, ordered by ``scheduled_at`` ascending so
        the calendar renders soonest-first. When ``statuses`` is given only rows
        whose status is in that set are returned (blank entries ignored); a
        falsy / empty ``statuses`` means "any status". A row outside the window
        or owned by another user is never returned.
        """
        stmt = select(ScheduledPublish).where(
            ScheduledPublish.user_id == user_id,
            ScheduledPublish.scheduled_at >= start_utc,
            ScheduledPublish.scheduled_at <= end_utc,
        )
        normalized = [s for s in (statuses or []) if (s or "").strip()]
        if normalized:
            stmt = stmt.where(ScheduledPublish.status.in_(normalized))
        stmt = stmt.order_by(ScheduledPublish.scheduled_at.asc())
        return list(self._session.execute(stmt).scalars().all())

    def reschedule(
        self, schedule_id: str, user_id: str, new_scheduled_at
    ) -> ScheduledPublish | None:
        """Move a still-``pending`` schedule to ``new_scheduled_at``.

        Returns the updated row on success, or ``None`` (touching **nothing**)
        when the schedule does not exist, belongs to another user, or is no
        longer pending (already publishing / published / failed / canceled) — so
        a schedule the due-runner has already claimed can never be moved out from
        under it.

        Uses the same **guarded** ``UPDATE ... WHERE id=:id AND user_id=:user_id
        AND status='pending'`` pattern as :meth:`cancel` / :meth:`claim_due`
        rather than an ORM read-modify-write: the status predicate lives in the
        UPDATE itself, so a stale identity-map read can never cause a move of a
        row another session has already committed to ``publishing`` (rowcount ==
        0 → ``None``). On success the row is refreshed so the returned object
        reflects the persisted ``new_scheduled_at``.
        """
        stmt = (
            update(ScheduledPublish)
            .where(
                ScheduledPublish.id == schedule_id,
                ScheduledPublish.user_id == user_id,
                ScheduledPublish.status == SCHEDULE_STATUS_PENDING,
            )
            .values(scheduled_at=new_scheduled_at)
        )
        result = self._session.execute(stmt)
        self._session.flush()
        if (result.rowcount or 0) != 1:
            return None
        row = self._session.get(ScheduledPublish, schedule_id)
        if row is not None:
            self._session.refresh(row)
        return row

    def claim_due(self, now, limit: int = 20) -> list[ScheduledPublish]:
        """Atomically claim due ``pending`` schedules, flipping them to
        ``publishing`` and returning them.

        A due row is ``pending`` with ``scheduled_at <= now``. Each candidate is
        claimed with a **guarded** ``UPDATE ... WHERE id=:id AND
        status='pending'``: whichever runner's UPDATE commits first flips the row
        to ``publishing`` (rowcount == 1 → claimed); a second concurrent runner's
        identical UPDATE then matches zero rows (rowcount == 0 → skipped), so the
        same schedule can never be claimed twice. On SQLite (tests) there are no
        row locks, but the single-writer model plus the guarded predicate keep
        the claim correct — it degrades gracefully.

        Returns the freshly-claimed rows, soonest-due first. A second call with
        no newly-due rows returns ``[]`` (idempotent).
        """
        candidate_stmt = (
            select(ScheduledPublish.id)
            .where(
                ScheduledPublish.status == SCHEDULE_STATUS_PENDING,
                ScheduledPublish.scheduled_at <= now,
            )
            .order_by(ScheduledPublish.scheduled_at.asc())
            .limit(max(1, limit))
        )
        candidate_ids = list(
            self._session.execute(candidate_stmt).scalars().all()
        )

        claimed_ids: list[str] = []
        for schedule_id in candidate_ids:
            guarded = (
                update(ScheduledPublish)
                .where(
                    ScheduledPublish.id == schedule_id,
                    ScheduledPublish.status == SCHEDULE_STATUS_PENDING,
                    ScheduledPublish.scheduled_at <= now,
                )
                .values(status=SCHEDULE_STATUS_PUBLISHING)
            )
            result = self._session.execute(guarded)
            if (result.rowcount or 0) == 1:
                claimed_ids.append(schedule_id)
        self._session.flush()

        if not claimed_ids:
            return []

        rows_stmt = (
            select(ScheduledPublish)
            .where(ScheduledPublish.id.in_(claimed_ids))
            .order_by(ScheduledPublish.scheduled_at.asc())
        )
        return list(self._session.execute(rows_stmt).scalars().all())

    def mark_published(
        self, schedule_id: str, result: dict | None
    ) -> ScheduledPublish | None:
        """Mark a schedule ``published`` with its publish ``result`` dict.

        The ``result`` mapping is copied (immutable update) so later mutation of
        the caller's dict cannot bleed into the persisted row. Clears any prior
        error. Returns the row, or ``None`` when it does not exist.
        """
        row = self._session.get(ScheduledPublish, schedule_id)
        if row is None:
            return None
        row.status = SCHEDULE_STATUS_PUBLISHED
        row.result = dict(result or {})
        row.error = ""
        self._session.flush()
        return row

    def mark_processing(
        self, schedule_id: str, result: dict | None
    ) -> ScheduledPublish | None:
        """Mark a schedule ``processing`` (a platform is still ingesting).

        ``result`` carries the per-platform publish outcomes, including the
        platform ids the publish-status sweep needs to resume. Copied on write.
        """
        row = self._session.get(ScheduledPublish, schedule_id)
        if row is None:
            return None
        row.status = SCHEDULE_STATUS_PROCESSING
        row.result = dict(result or {})
        row.error = ""
        self._session.flush()
        return row

    def create_processing(
        self,
        *,
        user_id: str,
        job_id: str,
        platforms: list[str],
        result: dict,
        scheduled_at,
    ) -> ScheduledPublish:
        """Track an immediate ("Publish now") post a platform is still ingesting.

        Stored as a ``processing`` schedule so the same publish-status sweep that
        resolves scheduled posts also finishes immediate ones, and the creator
        sees it on the calendar until it is live.
        """
        row = ScheduledPublish(
            user_id=user_id,
            job_id=job_id,
            platforms=list(platforms or []),
            scheduled_at=scheduled_at,
            status=SCHEDULE_STATUS_PROCESSING,
            attempts=0,
            result=dict(result or {}),
            error="",
        )
        self._session.add(row)
        self._session.flush()
        return row

    def claim_processing(self, limit: int = 20) -> list[ScheduledPublish]:
        """Claim ``processing`` rows for one re-poll pass (guarded flip).

        Each row is flipped ``processing`` -> ``publishing`` with the status
        predicate inside the UPDATE, so two overlapping sweeps can never resume
        (and double-publish) the same platform container.
        """
        candidate_stmt = (
            select(ScheduledPublish.id)
            .where(ScheduledPublish.status == SCHEDULE_STATUS_PROCESSING)
            .order_by(ScheduledPublish.updated_at.asc())
            .limit(max(1, limit))
        )
        candidate_ids = list(self._session.execute(candidate_stmt).scalars().all())
        claimed_ids: list[str] = []
        for schedule_id in candidate_ids:
            guarded = (
                update(ScheduledPublish)
                .where(
                    ScheduledPublish.id == schedule_id,
                    ScheduledPublish.status == SCHEDULE_STATUS_PROCESSING,
                )
                .values(status=SCHEDULE_STATUS_PUBLISHING)
            )
            if (self._session.execute(guarded).rowcount or 0) == 1:
                claimed_ids.append(schedule_id)
        self._session.flush()
        if not claimed_ids:
            return []
        rows_stmt = select(ScheduledPublish).where(
            ScheduledPublish.id.in_(claimed_ids)
        )
        return list(self._session.execute(rows_stmt).scalars().all())

    def mark_failed(
        self, schedule_id: str, error: str
    ) -> ScheduledPublish | None:
        """Mark a schedule ``failed``, incrementing ``attempts`` by one.

        A blank/``None`` error is defaulted to a non-empty message so a failure
        always records a resolvable root cause. Returns the row, or ``None``
        when it does not exist.
        """
        row = self._session.get(ScheduledPublish, schedule_id)
        if row is None:
            return None
        row.status = SCHEDULE_STATUS_FAILED
        row.attempts = int(row.attempts or 0) + 1
        row.error = str(error or "").strip() or "unknown publish error"
        self._session.flush()
        return row


#: The roles a :class:`WorkspaceMember` may hold, most privileged first.
#: ``owner``  — the creator; full control, cannot be removed/demoted casually.
#: ``admin``  — can invite + remove members and change roles.
#: ``member`` — can view + leave only.
WORKSPACE_ROLE_OWNER = "owner"
WORKSPACE_ROLE_ADMIN = "admin"
WORKSPACE_ROLE_MEMBER = "member"
WORKSPACE_ROLES: frozenset[str] = frozenset(
    {WORKSPACE_ROLE_OWNER, WORKSPACE_ROLE_ADMIN, WORKSPACE_ROLE_MEMBER}
)


class WorkspaceRepository:
    """CRUD + membership management for :class:`Workspace` / :class:`WorkspaceMember`.

    Team Workspaces is an **additive** membership layer: creating a workspace
    and adding members never touches the existing per-user job/credit ownership
    model. A workspace always has exactly one canonical owner (denormalized on
    ``Workspace.owner_id`` and mirrored as a ``role='owner'`` membership row
    inserted by :meth:`create_workspace`).

    Role authorization (who may invite/remove/change roles) is enforced by the
    caller/controller using :meth:`get_membership`; this repository is the
    persistence layer and validates only the role *value* itself.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _normalize_role(role: str) -> str:
        """Validate + normalize a role string to one of :data:`WORKSPACE_ROLES`.

        Raises ``ValueError`` on an unknown / blank role so an invalid value can
        never be persisted (the DB column is a plain ``String`` with no CHECK).
        """
        normalized = (role or "").strip().lower()
        if normalized not in WORKSPACE_ROLES:
            raise ValueError(
                f"invalid workspace role: {role!r} "
                f"(expected one of {sorted(WORKSPACE_ROLES)})"
            )
        return normalized

    def create_workspace(self, name: str, owner_id: str) -> Workspace:
        """Create a workspace and insert its owner as a ``role='owner'`` member.

        The workspace and the owner's membership row are inserted in a single
        flush so a workspace is never left without its owner membership. The
        ``name`` is coerced to ``str`` (never SQL ``NULL``). Returns the
        persisted, id-populated :class:`Workspace`.
        """
        workspace = Workspace(name=str(name or ""), owner_id=owner_id)
        self._session.add(workspace)
        self._session.flush()  # populate workspace.id without ending the txn

        owner_member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=owner_id,
            role=WORKSPACE_ROLE_OWNER,
        )
        self._session.add(owner_member)
        self._session.flush()
        return workspace

    def get(self, workspace_id: str) -> Workspace | None:
        """Return a workspace by id, or ``None`` if it does not exist."""
        return self._session.get(Workspace, workspace_id)

    def list_for_user(self, user_id: str) -> list[Workspace]:
        """Return every workspace ``user_id`` is a member of, newest first.

        Scoped strictly to the user's memberships — a workspace the user neither
        owns nor was invited to is never returned. Joins ``workspaces`` to the
        caller's ``workspace_members`` rows so ownership is derived from actual
        membership (the owner always has a ``role='owner'`` member row).
        """
        stmt = (
            select(Workspace)
            .join(
                WorkspaceMember,
                WorkspaceMember.workspace_id == Workspace.id,
            )
            .where(WorkspaceMember.user_id == user_id)
            .order_by(Workspace.created_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_membership(
        self, workspace_id: str, user_id: str
    ) -> WorkspaceMember | None:
        """Return the caller's membership of a workspace, or ``None``.

        This is the authorization primitive: a ``None`` result means the user is
        not a member (so may neither view nor act on the workspace), while a
        non-``None`` result carries the ``role`` a controller checks before
        allowing invite/remove/role-change operations.
        """
        stmt = (
            select(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def add_member(
        self, workspace_id: str, user_id: str, role: str
    ) -> WorkspaceMember:
        """Add a user to a workspace with ``role``; return the membership row.

        The role is validated via :meth:`_normalize_role` (raising
        ``ValueError`` on an unknown value). Raises ``ValueError`` when the user
        is already a member — the ``(workspace_id, user_id)`` UNIQUE constraint
        guarantees at-most-one membership, and this pre-check turns a duplicate
        invite into a clear error the controller can surface as a 409 rather
        than an opaque ``IntegrityError``.
        """
        normalized = self._normalize_role(role)
        existing = self.get_membership(workspace_id, user_id)
        if existing is not None:
            raise ValueError(
                f"user {user_id} is already a member of workspace {workspace_id}"
            )
        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user_id,
            role=normalized,
        )
        self._session.add(member)
        self._session.flush()
        return member

    def list_members(self, workspace_id: str) -> list[WorkspaceMember]:
        """Return all members of a workspace, oldest first (owner leads)."""
        stmt = (
            select(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def set_role(
        self, workspace_id: str, user_id: str, role: str
    ) -> WorkspaceMember | None:
        """Change a member's role; return the updated row or ``None``.

        Returns ``None`` (without changing anything) when the user is not a
        member of the workspace, so a role change can never create a phantom
        membership. The new role is validated via :meth:`_normalize_role`.
        """
        normalized = self._normalize_role(role)
        member = self.get_membership(workspace_id, user_id)
        if member is None:
            return None
        member.role = normalized
        self._session.flush()
        return member

    def remove_member(self, workspace_id: str, user_id: str) -> bool:
        """Remove a user from a workspace; return whether a row was removed.

        Returns ``False`` (without deleting) when the user is not a member, so a
        no-op removal is distinguishable from a real one. This also backs a
        member "leaving" the workspace (a self-removal).
        """
        member = self.get_membership(workspace_id, user_id)
        if member is None:
            return False
        self._session.delete(member)
        self._session.flush()
        return True


class UserApiKeyRepository:
    """CRUD + resolution for per-user :class:`UserApiKey` rows (PUBLIC API KEYS).

    Backs personal programmatic access to ``/api/v1``: a user mints a key
    (``x-api-key``), whose SHA-256 digest is stored here and matched back to the
    owning user at request time — extending the existing single
    ``User.api_key_hash`` resolution in ``jobs.py``.

    SECURITY: this layer only ever handles the SHA-256 **digest** of a key, never
    the raw secret. Callers hash the raw key (revealed once at creation) before
    it reaches :meth:`create`, and hash a presented key before :meth:`get_by_hash`.

    Ownership: every owner-facing mutation (:meth:`revoke`) is scoped to
    ``user_id`` so a caller can never revoke another user's key by guessing its
    id. Resolution (:meth:`get_by_hash`) deliberately excludes revoked keys so a
    revoked key can never authenticate.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, user_id: str, name: str, key_hash: str, prefix: str
    ) -> UserApiKey:
        """Insert a new (active) API key row and flush to obtain its id.

        ``key_hash`` is the caller-computed SHA-256 hex digest of the raw key —
        the raw key itself is never passed in or stored. ``name``/``prefix`` are
        coerced to ``str`` (never SQL ``NULL``); ``prefix`` is a non-secret
        display label. Raises ``ValueError`` on a blank ``user_id`` or
        ``key_hash`` so an unusable row (unattributable / unresolvable) can never
        be persisted. A duplicate ``key_hash`` violates the UNIQUE constraint and
        surfaces as an ``IntegrityError`` on flush.
        """
        normalized_user = (user_id or "").strip()
        if not normalized_user:
            raise ValueError("user_id must be a non-empty string")
        normalized_hash = (key_hash or "").strip()
        if not normalized_hash:
            raise ValueError("key_hash must be a non-empty string")

        api_key = UserApiKey(
            user_id=normalized_user,
            name=str(name or ""),
            key_hash=normalized_hash,
            prefix=str(prefix or ""),
            revoked=False,
        )
        self._session.add(api_key)
        self._session.flush()  # populate api_key.id without ending the transaction
        return api_key

    def list_for_user(self, user_id: str) -> list[UserApiKey]:
        """Return ALL of the user's keys (active *and* revoked), newest first.

        Revoked keys are intentionally **included** (not filtered out) so the UI
        can render a full history with each row's ``revoked`` flag and
        ``last_used_at`` — a revoked key stays visible for audit/display but can
        never authenticate (see :meth:`get_by_hash`). Owner-scoped: only rows
        belonging to ``user_id`` are returned.
        """
        stmt = (
            select(UserApiKey)
            .where(UserApiKey.user_id == user_id)
            .order_by(UserApiKey.created_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_by_hash(self, key_hash: str) -> UserApiKey | None:
        """Resolve a presented key's digest to its LIVE (non-revoked) row.

        Only a non-revoked row matches so a revoked key can never authenticate.
        A blank/whitespace-only digest never matches (returns ``None``) so an
        empty header can never sweep up a row. This is the resolution primitive
        the ``x-api-key`` auth path uses to map a key to its owning user.
        """
        normalized = (key_hash or "").strip()
        if not normalized:
            return None
        stmt = (
            select(UserApiKey)
            .where(
                UserApiKey.key_hash == normalized,
                UserApiKey.revoked.is_(False),
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def revoke(self, key_id: str, user_id: str) -> bool:
        """Soft-revoke a key owned by ``user_id``; return whether a row changed.

        Owner-scoped guarded ``UPDATE ... WHERE id AND user_id AND NOT revoked``:
        returns ``True`` only when an active row belonging to the caller was
        flipped to ``revoked``. Returns ``False`` (without touching any row) when
        the key does not exist, belongs to a different user, or is already
        revoked — so a caller can never revoke another user's key by guessing its
        id, and a double-revoke is a harmless no-op. The row is retained (soft
        delete) for audit/display.
        """
        stmt = (
            update(UserApiKey)
            .where(
                UserApiKey.id == key_id,
                UserApiKey.user_id == user_id,
                UserApiKey.revoked.is_(False),
            )
            .values(revoked=True)
        )
        result = self._session.execute(stmt)
        self._session.flush()
        return (result.rowcount or 0) == 1

    def touch_last_used(self, key_id: str) -> None:
        """Best-effort stamp ``last_used_at`` to now for a key (never raises).

        Called on a successful ``x-api-key`` authentication to power a "last
        used" display. Deliberately best-effort: a missing key is a silent no-op
        and any failure is swallowed with a log line so a telemetry write can
        never break the authenticated request it decorates.
        """
        try:
            key = self._session.get(UserApiKey, key_id)
            if key is None:
                return
            key.last_used_at = datetime.now(timezone.utc)
            self._session.flush()
        except Exception as exc:  # noqa: BLE001 - best-effort telemetry write
            logger.warning(f"touch_last_used failed for api key {key_id}: {exc}")


class ApiKeyUsageRepository:
    """Row-locked monthly usage counter for :class:`ApiKeyUsage` (per-key quota).

    Backs the POWER-USER TIER monthly quota: :meth:`increment` atomically bumps —
    and returns — the request count for one key's current calendar month, and
    :meth:`get_month` reads it back. Exactly one row exists per
    ``(api_key_id, period_ym)`` (a composite UNIQUE constraint), so an increment
    is an UPSERT: it updates the existing month row in place (never accumulating
    duplicates) and a new month inserts a fresh row.

    Concurrency mirrors the repository's established ``_locked_*`` idiom — the
    existing month row is taken ``FOR UPDATE`` so concurrent increments serialize
    and the count stays monotonic; SQLite (tests) has no row locks so it degrades
    to an unlocked read-modify-write, and any other backend locking failure
    propagates unchanged.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def increment(
        self, api_key_id: str, period_ym: str, amount: int = 1
    ) -> int:
        """Atomically add ``amount`` to a key's month counter; return the new count.

        Upserts the single ``(api_key_id, period_ym)`` row: the existing row is
        locked ``FOR UPDATE`` and its ``count`` bumped, or a fresh row is inserted
        when this is the first request of the month. ``amount`` is floored
        non-negative so a bad caller can never decrement the counter. Raises
        ``ValueError`` on a blank ``api_key_id`` / ``period_ym`` so an
        unattributable counter row can never be persisted. Returns the count
        after the increment.
        """
        key = (api_key_id or "").strip()
        if not key:
            raise ValueError("api_key_id must be a non-empty string")
        period = (period_ym or "").strip()
        if not period:
            raise ValueError("period_ym must be a non-empty string")
        delta = max(0, int(amount))

        row = self._locked_usage(key, period)
        if row is not None:
            row.count = int(row.count or 0) + delta
            self._session.flush()
            return int(row.count)

        # First request of the month: INSERT a fresh counter row. Two requests can
        # race here as the month's first writers — ``FOR UPDATE`` cannot lock a
        # not-yet-existing row, so both would INSERT and the second flush would
        # violate the ``(api_key_id, period_ym)`` UNIQUE constraint. Guard the
        # INSERT with a SAVEPOINT so that collision rolls back ONLY the failed
        # insert (never aborting the caller's outer transaction); then re-read the
        # now-existing row ``FOR UPDATE`` and bump it, keeping the count monotonic.
        try:
            with self._session.begin_nested():
                row = ApiKeyUsage(api_key_id=key, period_ym=period, count=delta)
                self._session.add(row)
                self._session.flush()
            return int(row.count)
        except IntegrityError:
            row = self._locked_usage(key, period)
            if row is None:
                raise
            row.count = int(row.count or 0) + delta
            self._session.flush()
            return int(row.count)

    def get_month(self, api_key_id: str, period_ym: str) -> int:
        """Return a key's request count for ``period_ym`` (0 when no row exists).

        A blank ``api_key_id`` / ``period_ym`` never matches (returns 0) so an
        empty identifier can never sweep up an unrelated counter.
        """
        key = (api_key_id or "").strip()
        period = (period_ym or "").strip()
        if not key or not period:
            return 0
        stmt = (
            select(ApiKeyUsage.count)
            .where(
                ApiKeyUsage.api_key_id == key,
                ApiKeyUsage.period_ym == period,
            )
            .limit(1)
        )
        current = self._session.execute(stmt).scalars().first()
        return int(current) if current is not None else 0

    def _locked_usage(self, api_key_id: str, period_ym: str) -> ApiKeyUsage | None:
        """SELECT ... FOR UPDATE the ``(key, month)`` counter row to serialize writers.

        Falls back to a plain read only when the backend does not support row
        locking (SQLite in tests raises ``NotSupportedError``); any other backend
        error is a real failure and propagates unchanged.
        """
        stmt = (
            select(ApiKeyUsage)
            .where(
                ApiKeyUsage.api_key_id == api_key_id,
                ApiKeyUsage.period_ym == period_ym,
            )
            .limit(1)
        )
        try:
            return self._session.execute(stmt.with_for_update()).scalars().first()
        except NotSupportedError:
            if self._session.get_bind().dialect.name != "sqlite":
                raise
            # SQLite (tests): no row locks — degrade to an unlocked read.
            return self._session.execute(stmt).scalars().first()


#: Inclusive star bounds for a :class:`TemplateRating`. A rating outside this
#: range is meaningless; the service layer validates against these before an
#: upsert and the repository clamps defensively so a stray value can never
#: corrupt the aggregate.
TEMPLATE_RATING_MIN_STARS = 1
TEMPLATE_RATING_MAX_STARS = 5

#: Hard cap on the page size a single marketplace browse may return, so an
#: untrusted ``limit`` can never trigger an unbounded scan.
MARKETPLACE_MAX_LIMIT = 100
MARKETPLACE_DEFAULT_LIMIT = 20

#: Recognized browse sort orders. ``top`` ranks by rating then recency;
#: ``new`` is pure recency; ``clones`` ranks by clone_count then recency;
#: ``proven`` ranks by the real-world win-score of the reels made from a
#: listing's clones (see :func:`app.services.marketplace.proven_ranking`). The
#: win-score is a Python-side aggregate of :class:`JobPerformance` rows and so
#: cannot be expressed as a SQL ``ORDER BY``; at the repository level ``proven``
#: therefore reuses the ``top`` (rating/recency) ordering to build a bounded,
#: deterministic candidate page which the service layer then re-ranks by
#: win-score. Unknown sorts still fall back to ``top``.
MARKETPLACE_SORT_TOP = "top"
MARKETPLACE_SORT_NEW = "new"
MARKETPLACE_SORT_CLONES = "clones"
MARKETPLACE_SORT_PROVEN = "proven"
#: Ranks by ``remix_count`` (how many published listings descend from this one in
#: the remix tree) then recency, with ``id`` as a final deterministic tie-break.
MARKETPLACE_SORT_REMIXED = "most_remixed"
MARKETPLACE_SORTS: frozenset[str] = frozenset(
    {
        MARKETPLACE_SORT_TOP,
        MARKETPLACE_SORT_NEW,
        MARKETPLACE_SORT_CLONES,
        MARKETPLACE_SORT_PROVEN,
        MARKETPLACE_SORT_REMIXED,
    }
)


def _clamp_stars(stars: object) -> int:
    """Coerce/clamp a star value into ``[1, 5]`` (defaults to the min on garbage)."""
    try:
        value = int(stars)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return TEMPLATE_RATING_MIN_STARS
    return max(TEMPLATE_RATING_MIN_STARS, min(TEMPLATE_RATING_MAX_STARS, value))


class MarketplaceRepository:
    """CRUD + browse for :class:`MarketplaceTemplate` public listings.

    Backs the Template Marketplace: a creator publishes an immutable snapshot of
    a private template, others browse/search + clone it, and the author (only)
    may soft-unpublish it. Publishing copies the caller-supplied content
    (``params`` / ``tags`` are copied into fresh JSON blobs) so a later edit to
    the author's private template never mutates the public listing. All
    owner-facing mutations are scoped to ``author_user_id`` so a caller can never
    edit/unpublish another creator's listing by guessing its id.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def publish(
        self,
        *,
        author_user_id: str,
        title: str,
        description: str = "",
        prompt: str = "",
        params: dict | None = None,
        tags: list | None = None,
        language: str = "en",
        layout: str = "",
        published: bool = True,
        parent_template_id: str | None = None,
    ) -> MarketplaceTemplate:
        """Insert a new public listing (an immutable content snapshot).

        ``params`` and ``tags`` are copied into fresh JSON blobs (immutable
        update) so later mutation of the caller's dict/list — or of the author's
        private template the snapshot came from — cannot bleed into the persisted
        row. ``parent_template_id`` records REMIX-TREE provenance when the listing
        descends from another marketplace listing (see
        :attr:`MarketplaceTemplate.parent_template_id`); it is ``None`` for an
        original publish. Returns the id-populated listing.
        """
        listing = MarketplaceTemplate(
            author_user_id=author_user_id,
            title=str(title or ""),
            description=str(description or ""),
            prompt=str(prompt or ""),
            params=dict(params or {}),
            tags=list(tags or []),
            language=str(language or "en")[:20],
            layout=str(layout or "")[:40],
            published=bool(published),
            parent_template_id=(parent_template_id or None),
        )
        self._session.add(listing)
        self._session.flush()  # populate listing.id without ending the transaction
        return listing

    def get(self, template_id: str) -> MarketplaceTemplate | None:
        """Return a listing by id, or ``None`` if it does not exist."""
        return self._session.get(MarketplaceTemplate, template_id)

    def list(
        self,
        *,
        query: str = "",
        tag: str = "",
        language: str = "",
        sort: str = MARKETPLACE_SORT_TOP,
        limit: int = MARKETPLACE_DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[MarketplaceTemplate]:
        """Return published listings matching the filters, paginated + sorted.

        Only ``published`` rows are ever returned. ``query`` does a
        case-insensitive substring match on title OR description; ``tag`` matches
        a single membership of the JSON ``tags`` list; ``language`` filters by
        persona code. ``sort`` is one of :data:`MARKETPLACE_SORTS` (``top`` =
        rating then recency, ``new`` = recency, ``clones`` = clone_count then
        recency, ``proven`` = the ``top`` ordering here — the win-score re-rank
        happens in the service layer). ``limit`` is clamped to ``[1, 100]`` and
        ``offset`` to ``>= 0`` so an untrusted page request can never trigger an
        unbounded scan.
        """
        stmt = select(MarketplaceTemplate).where(
            MarketplaceTemplate.published.is_(True)
        )

        q = (query or "").strip().lower()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    func.lower(MarketplaceTemplate.title).like(like),
                    func.lower(MarketplaceTemplate.description).like(like),
                )
            )

        tag_token = (tag or "").strip().lower()
        if tag_token:
            # Portable JSON-list membership: match the serialized list text for a
            # quoted token (e.g. '..."saas"...'). Works on both SQLite (JSON is
            # TEXT) and Postgres (CAST(json AS TEXT)) without loading rows into
            # Python, so tag search stays index-friendly and bounded.
            tag_like = f'%"{tag_token}"%'
            stmt = stmt.where(
                func.lower(cast(MarketplaceTemplate.tags, String)).like(tag_like)
            )

        lang = (language or "").strip().lower()
        if lang:
            stmt = stmt.where(MarketplaceTemplate.language == lang)

        normalized_sort = (sort or "").strip().lower()
        if normalized_sort == MARKETPLACE_SORT_NEW:
            stmt = stmt.order_by(MarketplaceTemplate.created_at.desc())
        elif normalized_sort == MARKETPLACE_SORT_CLONES:
            stmt = stmt.order_by(
                MarketplaceTemplate.clone_count.desc(),
                MarketplaceTemplate.created_at.desc(),
            )
        elif normalized_sort == MARKETPLACE_SORT_REMIXED:
            # "most_remixed" — most-forked first, then recency, with id as a final
            # deterministic tie-break so the ordering is stable when two listings
            # share the same remix_count and created_at (e.g. in tests).
            stmt = stmt.order_by(
                MarketplaceTemplate.remix_count.desc(),
                MarketplaceTemplate.created_at.desc(),
                MarketplaceTemplate.id.asc(),
            )
        else:  # default: "top" — rating, then vote volume, then recency
            stmt = stmt.order_by(
                MarketplaceTemplate.rating_avg.desc(),
                MarketplaceTemplate.rating_count.desc(),
                MarketplaceTemplate.created_at.desc(),
            )

        safe_limit = max(1, min(int(limit or 0), MARKETPLACE_MAX_LIMIT))
        safe_offset = max(0, int(offset or 0))
        stmt = stmt.limit(safe_limit).offset(safe_offset)
        return list(self._session.execute(stmt).scalars().all())

    def list_for_author(self, author_user_id: str) -> list[MarketplaceTemplate]:
        """Return every listing (published *and* unpublished) an author owns.

        Owner-scoped: only rows belonging to ``author_user_id`` are returned so a
        creator sees their full catalog (including soft-hidden listings) newest
        first, while a stranger never receives them.
        """
        stmt = (
            select(MarketplaceTemplate)
            .where(MarketplaceTemplate.author_user_id == author_user_id)
            .order_by(MarketplaceTemplate.created_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def unpublish(self, template_id: str, author_user_id: str) -> bool:
        """Soft-unpublish a listing owned by ``author_user_id``.

        Owner-scoped guarded ``UPDATE ... WHERE id AND author_user_id AND
        published``: returns ``True`` only when a *published* row belonging to the
        caller was flipped to unpublished. Returns ``False`` (without touching any
        row) when the listing does not exist, belongs to a different author, or is
        already unpublished — so a caller can never unpublish another creator's
        listing by guessing its id, and a double-unpublish is a harmless no-op.
        The row is retained (soft hide) so its clones/ratings survive.
        """
        stmt = (
            update(MarketplaceTemplate)
            .where(
                MarketplaceTemplate.id == template_id,
                MarketplaceTemplate.author_user_id == author_user_id,
                MarketplaceTemplate.published.is_(True),
            )
            .values(published=False)
        )
        result = self._session.execute(stmt)
        self._session.flush()
        if (result.rowcount or 0) != 1:
            return False

        # Keep the parent's ``remix_count`` consistent with its count of LIVE
        # (published) children: this row just left the public remix tree, so
        # decrement its parent's counter (mirroring the ++ on publish). Without
        # this the ``most_remixed`` sort would rank a parent above the number of
        # visible children it actually has. Guarded ``remix_count > 0`` UPDATE so
        # the counter floors at 0 and a double-unpublish (already handled by the
        # rowcount check above) could never underflow it.
        row = self._session.get(MarketplaceTemplate, template_id)
        parent_id = getattr(row, "parent_template_id", None) if row else None
        if parent_id:
            self._session.execute(
                update(MarketplaceTemplate)
                .where(
                    MarketplaceTemplate.id == parent_id,
                    MarketplaceTemplate.remix_count > 0,
                )
                .values(remix_count=MarketplaceTemplate.remix_count - 1)
            )
            self._session.flush()
        return True

    def increment_clone(self, template_id: str) -> MarketplaceTemplate | None:
        """Atomically bump a listing's ``clone_count`` by one; return the row.

        Uses an in-place ``clone_count = clone_count + 1`` UPDATE (never a
        read-modify-write) so concurrent clones cannot lose an increment. Returns
        the refreshed listing, or ``None`` when it does not exist.
        """
        stmt = (
            update(MarketplaceTemplate)
            .where(MarketplaceTemplate.id == template_id)
            .values(clone_count=MarketplaceTemplate.clone_count + 1)
        )
        result = self._session.execute(stmt)
        self._session.flush()
        if (result.rowcount or 0) == 0:
            return None
        listing = self._session.get(MarketplaceTemplate, template_id)
        if listing is not None:
            self._session.refresh(listing)
        return listing

    def increment_remix(self, template_id: str) -> MarketplaceTemplate | None:
        """Atomically bump a parent listing's ``remix_count`` by one; return it.

        Called once when a listing that descends from this one is published (a
        "remix"). Uses an in-place ``remix_count = remix_count + 1`` UPDATE (never
        a read-modify-write) so concurrent remixes cannot lose an increment.
        Mirrors :meth:`increment_clone`. Returns the refreshed listing, or ``None``
        when it does not exist (a blank id never matches).
        """
        normalized = (template_id or "").strip()
        if not normalized:
            return None
        stmt = (
            update(MarketplaceTemplate)
            .where(MarketplaceTemplate.id == normalized)
            .values(remix_count=MarketplaceTemplate.remix_count + 1)
        )
        result = self._session.execute(stmt)
        self._session.flush()
        if (result.rowcount or 0) == 0:
            return None
        listing = self._session.get(MarketplaceTemplate, normalized)
        if listing is not None:
            self._session.refresh(listing)
        return listing

    def get_children(
        self, template_id: str, limit: int = MARKETPLACE_MAX_LIMIT
    ) -> list[MarketplaceTemplate]:
        """Return the PUBLISHED listings that directly remix ``template_id``.

        The direct children in the remix tree: rows whose ``parent_template_id``
        equals this listing. Only ``published`` children are returned (a
        soft-unpublished remix is hidden from the public lineage view, mirroring
        the ``published``-only :meth:`list` browse invariant), newest first with
        ``id`` as a final deterministic tie-break. ``limit`` is clamped to
        ``[1, 100]`` so an untrusted request can never trigger an unbounded scan;
        a blank ``template_id`` yields ``[]``.
        """
        normalized = (template_id or "").strip()
        if not normalized:
            return []
        safe_limit = max(1, min(int(limit or 0), MARKETPLACE_MAX_LIMIT))
        stmt = (
            select(MarketplaceTemplate)
            .where(
                MarketplaceTemplate.parent_template_id == normalized,
                MarketplaceTemplate.published.is_(True),
            )
            .order_by(
                MarketplaceTemplate.created_at.desc(),
                MarketplaceTemplate.id.asc(),
            )
            .limit(safe_limit)
        )
        return list(self._session.execute(stmt).scalars().all())

    # ------------------------------------------------------------------ #
    # Author reputation aggregates (Creator Profiles + Leaderboards)
    # ------------------------------------------------------------------ #
    # These are OWNER-AGNOSTIC, PUBLIC aggregates over a creator's *published*
    # listings only — a soft-unpublished listing never counts toward their public
    # reputation. They expose only counts/averages (published listings, clones
    # received, weighted rating) — never any private/financial field.
    def author_aggregates(self, author_user_id: str) -> dict[str, float]:
        """Return one creator's public listing aggregates.

        Aggregates over the author's ``published`` listings only:
        ``published_template_count`` (row count), ``total_clones_received``
        (SUM ``clone_count``) and ``avg_rating`` — a rating-count-weighted mean of
        the per-listing ``rating_avg`` (``SUM(rating_avg*rating_count) /
        SUM(rating_count)``), so a listing with more votes pulls the creator's
        average proportionally and an unrated author scores ``0.0`` (never
        ``NaN``). A blank id yields all-zero aggregates.
        """
        normalized = (author_user_id or "").strip()
        zero = {
            "published_template_count": 0,
            "total_clones_received": 0,
            "avg_rating": 0.0,
        }
        if not normalized:
            return dict(zero)
        stmt = select(
            func.count(MarketplaceTemplate.id),
            func.coalesce(func.sum(MarketplaceTemplate.clone_count), 0),
            func.coalesce(
                func.sum(
                    MarketplaceTemplate.rating_avg
                    * MarketplaceTemplate.rating_count
                ),
                0.0,
            ),
            func.coalesce(func.sum(MarketplaceTemplate.rating_count), 0),
        ).where(
            MarketplaceTemplate.author_user_id == normalized,
            MarketplaceTemplate.published.is_(True),
        )
        count, clones, weighted_rating_sum, rating_count = self._session.execute(
            stmt
        ).one()
        return {
            "published_template_count": int(count or 0),
            "total_clones_received": int(clones or 0),
            "avg_rating": (
                float(weighted_rating_sum) / float(rating_count)
                if rating_count
                else 0.0
            ),
        }

    def all_author_aggregates(self) -> dict[str, dict[str, float]]:
        """Return the public listing aggregates for EVERY author, keyed by id.

        One bounded ``GROUP BY author_user_id`` scan over ``published`` listings
        (mirroring :meth:`author_aggregates`) so a leaderboard can rank every
        creator without an N+1 per-author query. Only authors with at least one
        published listing appear. The rating is the same rating-count-weighted mean
        as :meth:`author_aggregates`.
        """
        stmt = (
            select(
                MarketplaceTemplate.author_user_id,
                func.count(MarketplaceTemplate.id),
                func.coalesce(func.sum(MarketplaceTemplate.clone_count), 0),
                func.coalesce(
                    func.sum(
                        MarketplaceTemplate.rating_avg
                        * MarketplaceTemplate.rating_count
                    ),
                    0.0,
                ),
                func.coalesce(func.sum(MarketplaceTemplate.rating_count), 0),
            )
            .where(MarketplaceTemplate.published.is_(True))
            .group_by(MarketplaceTemplate.author_user_id)
        )
        out: dict[str, dict[str, float]] = {}
        for author, count, clones, weighted_rating_sum, rating_count in (
            self._session.execute(stmt).all()
        ):
            out[author] = {
                "published_template_count": int(count or 0),
                "total_clones_received": int(clones or 0),
                "avg_rating": (
                    float(weighted_rating_sum) / float(rating_count)
                    if rating_count
                    else 0.0
                ),
            }
        return out

    def published_listing_ids_by_author(self) -> dict[str, list[str]]:
        """Return ``{author_user_id: [published listing id, ...]}`` for all authors.

        One bounded scan over ``published`` listings, grouped in Python, so the
        leaderboard can resolve every creator's downstream win-score (via the
        marketplace provenance chain in :func:`app.services.marketplace.listing_win_scores`)
        without an N+1 per-author query. Ids are ordered newest-first (then ``id``)
        for a deterministic per-author order.
        """
        stmt = (
            select(
                MarketplaceTemplate.author_user_id, MarketplaceTemplate.id
            )
            .where(MarketplaceTemplate.published.is_(True))
            .order_by(
                MarketplaceTemplate.created_at.desc(),
                MarketplaceTemplate.id.asc(),
            )
        )
        out: dict[str, list[str]] = {}
        for author, listing_id in self._session.execute(stmt).all():
            out.setdefault(author, []).append(listing_id)
        return out


class TemplateRatingRepository:
    """Upsert + aggregate maintenance for :class:`TemplateRating` rows.

    One rating exists per ``(template_id, user_id)`` — :meth:`upsert_rating`
    updates the existing row's ``stars`` rather than inserting a duplicate, then
    recomputes the parent :class:`MarketplaceTemplate`'s ``rating_avg`` /
    ``rating_count`` atomically from every rating row of that template in the same
    transaction, so the denormalized aggregate can never drift from the source
    rows.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_user(
        self, template_id: str, user_id: str
    ) -> TemplateRating | None:
        """Return the caller's existing rating of a template, or ``None``."""
        stmt = (
            select(TemplateRating)
            .where(
                TemplateRating.template_id == template_id,
                TemplateRating.user_id == user_id,
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def upsert_rating(
        self, template_id: str, user_id: str, stars: int
    ) -> TemplateRating:
        """Insert or update the caller's rating, then recompute the aggregate.

        ``stars`` is clamped defensively into ``[1, 5]``. When the caller has
        already rated this template the existing row's ``stars`` is updated in
        place (never a second row — the ``(template_id, user_id)`` UNIQUE
        constraint guarantees at-most-one). The parent listing's ``rating_avg``
        and ``rating_count`` are then recomputed from ``COUNT``/``AVG`` over every
        rating row of the template and written back in the SAME transaction, so
        the denormalized aggregate stays exactly consistent with the child rows.
        """
        safe_stars = _clamp_stars(stars)

        # Serialize concurrent rates of the SAME template: lock the parent
        # listing row FOR UPDATE before the rating insert/update and the
        # COUNT/AVG recompute, so each transaction's aggregate sees all
        # committed sibling rating rows and the denormalized
        # rating_count/rating_avg can never drift from the source rows.
        self._lock_listing(template_id)

        rating = self.get_for_user(template_id, user_id)
        if rating is None:
            rating = TemplateRating(
                template_id=template_id,
                user_id=user_id,
                stars=safe_stars,
            )
            self._session.add(rating)
        else:
            rating.stars = safe_stars
        self._session.flush()

        self._recompute_aggregate(template_id)
        return rating

    def _lock_listing(self, template_id: str) -> None:
        """SELECT ... FOR UPDATE the parent listing to serialize concurrent rates.

        Falls back to a no-op only when the backend does not support row
        locking (SQLite in tests raises ``NotSupportedError``); any other
        backend error is a real failure and propagates unchanged.
        """
        try:
            stmt = (
                select(MarketplaceTemplate)
                .where(MarketplaceTemplate.id == template_id)
                .with_for_update()
            )
            self._session.execute(stmt).scalars().first()
        except NotSupportedError:
            if self._session.get_bind().dialect.name != "sqlite":
                raise
            # SQLite (tests): no row locks — proceed without the lock.

    def _recompute_aggregate(self, template_id: str) -> None:
        """Recompute a listing's ``rating_avg`` / ``rating_count`` from its rows.

        Derives both from a single ``COUNT``/``AVG`` aggregate over the template's
        :class:`TemplateRating` rows rather than incrementally, so the cached
        values are always exactly correct (even after a re-rate that changes an
        existing star value). A listing with no ratings resets to ``(0.0, 0)``.
        """
        stmt = select(
            func.count(TemplateRating.id),
            func.coalesce(func.avg(TemplateRating.stars), 0.0),
        ).where(TemplateRating.template_id == template_id)
        count, avg = self._session.execute(stmt).one()

        listing = self._session.get(MarketplaceTemplate, template_id)
        if listing is None:
            return
        listing.rating_count = int(count or 0)
        listing.rating_avg = round(float(avg or 0.0), 4)
        self._session.flush()


#: Hard cap on the page size a single ``list_for_user`` page may return, so an
#: untrusted ``limit`` can never trigger an unbounded scan of a creator's
#: performance log. Mirrors :data:`MARKETPLACE_MAX_LIMIT`.
JOB_PERFORMANCE_MAX_LIMIT = 100
JOB_PERFORMANCE_DEFAULT_LIMIT = 50

#: Inclusive bounds for a self-reported watch-through / retention percentage. A
#: creator-entered value outside this range is meaningless, so it is clamped
#: here before it reaches the row (the win-score math relies on it being a
#: fraction of 100).
RETENTION_PCT_MIN = 0.0
RETENTION_PCT_MAX = 100.0

#: The integer engagement-count metric keys a performance log carries. Each is
#: clamped non-negative at this boundary so a hostile / mistyped payload can
#: never persist a negative count (which would corrupt the win-score aggregate).
JOB_PERFORMANCE_COUNT_KEYS: tuple[str, ...] = (
    "views",
    "likes",
    "comments",
    "shares",
    "saves",
)

#: Length cap for the free-form, creator-entered ``platform`` label, matching the
#: ``JobPerformance.platform`` ``String(40)`` column so an oversized value never
#: raises a truncation ``DataError`` on PostgreSQL.
JOB_PERFORMANCE_PLATFORM_MAX_LEN = 40


def _clamp_count(value: object) -> int:
    """Coerce a metric to a non-negative ``int`` (0 on garbage / negatives).

    Creator-entered counts are untrusted, so a non-numeric or negative value is
    floored to 0 rather than raised — a single bad field never rejects the whole
    log, and a negative count can never poison the win-score aggregate.
    """
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _clamp_retention(value: object) -> float:
    """Clamp a self-reported retention percentage into ``[0.0, 100.0]``."""
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return RETENTION_PCT_MIN
    return max(RETENTION_PCT_MIN, min(RETENTION_PCT_MAX, parsed))


def _normalize_platform(value: object) -> str:
    """Normalize a creator-entered platform label to a bounded lower-cased token.

    A blank / missing value becomes ``'unknown'`` so the column is never SQL
    ``NULL`` and aggregates always have a stable label; the value is truncated to
    the column limit so an oversized payload never raises a truncation error.
    """
    token = ("" if value is None else str(value)).strip().lower()
    if not token:
        return "unknown"
    return token[:JOB_PERFORMANCE_PLATFORM_MAX_LEN]


class JobPerformanceRepository:
    """Upsert + owner-scoped reads for :class:`JobPerformance` outcome rows.

    Backs the Hook Performance Loop: a creator logs the real-world metrics a
    posted reel earned, one row per :class:`Job`. :meth:`upsert` updates the
    existing row in place (``job_id`` is UNIQUE) rather than accumulating
    duplicates, so re-logging a job is idempotent. Every read is owner-scoped so
    a caller can never observe another creator's outcomes by guessing an id — job
    ownership itself is verified one layer up in
    :func:`app.services.hook_performance.log_performance` before any write.

    All numeric inputs are validated/clamped at this boundary: engagement counts
    are floored non-negative, ``retention_pct`` is clamped to ``[0, 100]`` and
    ``platform`` is normalized to a bounded lower-cased token — so an untrusted
    API payload can never persist an out-of-range or oversized value.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(
        self, job_id: str, user_id: str, metrics: dict | None = None
    ) -> JobPerformance:
        """Create or update the one performance row for ``job_id``.

        Owner-scoped by ``user_id`` (the verified job owner). Only recognized
        metric keys are applied; each is coerced/clamped at this boundary so a
        negative or non-numeric value can never reach the row. Re-logging finds
        the existing row (``job_id`` is UNIQUE) and updates it in place, so the
        log stays idempotent — exactly one row per job. Raises ``ValueError`` on a
        blank ``job_id`` / ``user_id`` so an unattributable row is never
        persisted. Returns the id-populated row.
        """
        normalized_job = (job_id or "").strip()
        if not normalized_job:
            raise ValueError("job_id must be a non-empty string")
        normalized_user = (user_id or "").strip()
        if not normalized_user:
            raise ValueError("user_id must be a non-empty string")

        payload = dict(metrics or {})
        row = self._get_for_job_unscoped(normalized_job)
        if row is None:
            row = JobPerformance(job_id=normalized_job, user_id=normalized_user)
            self._session.add(row)
        else:
            # Keep the denormalized owner in sync (it is always the job owner).
            row.user_id = normalized_user

        if "platform" in payload:
            row.platform = _normalize_platform(payload.get("platform"))
        for key in JOB_PERFORMANCE_COUNT_KEYS:
            if key in payload:
                setattr(row, key, _clamp_count(payload.get(key)))
        if "retention_pct" in payload:
            row.retention_pct = _clamp_retention(payload.get("retention_pct"))

        self._session.flush()  # populate row.id without ending the transaction
        return row

    def get_for_job(self, job_id: str, user_id: str) -> JobPerformance | None:
        """Return the job's performance row only when it belongs to ``user_id``.

        Ownership is enforced here so a caller cannot read another creator's
        outcome by guessing a job id; a foreign or missing id returns ``None``.
        """
        row = self._get_for_job_unscoped((job_id or "").strip())
        if row is None or row.user_id != user_id:
            return None
        return row

    def list_for_user(
        self,
        user_id: str,
        limit: int = JOB_PERFORMANCE_DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[JobPerformance]:
        """Return the user's performance rows, newest first, paginated.

        Owner-scoped: only rows belonging to ``user_id`` are returned. ``limit``
        is clamped to ``[1, 100]`` and ``offset`` to ``>= 0`` so an untrusted page
        request can never trigger an unbounded scan.
        """
        safe_limit = max(1, min(int(limit or 0), JOB_PERFORMANCE_MAX_LIMIT))
        safe_offset = max(0, int(offset or 0))
        stmt = (
            select(JobPerformance)
            .where(JobPerformance.user_id == user_id)
            .order_by(JobPerformance.logged_at.desc())
            .limit(safe_limit)
            .offset(safe_offset)
        )
        return list(self._session.execute(stmt).scalars().all())

    def _get_for_job_unscoped(self, job_id: str) -> JobPerformance | None:
        """Resolve the singleton performance row for a job id (no owner check).

        A blank id never matches. Used internally by the owner-scoped
        :meth:`get_for_job` and by :meth:`upsert` (which owns the ownership
        guarantee via the verified ``user_id`` passed in).
        """
        if not job_id:
            return None
        stmt = (
            select(JobPerformance)
            .where(JobPerformance.job_id == job_id)
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()


#: The social platforms a :class:`SocialAccount` may connect (Direct-Publish
#: Account-Connect). A provider outside this set is rejected at the repository
#: boundary so an unknown platform can never be persisted (the DB column is a
#: plain ``String`` with no CHECK constraint). Kept lower-cased to match the
#: normalized ``provider`` token.
SOCIAL_PROVIDERS: frozenset[str] = frozenset({"tiktok", "instagram", "youtube"})


def _normalize_provider(value: object) -> str:
    """Validate + normalize a social provider to one of :data:`SOCIAL_PROVIDERS`.

    Coerces to a lower-cased, stripped token and raises ``ValueError`` on an
    unknown / blank provider so an invalid value can never reach the row.
    """
    token = ("" if value is None else str(value)).strip().lower()
    if token not in SOCIAL_PROVIDERS:
        raise ValueError(
            f"invalid social provider: {value!r} "
            f"(expected one of {sorted(SOCIAL_PROVIDERS)})"
        )
    return token


class SocialAccountRepository:
    """Owner-scoped CRUD + per-(user, provider) upsert for :class:`SocialAccount`.

    Backs Direct-Publish Account-Connect. A creator connects a social platform
    via OAuth; :meth:`upsert` stores the connection (already-ENCRYPTED token
    blobs — this layer never sees plaintext) with exactly one row per
    ``(user_id, provider)`` (the composite UNIQUE constraint), so re-connecting a
    provider updates the existing row in place rather than accumulating
    duplicates. Every read (:meth:`get`, :meth:`list_for_user`) is scoped to
    ``user_id`` so a caller can never read another creator's connection — and
    therefore never publish with another creator's tokens — by guessing an id or
    provider.

    SECURITY: this layer only ever handles the *encrypted* ``access_token_enc`` /
    ``refresh_token_enc`` blobs. Encryption/decryption is the caller's job
    (:mod:`app.services.crypto_tokens`); a plaintext token never reaches here.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(
        self,
        *,
        user_id: str,
        provider: str,
        access_token_enc: str,
        external_account_id: str = "",
        refresh_token_enc: str | None = None,
        token_expires_at: datetime | None = None,
        scopes: str = "",
    ) -> SocialAccount:
        """Create or update the one connection for ``(user_id, provider)``.

        Owner-scoped by ``user_id``. ``provider`` is validated/normalized to one
        of :data:`SOCIAL_PROVIDERS` (raising ``ValueError`` on an unknown value).
        ``access_token_enc`` is the caller-encrypted access-token blob and must be
        non-empty — a connection without an access token is unusable, so a blank
        value raises ``ValueError`` rather than persisting a dead row. Re-connecting
        a provider finds the existing row (the ``(user_id, provider)`` UNIQUE
        constraint guarantees at-most-one) and replaces its token blobs / expiry /
        scopes in place, so the connection stays a singleton. Returns the
        id-populated row.
        """
        normalized_user = (user_id or "").strip()
        if not normalized_user:
            raise ValueError("user_id must be a non-empty string")
        normalized_provider = _normalize_provider(provider)
        enc = (access_token_enc or "").strip()
        if not enc:
            raise ValueError("access_token_enc must be a non-empty string")

        row = self._get_unscoped(normalized_user, normalized_provider)
        if row is None:
            row = SocialAccount(
                user_id=normalized_user,
                provider=normalized_provider,
            )
            self._session.add(row)

        row.access_token_enc = enc
        row.refresh_token_enc = refresh_token_enc or None
        row.external_account_id = str(external_account_id or "")
        row.token_expires_at = token_expires_at
        row.scopes = str(scopes or "")

        self._session.flush()  # populate row.id without ending the transaction
        return row

    def get(self, user_id: str, provider: str) -> SocialAccount | None:
        """Return the caller's connection for ``provider``, or ``None``.

        Owner-scoped: the query filters on BOTH ``user_id`` and the normalized
        ``provider`` so a caller can never read another creator's connection. A
        blank ``user_id`` or an unknown/blank provider never matches (returns
        ``None``) rather than raising, so a lookup is a safe, side-effect-free
        probe.
        """
        normalized_user = (user_id or "").strip()
        if not normalized_user:
            return None
        token = ("" if provider is None else str(provider)).strip().lower()
        if token not in SOCIAL_PROVIDERS:
            return None
        return self._get_unscoped(normalized_user, token)

    def list_for_user(self, user_id: str) -> list[SocialAccount]:
        """Return every connection ``user_id`` owns, newest first.

        Owner-scoped: only rows belonging to ``user_id`` are returned. A blank
        ``user_id`` yields an empty list so an empty owner id can never sweep up
        unrelated rows.
        """
        normalized_user = (user_id or "").strip()
        if not normalized_user:
            return []
        stmt = (
            select(SocialAccount)
            .where(SocialAccount.user_id == normalized_user)
            .order_by(SocialAccount.connected_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_expiring_before(
        self, before: datetime, limit: int = 100
    ) -> list[SocialAccount]:
        """Return a bounded oldest-expiring-first refresh worklist.

        Accounts with an unknown expiry are intentionally excluded: refreshing
        them would be speculative and may violate provider token policies.
        """
        if not isinstance(before, datetime):
            raise ValueError("before must be a datetime")
        stmt = (
            select(SocialAccount)
            .where(
                SocialAccount.token_expires_at.is_not(None),
                SocialAccount.token_expires_at <= before,
            )
            .order_by(SocialAccount.token_expires_at.asc())
            .limit(max(1, min(int(limit), 1000)))
        )
        return list(self._session.execute(stmt).scalars().all())

    def delete(self, user_id: str, provider: str) -> bool:
        """Disconnect a provider owned by ``user_id``; return whether a row went.

        Owner-scoped: returns ``False`` (without deleting) when no connection
        exists for the caller and provider, so a caller can never disconnect
        another creator's account by guessing a provider.
        """
        row = self.get(user_id, provider)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def _get_unscoped(self, user_id: str, provider: str) -> SocialAccount | None:
        """Resolve the singleton connection for a (user, provider) pair.

        Callers pass an already-normalized ``user_id`` / ``provider``; the
        ``(user_id, provider)`` UNIQUE constraint guarantees at most one row.
        """
        stmt = (
            select(SocialAccount)
            .where(
                SocialAccount.user_id == user_id,
                SocialAccount.provider == provider,
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()


#: Phase 3 "Connect your store" providers (App Store Connect, Google Play Console).
STORE_PROVIDERS: frozenset[str] = frozenset({"appstore", "play"})


def _normalize_store_provider(value: object) -> str:
    """Validate + normalize a store provider to one of :data:`STORE_PROVIDERS`."""
    token = ("" if value is None else str(value)).strip().lower()
    if token not in STORE_PROVIDERS:
        raise ValueError(
            f"unknown store provider {value!r} (expected one of {sorted(STORE_PROVIDERS)})"
        )
    return token


class StoreConnectionRepository:
    """Owner-scoped CRUD + per-(user, provider) upsert for :class:`StoreConnection`.

    Backs Phase 3 "Connect your store". Mirrors :class:`SocialAccountRepository`'s
    shape exactly: one row per ``(user_id, provider)`` (re-connecting UPSERTs in
    place) and every read is scoped to ``user_id`` so a caller can never read —
    and therefore never call the App Store Connect / Play Developer API with —
    another creator's credentials.

    SECURITY: this layer only ever handles the *encrypted* ``credentials_enc``
    blob. Encryption/decryption is the caller's job
    (:mod:`app.services.crypto_tokens`); a plaintext credential never reaches here.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(
        self,
        *,
        user_id: str,
        provider: str,
        credentials_enc: str,
        account_name: str = "",
        meta: dict | None = None,
        status: str = "connected",
        status_note: str = "",
    ) -> StoreConnection:
        """Create or update the one connection for ``(user_id, provider)``."""
        normalized_user = (user_id or "").strip()
        if not normalized_user:
            raise ValueError("user_id must be a non-empty string")
        normalized_provider = _normalize_store_provider(provider)
        enc = (credentials_enc or "").strip()
        if not enc:
            raise ValueError("credentials_enc must be a non-empty string")

        row = self._get_unscoped(normalized_user, normalized_provider)
        if row is None:
            row = StoreConnection(user_id=normalized_user, provider=normalized_provider)
            self._session.add(row)

        row.credentials_enc = enc
        row.account_name = str(account_name or "")[:300]
        row.meta = dict(meta or {})
        row.status = str(status or "connected")[:20]
        row.status_note = str(status_note or "")

        self._session.flush()
        return row

    def get(self, user_id: str, provider: str) -> StoreConnection | None:
        """Return the caller's connection for ``provider``, or ``None``."""
        normalized_user = (user_id or "").strip()
        if not normalized_user:
            return None
        token = ("" if provider is None else str(provider)).strip().lower()
        if token not in STORE_PROVIDERS:
            return None
        return self._get_unscoped(normalized_user, token)

    def list_for_user(self, user_id: str) -> list[StoreConnection]:
        """Return every store connection ``user_id`` owns, newest first."""
        normalized_user = (user_id or "").strip()
        if not normalized_user:
            return []
        stmt = (
            select(StoreConnection)
            .where(StoreConnection.user_id == normalized_user)
            .order_by(StoreConnection.connected_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def delete(self, user_id: str, provider: str) -> bool:
        """Disconnect a provider owned by ``user_id``; return whether a row went."""
        row = self.get(user_id, provider)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def _get_unscoped(self, user_id: str, provider: str) -> StoreConnection | None:
        stmt = (
            select(StoreConnection)
            .where(
                StoreConnection.user_id == user_id,
                StoreConnection.provider == provider,
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()


class ShareLinkRepository:
    """Owner-scoped CRUD for :class:`ShareLink` public reel-share links.

    Backs Public Watermarked Share Pages: a creator turns one of THEIR OWN reels
    into a public, unguessable, revocable link, and anyone with the link views a
    watermarked preview (never the clean result). Security invariants enforced
    here:

    * **Strictly per-user + one active link per job.** :meth:`create_for_job`
      verifies the job belongs to the caller BEFORE any write and returns the
      existing *active* (non-revoked) link for that job rather than minting a
      duplicate — so a job has at most one live public link at a time and a caller
      can never share another creator's job.
    * **Revoked == non-existent.** :meth:`get_by_token` resolves ONLY a
      non-revoked link, so a revoked link is invisible to every public read even
      though the row is retained for audit.
    * **Unguessable token.** The token is a 128-bit ``secrets.token_urlsafe`` value
      (see :func:`app.models.db.models._share_token`) that is UNIQUE + indexed, so
      a link can never be enumerated.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_for_job(self, job_id: str, user_id: str) -> ShareLink:
        """Create (or return the existing active) share link for the caller's job.

        Owner-scoped: the job is loaded and its ``user_id`` compared to the caller
        BEFORE any write, so a caller can never share another creator's job. When
        an active (non-revoked) link already exists for the job it is returned
        as-is (idempotent — one live public link per job); a previously revoked
        link never blocks minting a fresh one. Raises ``ValueError`` on a blank
        ``job_id`` / ``user_id`` or a missing job, and ``PermissionError`` when the
        job exists but belongs to a different user (mirroring
        :func:`app.services.hook_performance.log_performance`).
        """
        normalized_job = (job_id or "").strip()
        if not normalized_job:
            raise ValueError("job_id must be a non-empty string")
        normalized_user = (user_id or "").strip()
        if not normalized_user:
            raise ValueError("user_id must be a non-empty string")

        job = self._session.get(Job, normalized_job)
        if job is None:
            raise ValueError(f"job not found: {job_id}")
        if job.user_id != normalized_user:
            # Never leak existence details across users beyond the ownership fact.
            raise PermissionError("job does not belong to the requesting user")

        existing = self._active_link_for_job(normalized_job)
        if existing is not None:
            return existing

        link = ShareLink(job_id=normalized_job, user_id=normalized_user)
        self._session.add(link)
        self._session.flush()  # populate link.id/token without ending the txn
        return link

    def get_by_token(self, token: str) -> ShareLink | None:
        """Resolve a token to its LIVE (non-revoked) link, or ``None``.

        Only a non-revoked row matches so a revoked link is invisible to every
        public read. A blank/whitespace-only token never matches (returns
        ``None``) so an empty token can never sweep up a row.
        """
        normalized = (token or "").strip()
        if not normalized:
            return None
        stmt = (
            select(ShareLink)
            .where(
                ShareLink.token == normalized,
                ShareLink.revoked.is_(False),
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def revoke(self, token: str, user_id: str) -> bool:
        """Owner-scoped soft-revoke of a link by token; return whether it changed.

        Guarded ``UPDATE ... WHERE token AND user_id AND NOT revoked``: returns
        ``True`` only when a live link belonging to the caller was flipped to
        revoked. Returns ``False`` (without touching any row) when the token does
        not exist, belongs to a different user, or is already revoked — so a caller
        can never revoke another creator's link by guessing its token, and a
        double-revoke is a harmless no-op. The row is retained (soft delete) for
        audit; the public read path (:meth:`get_by_token`) treats it as gone.
        """
        normalized = (token or "").strip()
        normalized_user = (user_id or "").strip()
        if not normalized or not normalized_user:
            return False
        stmt = (
            update(ShareLink)
            .where(
                ShareLink.token == normalized,
                ShareLink.user_id == normalized_user,
                ShareLink.revoked.is_(False),
            )
            .values(revoked=True)
        )
        result = self._session.execute(stmt)
        self._session.flush()
        return (result.rowcount or 0) == 1

    def increment_view(self, token: str) -> None:
        """Atomically bump a LIVE link's ``view_count`` by one.

        Uses an in-place ``view_count = view_count + 1`` UPDATE (never a
        read-modify-write) so concurrent public views cannot lose an increment.
        Guarded on ``NOT revoked`` so a view of a revoked link is a silent no-op
        (a revoked link is never publicly viewable). A blank token is a no-op.
        """
        normalized = (token or "").strip()
        if not normalized:
            return
        stmt = (
            update(ShareLink)
            .where(
                ShareLink.token == normalized,
                ShareLink.revoked.is_(False),
            )
            .values(view_count=ShareLink.view_count + 1)
        )
        self._session.execute(stmt)
        self._session.flush()

    def _active_link_for_job(self, job_id: str) -> ShareLink | None:
        """Return the job's existing active (non-revoked) link, or ``None``.

        Backs the one-active-link-per-job guarantee: a job has at most one live
        public link at a time. Callers pass an already-normalized ``job_id``.
        """
        stmt = (
            select(ShareLink)
            .where(
                ShareLink.job_id == job_id,
                ShareLink.revoked.is_(False),
            )
            .order_by(ShareLink.created_at.asc())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()


class CreatorFollowRepository:
    """Owner-scoped CRUD + aggregates for the :class:`CreatorFollow` graph.

    Backs Creator Profiles + Follow Graph + Leaderboards. Security / correctness
    invariants enforced here:

    * **Idempotent follow.** :meth:`follow` returns the existing edge when one is
      already present (and defends against a concurrent insert via the
      ``(follower, followee)`` UNIQUE constraint), so a double-follow can never
      create a second row.
    * **No self-follow.** :meth:`follow` rejects ``follower == followee`` with a
      ``ValueError`` before any write — a user can never follow themselves.
    * **Unfollow removes exactly one edge.** :meth:`unfollow` deletes the single
      directed edge (a no-op ``False`` when it does not exist), never a batch.
    * **Public aggregates only.** :meth:`follower_count` / :meth:`following_count`
      / :meth:`follower_counts` expose only counts — never any private field.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def follow(
        self, follower_user_id: str, followee_user_id: str
    ) -> CreatorFollow:
        """Idempotently create (or return the existing) follow edge.

        Rejects a blank id or a self-follow (``follower == followee``) with a
        ``ValueError`` before any write. When the edge already exists it is
        returned as-is (idempotent). A concurrent insert that loses the race
        surfaces as an ``IntegrityError`` on flush, which is caught and resolved to
        the now-existing edge, so the operation is safe under concurrency.
        """
        follower = (follower_user_id or "").strip()
        followee = (followee_user_id or "").strip()
        if not follower:
            raise ValueError("follower_user_id must be a non-empty string")
        if not followee:
            raise ValueError("followee_user_id must be a non-empty string")
        if follower == followee:
            raise ValueError("a user cannot follow themselves")

        existing = self._get_edge(follower, followee)
        if existing is not None:
            return existing

        edge = CreatorFollow(
            follower_user_id=follower, followee_user_id=followee
        )
        self._session.add(edge)
        try:
            self._session.flush()  # populate edge.id without ending the txn
        except IntegrityError:
            # Lost a concurrent insert race — the UNIQUE constraint fired. Roll the
            # failed INSERT back to a clean state and return the winning edge.
            self._session.rollback()
            winner = self._get_edge(follower, followee)
            if winner is None:  # pragma: no cover - unexpected, re-raise
                raise
            return winner
        return edge

    def unfollow(self, follower_user_id: str, followee_user_id: str) -> bool:
        """Remove the single directed edge; return whether a row was deleted.

        Owner-scoped guarded ``DELETE ... WHERE follower AND followee``: returns
        ``True`` only when exactly the caller's own edge was removed, ``False``
        (touching nothing) when the edge does not exist — so a double-unfollow is a
        harmless no-op and no other user's edge is ever affected. A blank id is a
        no-op ``False``.
        """
        follower = (follower_user_id or "").strip()
        followee = (followee_user_id or "").strip()
        if not follower or not followee:
            return False
        stmt = (
            delete(CreatorFollow)
            .where(
                CreatorFollow.follower_user_id == follower,
                CreatorFollow.followee_user_id == followee,
            )
        )
        result = self._session.execute(stmt)
        self._session.flush()
        return (result.rowcount or 0) >= 1

    def is_following(
        self, follower_user_id: str, followee_user_id: str
    ) -> bool:
        """Return whether ``follower`` currently follows ``followee``.

        A blank id never matches (returns ``False``).
        """
        follower = (follower_user_id or "").strip()
        followee = (followee_user_id or "").strip()
        if not follower or not followee:
            return False
        return self._get_edge(follower, followee) is not None

    def follower_count(self, user_id: str) -> int:
        """Return how many users follow ``user_id`` (0 for a blank id)."""
        normalized = (user_id or "").strip()
        if not normalized:
            return 0
        stmt = select(func.count(CreatorFollow.id)).where(
            CreatorFollow.followee_user_id == normalized
        )
        return int(self._session.execute(stmt).scalar_one() or 0)

    def following_count(self, user_id: str) -> int:
        """Return how many users ``user_id`` follows (0 for a blank id)."""
        normalized = (user_id or "").strip()
        if not normalized:
            return 0
        stmt = select(func.count(CreatorFollow.id)).where(
            CreatorFollow.follower_user_id == normalized
        )
        return int(self._session.execute(stmt).scalar_one() or 0)

    def follower_counts(self) -> dict[str, int]:
        """Return ``{followee_user_id: follower_count}`` for every followed user.

        One bounded ``GROUP BY followee_user_id`` scan so a leaderboard can rank by
        follower count without an N+1 per-user query. Users with zero followers are
        simply absent.
        """
        stmt = select(
            CreatorFollow.followee_user_id, func.count(CreatorFollow.id)
        ).group_by(CreatorFollow.followee_user_id)
        return {
            followee: int(count or 0)
            for followee, count in self._session.execute(stmt).all()
        }

    def following_counts(self) -> dict[str, int]:
        """Return ``{follower_user_id: following_count}`` for every following user.

        The symmetric bulk companion to :meth:`follower_counts` (one bounded
        ``GROUP BY follower_user_id`` scan) so a leaderboard can annotate each entry
        with a following count without an N+1 per-user query. Users who follow
        nobody are simply absent.
        """
        stmt = select(
            CreatorFollow.follower_user_id, func.count(CreatorFollow.id)
        ).group_by(CreatorFollow.follower_user_id)
        return {
            follower: int(count or 0)
            for follower, count in self._session.execute(stmt).all()
        }

    def _get_edge(
        self, follower_user_id: str, followee_user_id: str
    ) -> CreatorFollow | None:
        """Resolve the single directed edge for a (follower, followee) pair.

        Callers pass already-normalized ids; the ``(follower, followee)`` UNIQUE
        constraint guarantees at most one row.
        """
        stmt = (
            select(CreatorFollow)
            .where(
                CreatorFollow.follower_user_id == follower_user_id,
                CreatorFollow.followee_user_id == followee_user_id,
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()


class AuditLogRepository:
    """APPEND-ONLY persistence for :class:`AuditLog` rows (Access & Governance).

    Deliberately exposes NO update or delete — a governance trail must be
    tamper-evident, so the only writes are inserts and the only reads are
    tenant-scoped, newest-first listings. Authorization for *reading* a
    workspace's trail lives one layer up in :mod:`app.services.audit` (which
    requires the caller hold ``audit.read`` before calling
    :meth:`list_for_workspace`); this repository is the pure persistence layer.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        actor_user_id: str,
        action: str,
        workspace_id: str | None = None,
        target_type: str = "",
        target_id: str | None = None,
        metadata: dict | None = None,
        ip: str | None = None,
    ) -> AuditLog:
        """INSERT one immutable audit row and flush to obtain its id.

        The ``metadata`` mapping is copied (immutable update) so later mutation
        of the caller's dict cannot bleed into the persisted row. ``action`` is
        required (a row with no action is unauditable); ``workspace_id`` is
        optional so a platform-level action (e.g. a staff impersonation) can be
        recorded without a tenant. Raises ``ValueError`` on a blank
        ``actor_user_id`` / ``action`` so an unattributable row is never stored.
        """
        normalized_actor = (actor_user_id or "").strip()
        if not normalized_actor:
            raise ValueError("actor_user_id must be a non-empty string")
        normalized_action = (action or "").strip()
        if not normalized_action:
            raise ValueError("action must be a non-empty string")

        row = AuditLog(
            actor_user_id=normalized_actor,
            action=normalized_action,
            workspace_id=workspace_id or None,
            target_type=str(target_type or ""),
            target_id=(target_id or None),
            meta=dict(metadata or {}),
            ip=(ip or None),
        )
        self._session.add(row)
        self._session.flush()  # populate row.id without ending the transaction
        return row

    def list_for_workspace(
        self, workspace_id: str, limit: int = 50, offset: int = 0
    ) -> list[AuditLog]:
        """Return a workspace's audit rows, newest first, paginated.

        Strictly tenant-scoped: filters on ``workspace_id`` so a caller can never
        read another tenant's trail (the calling service also gates on
        ``audit.read``). An empty / whitespace-only ``workspace_id`` never
        matches (returns ``[]``) so a blank filter can never sweep up
        platform-level rows. ``limit`` is clamped to at least 1 and ``offset`` to
        at least 0 so a non-positive page never yields an invalid query. Backed
        by the composite ``(workspace_id, created_at)`` index.
        """
        normalized = (workspace_id or "").strip()
        if not normalized:
            return []
        stmt = (
            select(AuditLog)
            .where(AuditLog.workspace_id == normalized)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(max(1, limit))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())


class AdminRepository:
    """Cross-tenant list queries backing the platform-admin surface.

    Powers :mod:`app.services.admin` (list users / workspaces / jobs for a
    ReelForge *staff* operator). This is the persistence layer ONLY — it performs
    NO authorization; the ``User.is_staff`` hard gate lives in the service and
    every service function checks it before reaching here, so this class must
    never be wired to a request without that gate. Every query is newest-first
    and paginated with the same clamp idiom used across the repositories
    (``max(1, limit)`` / ``max(0, offset)``) so a non-positive page can never
    produce an invalid statement.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_users(self, limit: int = 50, offset: int = 0) -> list[User]:
        """Return all users, newest first, paginated (staff-only, gated above)."""
        stmt = (
            select(User)
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(max(1, limit))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_workspaces(
        self, limit: int = 50, offset: int = 0
    ) -> list[Workspace]:
        """Return all workspaces, newest first, paginated (staff-only)."""
        stmt = (
            select(Workspace)
            .order_by(Workspace.created_at.desc(), Workspace.id.desc())
            .limit(max(1, limit))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_jobs(self, limit: int = 50, offset: int = 0) -> list[Job]:
        """Return all jobs across every tenant, newest first, paginated (staff-only)."""
        stmt = (
            select(Job)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(max(1, limit))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())


# --------------------------------------------------------------------------- #
# Enterprise Identity & SSO (Epic 2)
# --------------------------------------------------------------------------- #
#: The SSO protocols a :class:`SSOConnection` may speak. Validated at the
#: repository boundary so an unknown value can never be persisted (the DB column
#: is a plain ``String`` with no CHECK).
SSO_PROTOCOL_SAML = "saml"
SSO_PROTOCOL_OIDC = "oidc"
SSO_PROTOCOLS: frozenset[str] = frozenset({SSO_PROTOCOL_SAML, SSO_PROTOCOL_OIDC})


def _normalize_protocol(value: object) -> str:
    """Validate + normalize an SSO protocol to one of :data:`SSO_PROTOCOLS`.

    Raises ``ValueError`` on an unknown / blank value so an invalid protocol can
    never be persisted.
    """
    token = ("" if value is None else str(value)).strip().lower()
    if token not in SSO_PROTOCOLS:
        raise ValueError(
            f"invalid SSO protocol: {value!r} (expected one of {sorted(SSO_PROTOCOLS)})"
        )
    return token


class SSOConnectionRepository:
    """Per-workspace upsert + resolution for :class:`SSOConnection` (Identity & SSO).

    Exactly ONE connection exists per workspace (``workspace_id`` is UNIQUE), so
    :meth:`upsert` updates the single row in place rather than accumulating
    duplicates and :meth:`get_for_workspace` resolves it by workspace id in an
    O(index) lookup. TENANT ISOLATION: every read/write is scoped to a single
    ``workspace_id`` so a connection can never authenticate into another
    workspace.

    SECURITY: this layer stores the caller-ENCRYPTED cert / secret blobs verbatim
    (``idp_x509_cert_enc`` / ``oidc_client_secret_enc``) — encryption/decryption
    is the service's job (:mod:`app.services.crypto_tokens`); a plaintext secret
    never reaches here.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_workspace(self, workspace_id: str) -> SSOConnection | None:
        """Return the workspace's SSO connection, or ``None`` when unset.

        A blank ``workspace_id`` never matches (returns ``None``) so an empty id
        can never sweep up an unrelated row.
        """
        normalized = (workspace_id or "").strip()
        if not normalized:
            return None
        stmt = (
            select(SSOConnection)
            .where(SSOConnection.workspace_id == normalized)
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def upsert(
        self,
        *,
        workspace_id: str,
        protocol: str,
        idp_entity_id: str = "",
        idp_sso_url: str = "",
        idp_x509_cert_enc: str | None = None,
        sp_acs_url: str = "",
        oidc_client_id: str | None = None,
        oidc_client_secret_enc: str | None = None,
        enabled: bool = False,
    ) -> SSOConnection:
        """Create or update the one connection for ``workspace_id``; return the row.

        ``protocol`` is validated/normalized to :data:`SSO_PROTOCOLS` (raising
        ``ValueError`` on an unknown value). The encrypted blobs are stored
        verbatim; a ``None`` blob leaves the column NULL (SAML has no OIDC secret
        and vice-versa). Raises ``ValueError`` on a blank ``workspace_id``.
        """
        normalized_ws = (workspace_id or "").strip()
        if not normalized_ws:
            raise ValueError("workspace_id must be a non-empty string")
        normalized_protocol = _normalize_protocol(protocol)

        row = self.get_for_workspace(normalized_ws)
        if row is None:
            row = SSOConnection(workspace_id=normalized_ws)
            self._session.add(row)

        row.protocol = normalized_protocol
        row.idp_entity_id = str(idp_entity_id or "")
        row.idp_sso_url = str(idp_sso_url or "")
        row.idp_x509_cert_enc = idp_x509_cert_enc or None
        row.sp_acs_url = str(sp_acs_url or "")
        row.oidc_client_id = oidc_client_id or None
        row.oidc_client_secret_enc = oidc_client_secret_enc or None
        row.enabled = bool(enabled)

        self._session.flush()  # populate row.id without ending the transaction
        return row

    def set_enabled(self, workspace_id: str, enabled: bool) -> SSOConnection | None:
        """Flip a connection's ``enabled`` flag; return the row or ``None``."""
        row = self.get_for_workspace(workspace_id)
        if row is None:
            return None
        row.enabled = bool(enabled)
        self._session.flush()
        return row

    def delete(self, workspace_id: str) -> bool:
        """Delete a workspace's connection; return whether a row was removed."""
        row = self.get_for_workspace(workspace_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True


class ScimTokenRepository:
    """CRUD + resolution for per-workspace :class:`ScimToken` bearer tokens.

    Backs SCIM 2.0 provisioning auth. TENANT ISOLATION: :meth:`get_by_hash`
    resolves a presented token's digest to its LIVE (non-revoked) row, and the
    SCIM auth layer asserts the row's ``workspace_id`` matches the target before
    any write/read — so a token minted for workspace B can never provision into
    or read workspace A.

    SECURITY: this layer only ever handles the SHA-256 **digest** of a token,
    never the raw secret (the raw token is revealed once at creation).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, workspace_id: str, token_hash: str, prefix: str = ""
    ) -> ScimToken:
        """Insert a new (active) SCIM token row and flush to obtain its id.

        ``token_hash`` is the caller-computed SHA-256 hex digest — the raw token
        is never passed in or stored. Raises ``ValueError`` on a blank
        ``workspace_id`` / ``token_hash`` so an unusable row can never be
        persisted. A duplicate ``token_hash`` violates the UNIQUE constraint and
        surfaces as an ``IntegrityError`` on flush.
        """
        normalized_ws = (workspace_id or "").strip()
        if not normalized_ws:
            raise ValueError("workspace_id must be a non-empty string")
        normalized_hash = (token_hash or "").strip()
        if not normalized_hash:
            raise ValueError("token_hash must be a non-empty string")

        token = ScimToken(
            workspace_id=normalized_ws,
            token_hash=normalized_hash,
            prefix=str(prefix or ""),
            revoked=False,
        )
        self._session.add(token)
        self._session.flush()  # populate token.id without ending the transaction
        return token

    def get_by_hash(self, token_hash: str) -> ScimToken | None:
        """Resolve a presented token's digest to its LIVE (non-revoked) row.

        Only a non-revoked row matches so a revoked token can never authenticate.
        A blank/whitespace-only digest never matches (returns ``None``). NOTE:
        this deliberately does NOT filter by workspace — the caller (SCIM auth)
        compares the resolved row's ``workspace_id`` to the target so a mismatch
        is a clean tenant-isolation denial rather than an ambiguous "not found".
        """
        normalized = (token_hash or "").strip()
        if not normalized:
            return None
        stmt = (
            select(ScimToken)
            .where(
                ScimToken.token_hash == normalized,
                ScimToken.revoked.is_(False),
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def list_for_workspace(self, workspace_id: str) -> list[ScimToken]:
        """Return ALL of the workspace's tokens (active + revoked), newest first."""
        normalized = (workspace_id or "").strip()
        if not normalized:
            return []
        stmt = (
            select(ScimToken)
            .where(ScimToken.workspace_id == normalized)
            .order_by(ScimToken.created_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def revoke(self, token_id: str, workspace_id: str) -> bool:
        """Soft-revoke a token owned by ``workspace_id``; return whether a row changed.

        Workspace-scoped guarded ``UPDATE ... WHERE id AND workspace_id AND NOT
        revoked``: a caller can never revoke another workspace's token by guessing
        its id, and a double-revoke is a harmless no-op. The row is retained (soft
        delete) for audit.
        """
        stmt = (
            update(ScimToken)
            .where(
                ScimToken.id == token_id,
                ScimToken.workspace_id == workspace_id,
                ScimToken.revoked.is_(False),
            )
            .values(revoked=True)
        )
        result = self._session.execute(stmt)
        self._session.flush()
        return (result.rowcount or 0) == 1

    def touch_last_used(self, token_id: str) -> None:
        """Best-effort stamp ``last_used_at`` to now for a token (never raises)."""
        try:
            token = self._session.get(ScimToken, token_id)
            if token is None:
                return
            token.last_used_at = datetime.now(timezone.utc)
            self._session.flush()
        except Exception as exc:  # noqa: BLE001 - best-effort telemetry write
            logger.warning(f"touch_last_used failed for scim token {token_id}: {exc}")


class SecurityPolicyRepository:
    """Read + upsert for the per-workspace :class:`SecurityPolicy` singleton.

    Exactly ONE policy per workspace (``workspace_id`` is the PK), so :meth:`upsert`
    updates the existing row in place rather than inserting a duplicate and
    :meth:`get` resolves the singleton by workspace id. The JSON list columns are
    copied on write (immutable update) so a later mutation of the caller's list
    cannot bleed into the persisted row.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, workspace_id: str) -> SecurityPolicy | None:
        """Return the workspace's security policy, or ``None`` when unset."""
        normalized = (workspace_id or "").strip()
        if not normalized:
            return None
        return self._session.get(SecurityPolicy, normalized)

    def upsert(self, workspace_id: str, **fields: object) -> SecurityPolicy:
        """Create or update the workspace's policy, returning the row.

        Only the recognized keys (``require_sso``, ``session_timeout_min``,
        ``allowed_email_domains``, ``mfa_required``, ``ip_allowlist``) are applied
        and only when their value is not ``None`` — a partial update leaves the
        untouched columns as they were (or at their column default on first
        insert). The JSON lists are copied + normalized (domains lower-cased,
        blanks dropped) at this boundary so an untrusted payload can never persist
        a malformed policy. Raises ``ValueError`` on a blank ``workspace_id``.
        """
        normalized = (workspace_id or "").strip()
        if not normalized:
            raise ValueError("workspace_id must be a non-empty string")

        policy = self.get(normalized)
        if policy is None:
            policy = SecurityPolicy(workspace_id=normalized)
            self._session.add(policy)

        if fields.get("require_sso") is not None:
            policy.require_sso = bool(fields["require_sso"])
        if fields.get("session_timeout_min") is not None:
            policy.session_timeout_min = max(0, int(fields["session_timeout_min"]))  # type: ignore[arg-type]
        if fields.get("allowed_email_domains") is not None:
            policy.allowed_email_domains = _normalize_str_list(
                fields["allowed_email_domains"], lower=True
            )
        if fields.get("mfa_required") is not None:
            policy.mfa_required = bool(fields["mfa_required"])
        if fields.get("ip_allowlist") is not None:
            policy.ip_allowlist = _normalize_str_list(
                fields["ip_allowlist"], lower=False
            )

        self._session.flush()
        return policy


def _normalize_str_list(value: object, *, lower: bool) -> list[str]:
    """Coerce an untrusted value into a clean list of non-blank strings.

    Accepts a list/tuple/set (or a single string). Each entry is coerced to
    ``str``, stripped, optionally lower-cased, and dropped when blank. Returns a
    fresh list (immutable update) so the caller's container is never mutated.
    """
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    out: list[str] = []
    for item in items:
        token = str(item or "").strip()
        if lower:
            token = token.lower()
        if token:
            out.append(token)
    return out


class ExternalIdentityRepository:
    """Tenant-scoped CRUD for :class:`ExternalIdentity` IdP<->user links.

    Shared by the SAML ACS path and the SCIM provisioning path. TENANT ISOLATION:
    a composite UNIQUE on ``(workspace_id, idp_subject)`` guarantees a subject maps
    to at most one identity per workspace, and EVERY lookup filters on
    ``workspace_id`` so an identity provisioned in workspace B can never be
    resolved from workspace A. Deactivation is a soft-disable (``provisioned`` ->
    ``False``), never a delete, so the mapping is retained for audit.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_subject(
        self, workspace_id: str, idp_subject: str
    ) -> ExternalIdentity | None:
        """Return the identity for ``(workspace_id, idp_subject)``, or ``None``.

        Tenant-scoped: filters on BOTH ``workspace_id`` and ``idp_subject`` so a
        subject can only ever resolve within its own workspace.
        """
        ws = (workspace_id or "").strip()
        subject = (idp_subject or "").strip()
        if not ws or not subject:
            return None
        stmt = (
            select(ExternalIdentity)
            .where(
                ExternalIdentity.workspace_id == ws,
                ExternalIdentity.idp_subject == subject,
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def get_by_email(
        self, workspace_id: str, email: str
    ) -> ExternalIdentity | None:
        """Return the workspace's identity for ``email`` (case-insensitive), or ``None``."""
        ws = (workspace_id or "").strip()
        normalized = (email or "").strip().lower()
        if not ws or not normalized:
            return None
        stmt = (
            select(ExternalIdentity)
            .where(
                ExternalIdentity.workspace_id == ws,
                func.lower(ExternalIdentity.email) == normalized,
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def create(
        self,
        *,
        user_id: str,
        workspace_id: str,
        idp_subject: str,
        email: str = "",
        provisioned: bool = True,
    ) -> ExternalIdentity:
        """Insert a new identity link and flush to obtain its id.

        Raises ``ValueError`` on a blank ``user_id`` / ``workspace_id`` /
        ``idp_subject`` so an unresolvable link can never be persisted. A duplicate
        ``(workspace_id, idp_subject)`` violates the UNIQUE constraint and surfaces
        as an ``IntegrityError`` on flush.
        """
        normalized_user = (user_id or "").strip()
        normalized_ws = (workspace_id or "").strip()
        normalized_subject = (idp_subject or "").strip()
        if not normalized_user:
            raise ValueError("user_id must be a non-empty string")
        if not normalized_ws:
            raise ValueError("workspace_id must be a non-empty string")
        if not normalized_subject:
            raise ValueError("idp_subject must be a non-empty string")

        identity = ExternalIdentity(
            user_id=normalized_user,
            workspace_id=normalized_ws,
            idp_subject=normalized_subject,
            email=str(email or "").strip(),
            provisioned=bool(provisioned),
        )
        self._session.add(identity)
        self._session.flush()  # populate identity.id without ending the transaction
        return identity

    def list_for_workspace(
        self, workspace_id: str, limit: int = 100, offset: int = 0
    ) -> list[ExternalIdentity]:
        """Return the workspace's identities, newest first, paginated (tenant-scoped)."""
        normalized = (workspace_id or "").strip()
        if not normalized:
            return []
        stmt = (
            select(ExternalIdentity)
            .where(ExternalIdentity.workspace_id == normalized)
            .order_by(ExternalIdentity.created_at.desc(), ExternalIdentity.id.desc())
            .limit(max(1, limit))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_owned(
        self, identity_id: str, workspace_id: str
    ) -> ExternalIdentity | None:
        """Return the identity only when it exists AND belongs to ``workspace_id``.

        Tenant isolation is enforced here so a SCIM caller can never read/patch an
        identity in another workspace by guessing its id; a foreign or missing id
        returns ``None``.
        """
        ws = (workspace_id or "").strip()
        if not ws:
            return None
        identity = self._session.get(ExternalIdentity, identity_id)
        if identity is None or identity.workspace_id != ws:
            return None
        return identity

    def set_provisioned(
        self, identity_id: str, workspace_id: str, provisioned: bool
    ) -> ExternalIdentity | None:
        """Flip an identity's ``provisioned`` flag (tenant-scoped); return the row.

        Returns ``None`` (touching nothing) when the identity does not exist or
        belongs to another workspace, so a SCIM caller can never (de)activate an
        identity outside its own tenant. Soft-disable — the row is retained.
        """
        identity = self.get_owned(identity_id, workspace_id)
        if identity is None:
            return None
        identity.provisioned = bool(provisioned)
        self._session.flush()
        return identity

    def update_email(
        self, identity_id: str, workspace_id: str, email: str
    ) -> ExternalIdentity | None:
        """Update an identity's denormalized ``email`` (tenant-scoped)."""
        identity = self.get_owned(identity_id, workspace_id)
        if identity is None:
            return None
        identity.email = str(email or "").strip()
        self._session.flush()
        return identity


# --------------------------------------------------------------------------- #
# Enterprise Billing Platform (Epic 3): subscriptions, metered usage, invoices.
# --------------------------------------------------------------------------- #
#: Subscription lifecycle statuses. Only ``active`` / ``trialing`` grant the
#: plan's entitlements; ``past_due`` / ``canceled`` fall back to base/free.
SUBSCRIPTION_STATUS_ACTIVE = "active"
SUBSCRIPTION_STATUS_TRIALING = "trialing"
SUBSCRIPTION_STATUS_PAST_DUE = "past_due"
SUBSCRIPTION_STATUS_CANCELED = "canceled"
SUBSCRIPTION_STATUSES: frozenset[str] = frozenset(
    {
        SUBSCRIPTION_STATUS_ACTIVE,
        SUBSCRIPTION_STATUS_TRIALING,
        SUBSCRIPTION_STATUS_PAST_DUE,
        SUBSCRIPTION_STATUS_CANCELED,
    }
)
#: The statuses under which a subscription's plan entitlements are LIVE. A
#: subscription in any other status is treated as if the workspace had none
#: (safe fallback to base/free) so a lapsed subscription never keeps granting a
#: premium extra — the #1 money-correctness invariant for entitlement gating.
SUBSCRIPTION_LIVE_STATUSES: frozenset[str] = frozenset(
    {SUBSCRIPTION_STATUS_ACTIVE, SUBSCRIPTION_STATUS_TRIALING}
)


class SubscriptionRepository:
    """Read + upsert for the per-workspace :class:`Subscription` singleton.

    Exactly ONE subscription exists per workspace (``workspace_id`` is UNIQUE), so
    :meth:`upsert` updates the existing row in place rather than inserting a
    duplicate and :meth:`get_for_workspace` resolves the singleton by tenant id.
    All reads are tenant-scoped — a blank ``workspace_id`` never matches — so a
    caller can never resolve another tenant's subscription.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_workspace(self, workspace_id: str) -> Subscription | None:
        """Return the workspace's subscription, or ``None`` when unset.

        A blank ``workspace_id`` never matches (returns ``None``) so an empty
        tenant id can never sweep up an unrelated row.
        """
        normalized = (workspace_id or "").strip()
        if not normalized:
            return None
        stmt = (
            select(Subscription)
            .where(Subscription.workspace_id == normalized)
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def get_by_provider_ref(self, provider: str, provider_ref: str) -> Subscription | None:
        """Resolve the row a provider subscription id belongs to (or ``None``).

        Used when a renewal event does not echo our metadata back: the provider
        id recorded at activation is then the only correlation handle. Blank
        inputs never match.
        """
        normalized_ref = (provider_ref or "").strip()
        normalized_provider = (provider or "").strip().lower()
        if not normalized_ref or not normalized_provider:
            return None
        stmt = (
            select(Subscription)
            .where(
                Subscription.provider == normalized_provider,
                Subscription.provider_ref == normalized_ref,
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def upsert(
        self,
        workspace_id: str,
        *,
        plan_key: str | None = None,
        provider: str | None = None,
        provider_ref: str | None = None,
        status: str | None = None,
        interval: str | None = None,
        seats: int | None = None,
        current_period_end=None,
    ) -> Subscription:
        """Create or update the workspace's subscription, returning the row.

        Only the non-``None`` keyword fields are applied — a partial update leaves
        the untouched columns as they were (or at their column default on first
        insert). ``status`` is validated against :data:`SUBSCRIPTION_STATUSES`
        (an unknown status is rejected rather than silently persisted, so the
        entitlement gate can trust it); ``seats`` is floored at 1. Raises
        ``ValueError`` on a blank ``workspace_id`` so an unattributable
        subscription can never be stored.
        """
        normalized = (workspace_id or "").strip()
        if not normalized:
            raise ValueError("workspace_id must be a non-empty string")

        row = self.get_for_workspace(normalized)
        if row is None:
            row = Subscription(workspace_id=normalized)
            self._session.add(row)

        if plan_key is not None:
            row.plan_key = str(plan_key or "").strip().lower() or "free"
        if provider is not None:
            row.provider = str(provider or "").strip().lower() or "stripe"
        if provider_ref is not None:
            row.provider_ref = str(provider_ref or "")
        if status is not None:
            normalized_status = str(status or "").strip().lower()
            if normalized_status not in SUBSCRIPTION_STATUSES:
                raise ValueError(f"unknown subscription status {status!r}")
            row.status = normalized_status
        if interval is not None:
            row.interval = str(interval or "").strip().lower() or "month"
        if seats is not None:
            row.seats = max(1, int(seats))
        if current_period_end is not None:
            row.current_period_end = current_period_end

        self._session.flush()
        return row

    def set_status(self, workspace_id: str, status: str) -> Subscription | None:
        """Set a workspace subscription's ``status`` (validated); return the row.

        Returns ``None`` (touching nothing) when the workspace has no
        subscription. Raises ``ValueError`` on an unknown status so a bad value
        can never reach the entitlement gate.
        """
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in SUBSCRIPTION_STATUSES:
            raise ValueError(f"unknown subscription status {status!r}")
        row = self.get_for_workspace(workspace_id)
        if row is None:
            return None
        row.status = normalized_status
        self._session.flush()
        return row


class MeteredUsageRepository:
    """Idempotent insert + tenant-scoped aggregation for :class:`MeteredUsage`.

    Backs usage-based billing: :meth:`record` inserts exactly one row per unique
    ``idempotency_key`` (a replay of the same metering event is swallowed, never
    double-counted), and :meth:`aggregate_for_period` sums usage per metric for a
    workspace's billing month. All reads are tenant-scoped so a caller can never
    read another tenant's usage.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_key(self, idempotency_key: str) -> MeteredUsage | None:
        """Return the usage row for ``idempotency_key``, or ``None``.

        A blank key never matches so an empty dedupe handle can never resolve an
        unrelated row.
        """
        normalized = (idempotency_key or "").strip()
        if not normalized:
            return None
        stmt = (
            select(MeteredUsage)
            .where(MeteredUsage.idempotency_key == normalized)
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def record(
        self,
        *,
        workspace_id: str,
        metric: str,
        quantity: int,
        period_ym: str,
        idempotency_key: str,
    ) -> tuple[MeteredUsage, bool]:
        """Insert one usage row IFF ``idempotency_key`` is new; never double-count.

        Returns ``(row, created)`` where ``created`` is ``True`` only on the first
        insert for this key. A replay of the same event returns the EXISTING row
        with ``created=False`` and inserts nothing — the ``UNIQUE`` constraint on
        ``idempotency_key`` is the durable guard, and the INSERT is wrapped in a
        SAVEPOINT so a concurrent racing insert's ``IntegrityError`` rolls back
        ONLY the failed insert (never the caller's outer transaction) and the
        existing row is re-read. ``quantity`` is floored non-negative so a bad
        caller can never decrement usage. Raises ``ValueError`` on a blank
        ``workspace_id`` / ``metric`` / ``period_ym`` / ``idempotency_key``.
        """
        ws = (workspace_id or "").strip()
        if not ws:
            raise ValueError("workspace_id must be a non-empty string")
        normalized_metric = (metric or "").strip().lower()
        if not normalized_metric:
            raise ValueError("metric must be a non-empty string")
        period = (period_ym or "").strip()
        if not period:
            raise ValueError("period_ym must be a non-empty string")
        key = (idempotency_key or "").strip()
        if not key:
            raise ValueError("idempotency_key must be a non-empty string")
        qty = max(0, int(quantity))

        existing = self.get_by_key(key)
        if existing is not None:
            return existing, False

        try:
            with self._session.begin_nested():
                row = MeteredUsage(
                    workspace_id=ws,
                    metric=normalized_metric,
                    quantity=qty,
                    period_ym=period,
                    idempotency_key=key,
                )
                self._session.add(row)
                self._session.flush()
            return row, True
        except IntegrityError:
            # A concurrent delivery won the race and inserted this key first; the
            # SAVEPOINT rolled back only our failed insert. Re-read the winner's
            # row and report it as NOT created so no double-count occurs.
            row = self.get_by_key(key)
            if row is None:
                raise
            return row, False

    def aggregate_for_period(
        self, workspace_id: str, period_ym: str
    ) -> dict[str, int]:
        """Return per-metric total usage for a workspace's billing month.

        Tenant-scoped ``SUM(quantity) GROUP BY metric`` over the composite
        ``(workspace_id, period_ym)`` index. Returns ``{metric: total}`` (empty
        when there is no usage). A blank ``workspace_id`` / ``period_ym`` returns
        an empty mapping so a blank filter can never sweep up unrelated rows.
        """
        ws = (workspace_id or "").strip()
        period = (period_ym or "").strip()
        if not ws or not period:
            return {}
        stmt = (
            select(
                MeteredUsage.metric,
                func.coalesce(func.sum(MeteredUsage.quantity), 0),
            )
            .where(
                MeteredUsage.workspace_id == ws,
                MeteredUsage.period_ym == period,
            )
            .group_by(MeteredUsage.metric)
        )
        return {
            str(metric): int(total or 0)
            for metric, total in self._session.execute(stmt).all()
        }


class InvoiceRepository:
    """CRUD + tenant-scoped listing for :class:`Invoice` / :class:`InvoiceLineItem`.

    Backs the invoicing surface: :meth:`create` writes an invoice plus its line
    items with the header amount recomputed as the exact integer sum of the lines
    (no floating-point drift), and :meth:`list_for_workspace` returns only that
    tenant's invoices. :meth:`revenue_since` powers the platform-admin revenue
    summary (the caller enforces the ``is_staff`` gate before reaching here).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: str,
        line_items: list[dict] | None = None,
        currency: str = "usd",
        status: str = "draft",
        provider_ref: str = "",
        period_start=None,
        period_end=None,
        amount_cents: int | None = None,
    ) -> Invoice:
        """Insert an invoice (and its lines) and flush to obtain its id.

        Each entry in ``line_items`` is a dict with ``description`` /
        ``quantity`` / ``amount_cents`` (the line's integer minor-unit total). The
        invoice header ``amount_cents`` is, by default, the exact integer SUM of
        the line ``amount_cents`` so the total can never drift from its lines; an
        explicit ``amount_cents`` overrides it (e.g. a provider-authoritative
        total). Raises ``ValueError`` on a blank ``workspace_id``.
        """
        ws = (workspace_id or "").strip()
        if not ws:
            raise ValueError("workspace_id must be a non-empty string")

        lines = list(line_items or [])
        summed = sum(max(0, int(li.get("amount_cents", 0) or 0)) for li in lines)
        header_amount = int(amount_cents) if amount_cents is not None else summed

        invoice = Invoice(
            workspace_id=ws,
            provider_ref=str(provider_ref or ""),
            amount_cents=header_amount,
            currency=str(currency or "usd").strip().lower() or "usd",
            status=str(status or "draft").strip().lower() or "draft",
            period_start=period_start,
            period_end=period_end,
        )
        self._session.add(invoice)
        self._session.flush()  # populate invoice.id

        for li in lines:
            self._session.add(
                InvoiceLineItem(
                    invoice_id=invoice.id,
                    description=str(li.get("description", "") or ""),
                    quantity=max(0, int(li.get("quantity", 1) or 0)),
                    amount_cents=max(0, int(li.get("amount_cents", 0) or 0)),
                )
            )
        self._session.flush()
        return invoice

    def get_owned(self, invoice_id: str, workspace_id: str) -> Invoice | None:
        """Return the invoice only when it exists *and* belongs to ``workspace_id``.

        Tenant isolation is enforced here so a caller can never read another
        tenant's invoice by guessing its id; a foreign or missing id returns
        ``None``.
        """
        invoice = self._session.get(Invoice, invoice_id)
        if invoice is None or invoice.workspace_id != (workspace_id or "").strip():
            return None
        return invoice

    def list_for_workspace(
        self, workspace_id: str, limit: int = 50, offset: int = 0
    ) -> list[Invoice]:
        """Return a workspace's invoices, newest first, paginated (tenant-scoped).

        A blank ``workspace_id`` never matches (returns ``[]``). ``limit`` is
        clamped to at least 1 and ``offset`` to at least 0 so a non-positive page
        never yields an invalid query.
        """
        normalized = (workspace_id or "").strip()
        if not normalized:
            return []
        stmt = (
            select(Invoice)
            .where(Invoice.workspace_id == normalized)
            .order_by(Invoice.created_at.desc(), Invoice.id.desc())
            .limit(max(1, limit))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_line_items(self, invoice_id: str) -> list[InvoiceLineItem]:
        """Return an invoice's line items, oldest first."""
        stmt = (
            select(InvoiceLineItem)
            .where(InvoiceLineItem.invoice_id == invoice_id)
            .order_by(InvoiceLineItem.created_at.asc(), InvoiceLineItem.id.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def revenue_since(self, cutoff, status: str = "paid") -> int:
        """Return total ``amount_cents`` across ALL tenants since ``cutoff``.

        Platform-admin aggregate (the caller enforces the ``is_staff`` gate
        first). Sums the header amount of invoices whose ``status`` matches
        (default ``paid`` — realized revenue) and whose ``created_at >= cutoff``.
        A falsy ``cutoff`` sums the whole history. Cross-tenant BY DESIGN — this is
        the only query in the billing layer that is not workspace-scoped, and it
        is reachable solely through the staff-gated service.
        """
        normalized_status = str(status or "").strip().lower()
        stmt = select(func.coalesce(func.sum(Invoice.amount_cents), 0))
        if normalized_status:
            stmt = stmt.where(Invoice.status == normalized_status)
        if cutoff is not None:
            stmt = stmt.where(Invoice.created_at >= cutoff)
        total = self._session.execute(stmt).scalar_one()
        return int(total or 0)


class WebhookSubscriptionRepository:
    """Tenant-scoped persistence for :class:`WebhookSubscription` (Enterprise API).

    Backs the customer webhook-subscription surface. Every read is filtered by
    ``workspace_id`` so a caller can never resolve, list, or revoke another
    tenant's subscription. The signing secret is supplied already-encrypted by the
    service (:mod:`app.services.webhook_subscriptions`) — this layer never sees the
    plaintext and never returns it. :meth:`revoke` is a soft disable (the row is
    retained for audit) so a subscription can be durably taken offline.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: str,
        url: str,
        event_types: list[str],
        secret_enc: str,
        enabled: bool = True,
    ) -> WebhookSubscription:
        """INSERT a subscription and flush to obtain its id.

        ``secret_enc`` is the ALREADY-ENCRYPTED signing secret (never plaintext) —
        the service encrypts before calling here so a plaintext key is never
        persisted. ``event_types`` is normalized to a fresh de-duplicated list.
        Raises ``ValueError`` on a blank ``workspace_id`` / ``url`` / ``secret_enc``
        so an unattributable or unusable subscription is never stored.
        """
        ws = (workspace_id or "").strip()
        if not ws:
            raise ValueError("workspace_id must be a non-empty string")
        normalized_url = (url or "").strip()
        if not normalized_url:
            raise ValueError("url must be a non-empty string")
        if not (secret_enc or "").strip():
            raise ValueError("secret_enc must be a non-empty string")

        # Fresh, order-preserving, de-duplicated list (never mutate the caller's).
        seen: set[str] = set()
        events: list[str] = []
        for raw in event_types or []:
            evt = str(raw or "").strip()
            if evt and evt not in seen:
                seen.add(evt)
                events.append(evt)

        row = WebhookSubscription(
            workspace_id=ws,
            url=normalized_url,
            event_types=events,
            secret_enc=secret_enc,
            enabled=bool(enabled),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get_by_id(self, subscription_id: str) -> WebhookSubscription | None:
        """Return a subscription by id WITHOUT a tenant filter (worker-internal).

        For the platform retry worker only, which already holds a delivery whose
        ``subscription_id`` is trusted. Tenant-facing reads MUST use
        :meth:`get_owned` (which enforces ``workspace_id``).
        """
        if not subscription_id:
            return None
        return self._session.get(WebhookSubscription, subscription_id)

    def get_owned(
        self, subscription_id: str, workspace_id: str
    ) -> WebhookSubscription | None:
        """Return the subscription only when it exists AND belongs to the tenant.

        Tenant isolation is enforced here so a caller can never read another
        tenant's subscription by guessing its id; a foreign or missing id (or a
        blank ``workspace_id``) returns ``None``.
        """
        ws = (workspace_id or "").strip()
        if not subscription_id or not ws:
            return None
        row = self._session.get(WebhookSubscription, subscription_id)
        if row is None or row.workspace_id != ws:
            return None
        return row

    def list_for_workspace(
        self, workspace_id: str, limit: int = 100, offset: int = 0
    ) -> list[WebhookSubscription]:
        """Return a workspace's subscriptions, newest first, paginated (scoped)."""
        ws = (workspace_id or "").strip()
        if not ws:
            return []
        stmt = (
            select(WebhookSubscription)
            .where(WebhookSubscription.workspace_id == ws)
            .order_by(
                WebhookSubscription.created_at.desc(),
                WebhookSubscription.id.desc(),
            )
            .limit(max(1, limit))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_enabled_for_event(
        self, workspace_id: str, event_type: str
    ) -> list[WebhookSubscription]:
        """Return the tenant's ENABLED subscriptions that match ``event_type``.

        Tenant-scoped and enabled-only. The ``event_types`` JSON membership test is
        applied in Python (portable across SQLite/Postgres) after the indexed
        ``workspace_id`` + ``enabled`` filter. A blank ``workspace_id`` /
        ``event_type`` returns ``[]`` so a blank filter can never sweep up rows.
        """
        ws = (workspace_id or "").strip()
        evt = (event_type or "").strip()
        if not ws or not evt:
            return []
        stmt = (
            select(WebhookSubscription)
            .where(
                WebhookSubscription.workspace_id == ws,
                WebhookSubscription.enabled.is_(True),
            )
            .order_by(WebhookSubscription.created_at.asc())
        )
        rows = self._session.execute(stmt).scalars().all()
        return [r for r in rows if evt in (r.event_types or [])]

    def revoke(
        self, subscription_id: str, workspace_id: str
    ) -> WebhookSubscription | None:
        """Soft-disable a tenant's subscription; return it (or ``None`` if foreign).

        Tenant-scoped: a subscription that does not belong to ``workspace_id`` is
        never touched (returns ``None``). Idempotent — revoking an
        already-disabled subscription is a no-op that still returns the row.
        """
        row = self.get_owned(subscription_id, workspace_id)
        if row is None:
            return None
        row.enabled = False
        self._session.flush()
        return row


class WebhookDeliveryRepository:
    """Idempotent insert + retry bookkeeping for :class:`WebhookDelivery`.

    :meth:`create_idempotent` inserts exactly one row per ``(subscription_id,
    event_id)`` — a replay of the same event is swallowed (never double-delivered)
    via the ``UNIQUE`` constraint, with the INSERT wrapped in a SAVEPOINT so a
    concurrent racing insert rolls back only the failed insert. :meth:`record_attempt`
    advances the retry state after each delivery try, and :meth:`list_pending`
    feeds the capped-backoff retry worker.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_sub_event(
        self, subscription_id: str, event_id: str
    ) -> WebhookDelivery | None:
        """Return the delivery for ``(subscription_id, event_id)``, or ``None``."""
        sub = (subscription_id or "").strip()
        evt = (event_id or "").strip()
        if not sub or not evt:
            return None
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.subscription_id == sub,
                WebhookDelivery.event_id == evt,
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def create_idempotent(
        self,
        *,
        subscription_id: str,
        event_type: str,
        event_id: str,
        payload: dict,
    ) -> tuple[WebhookDelivery, bool]:
        """Insert one delivery IFF ``(subscription_id, event_id)`` is new.

        Returns ``(row, created)`` where ``created`` is ``True`` only on the first
        insert. A replay of the same event returns the EXISTING row with
        ``created=False`` and inserts nothing — the ``UNIQUE`` constraint is the
        durable guard and the INSERT runs in a SAVEPOINT so a concurrent insert's
        ``IntegrityError`` rolls back only the failed insert and the winner's row
        is re-read. Raises ``ValueError`` on a blank ``subscription_id`` /
        ``event_type`` / ``event_id``.
        """
        sub = (subscription_id or "").strip()
        if not sub:
            raise ValueError("subscription_id must be a non-empty string")
        etype = (event_type or "").strip()
        if not etype:
            raise ValueError("event_type must be a non-empty string")
        eid = (event_id or "").strip()
        if not eid:
            raise ValueError("event_id must be a non-empty string")

        existing = self.get_by_sub_event(sub, eid)
        if existing is not None:
            return existing, False

        try:
            with self._session.begin_nested():
                row = WebhookDelivery(
                    subscription_id=sub,
                    event_type=etype,
                    event_id=eid,
                    payload=dict(payload or {}),
                    status="pending",
                    attempts=0,
                )
                self._session.add(row)
                self._session.flush()
            return row, True
        except IntegrityError:
            # A concurrent dispatch won the race for this (sub, event_id); the
            # SAVEPOINT rolled back only our failed insert. Re-read the winner.
            row = self.get_by_sub_event(sub, eid)
            if row is None:
                raise
            return row, False

    def record_attempt(
        self,
        delivery: WebhookDelivery,
        *,
        delivered: bool,
        response_code: int | None,
        attempted_at: datetime,
        exhausted: bool,
    ) -> WebhookDelivery:
        """Advance a delivery's retry state after one attempt and flush.

        Increments ``attempts``, stamps ``last_attempt_at`` / ``response_code``,
        and moves ``status`` to ``delivered`` on success, ``failed`` when the retry
        budget is ``exhausted``, else leaves it ``pending`` for a later retry.
        """
        delivery.attempts = int(delivery.attempts or 0) + 1
        delivery.last_attempt_at = attempted_at
        delivery.response_code = response_code
        if delivered:
            delivery.status = "delivered"
        elif exhausted:
            delivery.status = "failed"
        else:
            delivery.status = "pending"
        self._session.flush()
        return delivery

    def list_pending(self, limit: int = 100) -> list[WebhookDelivery]:
        """Return pending deliveries (oldest attempted first) for the retry worker.

        Ordered so the longest-waiting deliveries are retried first
        (``last_attempt_at`` ascending, NULLs — never attempted — via ``created_at``).
        """
        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.status == "pending")
            .order_by(
                WebhookDelivery.last_attempt_at.asc(),
                WebhookDelivery.created_at.asc(),
            )
            .limit(max(1, limit))
        )
        return list(self._session.execute(stmt).scalars().all())


class RetentionPolicyRepository:
    """CRUD for :class:`RetentionPolicy` singleton rows (Compliance, Epic 5).

    Exactly one policy per workspace (``workspace_id`` is the PK), so
    :meth:`upsert` updates the single row in place. Authorization (only a
    workspace owner/admin may set a policy) is enforced one layer up in
    :mod:`app.services.compliance.retention` via ``require_permission`` — this
    class is the pure persistence layer.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, workspace_id: str) -> RetentionPolicy | None:
        """Return a workspace's retention policy, or ``None`` if unset."""
        normalized = (workspace_id or "").strip()
        if not normalized:
            return None
        return self._session.get(RetentionPolicy, normalized)

    def upsert(
        self,
        workspace_id: str,
        jobs_retention_days: int | None = None,
        assets_retention_days: int | None = None,
    ) -> RetentionPolicy:
        """Insert or update a workspace's retention window; return the row.

        ``None`` for either window means **keep forever** (that dimension is
        never swept). Non-negative day counts are enforced at the service
        boundary. The single row is updated in place on a re-set so a workspace
        never accumulates conflicting policies.
        """
        policy = self._session.get(RetentionPolicy, workspace_id)
        if policy is None:
            policy = RetentionPolicy(
                workspace_id=workspace_id,
                jobs_retention_days=jobs_retention_days,
                assets_retention_days=assets_retention_days,
            )
            self._session.add(policy)
        else:
            policy.jobs_retention_days = jobs_retention_days
            policy.assets_retention_days = assets_retention_days
        self._session.flush()
        return policy

    def list_all(self) -> list[RetentionPolicy]:
        """Return every configured retention policy (drives the periodic sweep)."""
        stmt = select(RetentionPolicy).order_by(RetentionPolicy.workspace_id.asc())
        return list(self._session.execute(stmt).scalars().all())


class ConsentRepository:
    """APPEND-ONLY persistence for :class:`ConsentRecord` rows (Compliance, Epic 5).

    A consent decision inserts a NEW row (history is never mutated); the current
    decision for a ``(user_id, kind)`` pair is the newest row. Every read is
    strictly scoped to the requesting ``user_id`` so a caller can never read
    another user's consent trail.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, user_id: str, kind: str, granted: bool, version: str = ""
    ) -> ConsentRecord:
        """Append one immutable consent record and flush to obtain its id."""
        row = ConsentRecord(
            user_id=user_id,
            kind=(kind or "").strip().lower(),
            granted=bool(granted),
            version=str(version or ""),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get_latest(self, user_id: str, kind: str) -> ConsentRecord | None:
        """Return the NEWEST consent row for a ``(user_id, kind)`` pair, or None.

        Owner-scoped: filters on BOTH ``user_id`` and ``kind`` so a caller can
        never read another user's decision. A blank ``user_id`` never matches.
        """
        normalized = (user_id or "").strip()
        if not normalized:
            return None
        stmt = (
            select(ConsentRecord)
            .where(
                ConsentRecord.user_id == normalized,
                ConsentRecord.kind == (kind or "").strip().lower(),
            )
            .order_by(ConsentRecord.created_at.desc(), ConsentRecord.id.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def list_for_user(self, user_id: str) -> list[ConsentRecord]:
        """Return a user's full consent trail, oldest first (owner-scoped)."""
        normalized = (user_id or "").strip()
        if not normalized:
            return []
        stmt = (
            select(ConsentRecord)
            .where(ConsentRecord.user_id == normalized)
            .order_by(ConsentRecord.created_at.asc(), ConsentRecord.id.asc())
        )
        return list(self._session.execute(stmt).scalars().all())


class ErasureRequestRepository:
    """CRUD + lifecycle for :class:`ErasureRequest` rows (GDPR Art. 17, Epic 5).

    Tracks a user's right-to-erasure request through ``requested -> processing
    -> completed``. Every mutation is scoped to the owning ``user_id`` so a
    caller can never advance or read another user's erasure request.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, user_id: str, scope: str = "user") -> ErasureRequest:
        """Insert a new ``requested`` erasure request and flush to obtain its id."""
        row = ErasureRequest(
            user_id=user_id,
            status="requested",
            scope=str(scope or "user"),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, request_id: str) -> ErasureRequest | None:
        """Return an erasure request by id, or ``None``."""
        return self._session.get(ErasureRequest, request_id)

    def get_open_for_user(self, user_id: str) -> ErasureRequest | None:
        """Return the newest not-yet-completed request for a user, or ``None``.

        Used to make erasure idempotent: a re-request reuses an existing open
        row rather than accumulating duplicates. Owner-scoped.
        """
        normalized = (user_id or "").strip()
        if not normalized:
            return None
        stmt = (
            select(ErasureRequest)
            .where(
                ErasureRequest.user_id == normalized,
                ErasureRequest.status != "completed",
            )
            .order_by(ErasureRequest.requested_at.desc(), ErasureRequest.id.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def list_for_user(self, user_id: str) -> list[ErasureRequest]:
        """Return a user's erasure requests, newest first (owner-scoped)."""
        normalized = (user_id or "").strip()
        if not normalized:
            return []
        stmt = (
            select(ErasureRequest)
            .where(ErasureRequest.user_id == normalized)
            .order_by(ErasureRequest.requested_at.desc(), ErasureRequest.id.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def set_status(
        self, request_id: str, status: str, completed_at: datetime | None = None
    ) -> ErasureRequest | None:
        """Advance a request's ``status`` (and stamp ``completed_at``); return it.

        Returns ``None`` when the request does not exist. When ``status`` is
        ``completed`` the ``completed_at`` timestamp is recorded (defaulting to
        ``now`` in UTC when not supplied).
        """
        row = self._session.get(ErasureRequest, request_id)
        if row is None:
            return None
        row.status = status
        if status == "completed":
            row.completed_at = completed_at or datetime.now(timezone.utc)
        self._session.flush()
        return row


__all__ = [
    "AdminRepository",
    "ConsentRepository",
    "ErasureRequestRepository",
    "RetentionPolicyRepository",
    "ApiKeyUsageRepository",
    "AssetRepository",
    "AuditLogRepository",
    "CreatorFollowRepository",
    "CreditRepository",
    "ExternalIdentityRepository",
    "InvoiceRepository",
    "JobPerformanceRepository",
    "JobRepository",
    "MarketplaceRepository",
    "MeteredUsageRepository",
    "NotificationRepository",
    "SSOConnectionRepository",
    "SSO_PROTOCOLS",
    "SUBSCRIPTION_LIVE_STATUSES",
    "SUBSCRIPTION_STATUSES",
    "SavedIdeaRepository",
    "ScheduledPublishRepository",
    "ScimTokenRepository",
    "SecurityPolicyRepository",
    "ShareLinkRepository",
    "SocialAccountRepository",
    "SubscriptionRepository",
    "TemplateRatingRepository",
    "UserApiKeyRepository",
    "UserBrandRepository",
    "UserPresetRepository",
    "UserRepository",
    "UserVoiceRepository",
    "WebhookDeliveryRepository",
    "WebhookSubscriptionRepository",
    "WorkspaceRepository",
]
