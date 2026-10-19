"""ReelForge ORM models (SQLAlchemy 2.0 ``Mapped[]`` typing).

Per INTEGRATION_CONTRACT.md §4.2. Design rules:

* All non-sequence primary keys are 32-char uuid hex strings (``_uuid``).
* All timestamps are ``TIMESTAMP(timezone=True)`` with a server-side ``now()``.
* ``job_events`` and ``credit_ledger`` are **append-only** audit trails —
  rows are never mutated after insert; a running balance is materialized in
  ``CreditLedger.balance_after`` for O(1) reads.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db.base import Base, jsonb_variant


def _uuid() -> str:
    """Generate a 32-char hex uuid4 primary key."""
    return uuid.uuid4().hex


def _share_token() -> str:
    """Generate an unguessable, URL-safe public share token.

    ``secrets.token_urlsafe(16)`` yields 16 random bytes (128 bits of entropy)
    encoded as a ~22-char URL-safe string — well beyond guessable, so a public
    share link can never be enumerated. Used as the default for
    :attr:`ShareLink.token`; the column is ``UNIQUE`` so a (astronomically
    unlikely) collision surfaces as an ``IntegrityError`` rather than silently
    aliasing two links.
    """
    return secrets.token_urlsafe(16)


class User(Base):
    """A ReelForge account. ``credits`` is a denormalized cache of the ledger."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(
        String(320), unique=True, index=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(200), default="")
    # PUBLIC CREATOR PROFILE (Creator Profiles + Follow Graph). Both columns are
    # nullable and default to NULL so existing rows and prior tests are unaffected
    # (the ADD COLUMN is safe on an already-populated users table). ``handle`` is a
    # creator's chosen public vanity slug used to address their profile
    # (``/creators/<handle>``); it is UNIQUE (multiple NULLs are allowed on both
    # SQLite and Postgres, mirroring ``referral_code``) so an unclaimed handle
    # simply stays NULL while a claimed one resolves to exactly one owner. ``bio``
    # is a short, free-text public blurb. Neither is a private/financial field —
    # both are safe to expose on a public profile / leaderboard.
    handle: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, default=None
    )
    bio: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # sha256 hex digest of the user's raw API key (never store the raw key)
    api_key_hash: Mapped[str] = mapped_column(String(128), default="")
    credits: Mapped[int] = mapped_column(Integer, default=0)
    # PLATFORM ADMIN flag (Enterprise Access & Governance). ``True`` marks a
    # ReelForge *staff* operator who may reach the platform-admin surface
    # (:mod:`app.services.admin` — cross-tenant user/workspace/job listing +
    # impersonation). This is HARD-GATED and deliberately SEPARATE from the
    # per-workspace roles: a workspace ``owner`` is not a platform admin, and a
    # platform admin gains nothing inside a workspace they are not a member of.
    # Additive + defaulted ``False`` (``server_default`` '0') so the ADD COLUMN
    # is safe on an already-populated users table, every existing row backfills
    # to a NON-staff account, and prior tests are unaffected.
    is_staff: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    # Phase-7 (growth) referral loop. Both columns are nullable and default to
    # NULL so existing rows and prior tests are unaffected — the code is
    # populated lazily on first share (``UserRepository.set_referral_code``) and
    # ``referred_by`` records the referrer's ``user_id`` when a code is redeemed.
    # ``referral_code`` is UNIQUE (multiple NULLs are allowed on both SQLite and
    # Postgres) so it can be looked up directly by ``get_by_referral_code``.
    referral_code: Mapped[str | None] = mapped_column(
        String(16), unique=True, nullable=True, default=None
    )
    referred_by: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    jobs: Mapped[list[Job]] = relationship(back_populates="user")
    presets: Mapped[list[UserPreset]] = relationship(back_populates="user")


class JobRequest(Base):
    """Durable idempotency record for ``POST /jobs``.

    The unique ``(user_id, idempotency_key)`` pair is the money-path guard: a
    network retry cannot create a second job or debit credits a second time.
    ``request_hash`` prevents a client from accidentally reusing a key for a
    different payload, while ``response_data`` lets a replay receive the exact
    creation response without re-enqueuing the pipeline.
    """

    __tablename__ = "job_requests"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_job_requests_user_idempotency_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Job(Base):
    """A single avatar-reel render job and its per-stage status map."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # Phase-10 (batch variant review): the shared id linking the N jobs a single
    # ``POST /jobs {variants:N}`` request fans out to, so they can be reviewed
    # together. Nullable + indexed: a single-variant job (``variants == 1``)
    # leaves this NULL (it belongs to no batch), while every job in an N-variant
    # request shares one ``batch_id`` (a 32-char uuid hex). NULL default keeps the
    # ADD COLUMN safe on an already-populated jobs table and existing rows / prior
    # tests unaffected. Indexed so ``list_by_batch`` is an O(index) lookup.
    batch_id: Mapped[str | None] = mapped_column(
        String(32), index=True, nullable=True, default=None
    )
    kind: Mapped[str] = mapped_column(String(40), default="avatar_reel")
    # Reuses MPT TASK_STATE_* integers (const.py): PROCESSING=4, COMPLETE=1, FAILED=-1
    state: Mapped[int] = mapped_column(Integer, default=4, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    # per-stage status map, e.g. {"script": "complete", "tts": "running", ...}
    stages: Mapped[dict] = mapped_column(JSON, default=dict)
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # ReelForgeParams dump
    failed_stage: Mapped[str] = mapped_column(String(40), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    celery_task_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    result_key: Mapped[str] = mapped_column(String(512), default="")  # final R2 key
    # Phase-6 (Creator Studio) artifacts / config. All optional and defaulted to
    # "" so existing rows and prior tests are unaffected. ``server_default`` is
    # declared so the NOT NULL ADD COLUMN is safe on an already-populated jobs
    # table (existing rows backfill to '') and Alembic autogenerate
    # (``compare_server_default=True``) does not report spurious drift.
    poster_key: Mapped[str] = mapped_column(
        String(512), default="", server_default=text("''"), nullable=False
    )  # R2 key of the generated poster/thumbnail frame
    preview_key: Mapped[str] = mapped_column(
        String(512), default="", server_default=text("''"), nullable=False
    )  # R2 key of the low-res preview clip
    webhook_url: Mapped[str] = mapped_column(
        String(1024), default="", server_default=text("''"), nullable=False
    )  # optional completion-notification callback URL
    # The finalized narration script for this job. Persisted so an existing job
    # can be re-run or dubbed into other languages (multi-language dubbing:
    # translate this script, then re-run the pipeline) and shown in the UI.
    # Nullable per the ADD COLUMN contract — existing rows backfill to '' via the
    # ``server_default`` while the ORM default keeps new inserts at '' — so the
    # migration is safe on an already-populated jobs table and Alembic
    # autogenerate does not report spurious drift.
    script: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=True
    )
    # The R2 key of the latest generated cover/thumbnail image (Cover /
    # Thumbnail Generator). A creator renders a 1080x1920 JPG — the job's poster
    # frame (``poster_key``, else a gradient) with the HOOK overlaid as a bold
    # headline in a chosen style — which is uploaded to R2 and its key stored
    # here. Regenerable: a new headline/style simply overwrites this key.
    # Nullable per the ADD COLUMN contract — existing rows backfill to '' via the
    # ``server_default`` while the ORM default keeps new inserts at '' — so the
    # migration is safe on an already-populated jobs table and Alembic
    # autogenerate does not report spurious drift.
    cover_key: Mapped[str] = mapped_column(
        String(512), default="", server_default=text("''"), nullable=True
    )
    # Library management (rename / archive / soft delete). ``title`` is the
    # owner's display name for the reel ('' -> clients fall back to the hook).
    # ``archived_at`` hides a reel from the default library view; ``deleted_at``
    # soft-deletes it (hidden everywhere, rows kept because job_events, assets,
    # the credit ledger, publishes and shares reference ``jobs.id``).
    title: Mapped[str] = mapped_column(
        String(200), default="", server_default=text("''"), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="jobs")
    events: Mapped[list[JobEvent]] = relationship(back_populates="job")
    assets: Mapped[list[Asset]] = relationship(back_populates="job")


class JobEvent(Base):
    """Append-only telemetry / audit trail row for a job stage transition."""

    __tablename__ = "job_events"

    # BigInteger on Postgres/Neon; INTEGER on SQLite so autoincrement works in
    # the test DB (SQLite only auto-increments an INTEGER PRIMARY KEY column).
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id"), index=True, nullable=False
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # REELFORGE_STAGE_*
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # Per-job unit economics (CTO plan §0: "unit economics from job #1").
    # ``cost_usd`` is the estimated USD spend attributed to this stage event and
    # ``duration_ms`` its wall-clock duration. Both default to 0 so historical /
    # non-cost events remain valid and the table stays append-only.
    # ``server_default`` mirrors migration 8d33fcd0b532 (both columns use '0')
    # so the NOT NULL ADD COLUMN is safe on the populated append-only table and
    # Alembic autogenerate does not produce spurious DROP DEFAULT drift.
    cost_usd: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0"), nullable=False
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped[Job] = relationship(back_populates="events")


class Asset(Base):
    """A stored artifact (screen | audio | avatar | ass | final | upload) in R2."""

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id"), index=True, nullable=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40))  # screen|audio|avatar|ass|final|upload
    r2_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped[Job] = relationship(back_populates="assets")


class AvatarPreset(Base):
    """A saved avatar/voice preset. ``user_id`` NULL means a global preset."""

    __tablename__ = "avatar_presets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )  # null => global preset
    provider: Mapped[str] = mapped_column(String(40), default="heygen")
    provider_avatar_id: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    voice_name: Mapped[str] = mapped_column(String(120), default="")  # "elevenlabs:<id>"
    thumbnail_url: Mapped[str] = mapped_column(String(512), default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # background, style, dimension
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BrollPreset(Base):
    """A curated AI B-roll *motion preset* (Higgsfield-style studio primitive).

    A preset bundles a starter ``prompt_template`` + generation ``default_params``
    (and optionally a specific comfyui-deploy ``workflow_id``) under a friendly
    ``name`` + ``thumbnail_url`` so a creator picks a motion style instead of
    writing a prompt from scratch. ``user_id`` NULL means a GLOBAL curated preset
    visible to everyone; a non-NULL ``user_id`` scopes a private/user preset.
    ``is_public`` additionally lets a user share their own preset (the shareable
    preset primitive). Mirrors :class:`AvatarPreset` — an opaque JSON
    ``default_params`` blob keeps new knobs migration-free.
    """

    __tablename__ = "broll_presets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )  # null => global curated preset
    provider: Mapped[str] = mapped_column(
        String(40), default="comfyui", server_default=text("'comfyui'"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(
        String(128), default="", server_default=text("''"), nullable=False
    )  # "" => config default
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(
        String(512), default="", server_default=text("''"), nullable=False
    )
    mode: Mapped[str] = mapped_column(
        String(8), default="t2v", server_default=text("'t2v'"), nullable=False
    )  # t2v | i2v
    prompt_template: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    thumbnail_url: Mapped[str] = mapped_column(
        String(512), default="", server_default=text("''"), nullable=False
    )
    default_params: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserPreset(Base):
    """A user-saved "brand kit" (Phase-7 growth): a named bundle of the render
    knobs a creator reuses across jobs (avatar, voice, layout, caption style,
    background music, language).

    Append-friendly: rows are inserted and deleted but the JSON ``config`` blob
    is treated as an opaque, replace-on-edit value rather than mutated in place,
    so new config keys can be added without a schema migration.
    """

    __tablename__ = "user_presets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # When set, this preset is SHARED to a workspace so every member sees it
    # (a "brand kit" shared across a team); when NULL it is private to
    # ``user_id``. Indexed so "presets shared to a workspace" is an O(index)
    # lookup. The owning ``user_id`` is always retained for attribution.
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Opaque brand-kit config, e.g. {"avatar_id", "voice_name", "layout",
    # "caption_style", "music_id", "language"}. Kept as JSON so the shape can
    # grow without a migration.
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="presets")


class UserVoice(Base):
    """A creator's cloned "brand voice" (Phase-11 brand voice / voice cloning).

    A user uploads a short (30-60s) voice sample which ElevenLabs Instant Voice
    Clone turns into a private provider voice. The resulting voice is selectable
    as a reel narrator via ``voice_name = "elevenlabs:<provider_voice_id>"`` —
    the format already handled by ``app/services/voice.py::tts()``.

    CONSENT is mandatory: ``consent`` records the creator's attestation that they
    own or are authorized to use the sampled voice. It defaults to ``False`` so a
    row is never treated as consented unless the attestation is explicitly stored.
    """

    __tablename__ = "user_voices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), default="elevenlabs")
    # The provider-side voice id (e.g. ElevenLabs voice_id). Indexed so a job's
    # ``elevenlabs:<provider_voice_id>`` narrator can be resolved back to its
    # owning row. Defaults to '' for a row created before the clone completes
    # (``status == "processing"``).
    provider_voice_id: Mapped[str] = mapped_column(
        String(120), index=True, default=""
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    # R2 object key of the uploaded voice sample (via storage.r2). Empty until
    # the sample is stored.
    sample_key: Mapped[str] = mapped_column(String(512), default="")
    # Mandatory ownership/authorization attestation (see class docstring).
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    # ready | processing | failed
    status: Mapped[str] = mapped_column(String(20), default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserBrand(Base):
    """A creator's per-user "brand watermark" settings (Brand Watermark feature).

    A creator uploads a transparent PNG logo (stored in R2 via the existing
    presign flow) which the pure-FFmpeg compose stage overlays onto every reel
    at a chosen corner + opacity. Exactly ONE row exists per user — ``user_id``
    is ``UNIQUE`` (and indexed) so the settings are a singleton the render
    pipeline reads by owner id, and :class:`UserBrandRepository` upserts it in
    place rather than accumulating rows.

    The defaults describe a sensible enabled watermark (``bottom_right`` at 85%
    opacity) so a creator who only uploads a logo immediately gets it applied.
    ``enabled`` gates whether the watermark is applied by default; a job can
    still override/disable it via its ``ReelForgeParams`` (see
    ``reelforge.stage_compose``). ``logo_key`` is the R2 object key of the
    uploaded PNG and defaults to '' until one is uploaded (an empty key means
    "no watermark", even when ``enabled`` is True).
    """

    __tablename__ = "user_brands"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Exactly one brand row per user: UNIQUE so an upsert can never create a
    # second row, and indexed so the render pipeline resolves it by owner id in
    # an O(index) lookup.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True, nullable=False
    )
    # R2 object key of the uploaded transparent PNG logo. '' => no watermark.
    logo_key: Mapped[str] = mapped_column(
        String(512), default="", server_default=text("''"), nullable=False
    )
    # Overlay corner: bottom_right | bottom_left | top_right | top_left.
    position: Mapped[str] = mapped_column(
        String(20), default="bottom_right",
        server_default=text("'bottom_right'"), nullable=False,
    )
    # Overlay opacity in [0.0, 1.0] (colorchannelmixer aa=<opacity>).
    opacity: Mapped[float] = mapped_column(
        Float, default=0.85, server_default=text("0.85"), nullable=False
    )
    # Whether the watermark is applied by default (a job may still disable it).
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CreditLedger(Base):
    """Append-only credit ledger. Balance == SUM(delta); cached in balance_after."""

    __tablename__ = "credit_ledger"

    # BigInteger on Postgres/Neon; INTEGER on SQLite so autoincrement works in
    # the test DB (SQLite only auto-increments an INTEGER PRIMARY KEY column).
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    # Personal-pool rows carry the owning ``user_id``; workspace-pool rows may
    # have a NULL ``user_id`` (system grant) or record the actor's id purely for
    # audit. Nullable so a workspace-pool row can exist without a personal owner.
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    # When set, this ledger row belongs to a *workspace* shared credit pool
    # (SUM of deltas == the pool balance); when NULL the row belongs to the
    # ``user_id`` personal pool. A row never counts toward both balances:
    # personal reads filter ``workspace_id IS NULL`` and pool reads filter
    # ``workspace_id == X``. Indexed for O(index) pool-balance aggregation.
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id"), index=True, nullable=True
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)  # +grant / -debit
    # signup | purchase | job_debit | refund | workspace_grant | workspace_debit
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SavedIdea(Base):
    """A SPARK "AI Idea Engine" concept a creator saved for later (Phase-18).

    SPARK turns a creator's app/niche description into N ready-to-shoot viral
    UGC video concepts. Any concept can be persisted here so the creator can
    revisit it and later one-click "Make this" (mapping the idea onto
    ``POST /jobs``). The full concept dict is stored opaquely in ``payload`` so
    the idea schema (hook / angle / format / script_outline / suggested_layout /
    suggested_caption_style / language / est_duration_s) can grow without a
    schema migration; ``title`` and ``hook`` are denormalized out of it as
    indexed/displayable columns for cheap list rendering.

    A brand-new, append-friendly table: rows are inserted and deleted but the
    ``payload`` blob is treated as an opaque, replace-on-edit value rather than
    mutated in place. ``user_id`` is indexed for owner-scoped listing.
    """

    __tablename__ = "saved_ideas"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), default="")
    hook: Mapped[str] = mapped_column(String(300), default="")
    # The full opaque idea dict (see class docstring). Kept as JSON so the shape
    # can grow without a migration.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Notification(Base):
    """An in-app notification surfaced in the user's notification center (bell).

    The in-app counterpart to the external webhook (``app/services/webhooks.py``):
    the server emits a row on lifecycle / growth events — ``job_complete`` (with
    ``job_id`` + result), ``job_failed`` (with ``error``), ``low_credits``
    (balance below a threshold) and ``referral_earned`` (credits from a
    referral) — and the client renders an unread badge + list.

    A brand-new, append-friendly table: rows are inserted, flipped to ``read``,
    and (optionally) deleted, but the opaque ``data`` JSON blob is treated as a
    replace-on-edit value rather than mutated in place, so the event payload
    shape (e.g. ``job_id``, ``result_key``, ``error``, ``balance``, ``amount``)
    can grow without a schema migration.

    ``read`` defaults to ``False`` so a freshly emitted notification always
    counts toward the unread badge. A composite ``(user_id, read)`` index backs
    the hot ``unread_count`` / ``unread_only`` list queries, and ``created_at``
    is indexed so the newest-first list ordering is an O(index) scan.
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # job_complete | job_failed | low_credits | referral_earned
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    body: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    # Opaque per-event payload (see class docstring). Kept as JSON so the shape
    # can grow without a migration.
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    read: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Composite index backing the hot unread_count / unread_only list queries
    # (filter on user_id AND read together).
    __table_args__ = (
        Index("ix_notifications_user_id_read", "user_id", "read"),
    )


class PushToken(Base):
    """A device's Expo push token for out-of-app render notifications.

    The out-of-app counterpart to :class:`Notification`: where a notification
    row surfaces in the in-app bell, this table lets the server deliver a native
    push (via Expo's push service) so a finished render reaches the user even
    when the app is backgrounded.

    Registered by the mobile client (``POST /me/push-tokens``) keyed by the
    stable per-install ``install_id`` so re-registration UPSERTS — refreshing the
    token for that install — rather than piling up duplicate rows. ``token`` is
    the opaque ``ExponentPushToken[...]`` string Expo maps to the device's
    APNs/FCM token; it is **sensitive** and is never logged.

    ``user_id`` is nullable (a token may be seen before its owner is resolved)
    and carries a get-or-create account once known. When Expo reports a token is
    no longer valid (``DeviceNotRegistered``) the row is flipped
    ``is_active=False`` rather than deleted, so the install↔token history is
    preserved while the dead token drops out of every future send. A composite
    ``(user_id, is_active)`` index backs the hot "active tokens for this owner"
    lookup the job-completion path runs.
    """

    __tablename__ = "push_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Stable per-install id (mobile SecureStore) — the UPSERT key, UNIQUE so each
    # install owns exactly one row and a rotated token refreshes it in place.
    install_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    # Opaque ExponentPushToken[...] string (SENSITIVE — never logged).
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    platform: Mapped[str] = mapped_column(
        String(16), default="", server_default=text("''"), nullable=False
    )
    # The account that registered this install (nullable; get-or-create).
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Composite index backing the hot "active tokens for this owner" lookup.
    __table_args__ = (
        Index("ix_push_tokens_user_id_is_active", "user_id", "is_active"),
    )


class ScheduledPublish(Base):
    """A finished reel queued to auto-publish to social platforms at a future
    UTC time (Scheduled Publishing).

    A creator schedules an already-rendered, *complete* job to be cross-posted
    (tiktok | instagram | youtube_shorts, through the owner's native OAuth
    connections) at ``scheduled_at``. A background due-runner (Celery beat, every minute) claims
    due ``pending`` rows, publishes them, and flips them to ``published`` or
    ``failed``. Users can list and cancel their still-``pending`` schedules.

    Lifecycle (``status``): ``pending`` -> ``publishing`` (claimed by a runner)
    -> ``published`` | ``failed``; a still-``pending`` row may be flipped to
    ``canceled`` by its owner. ``status`` is indexed so the hot due-claim query
    (``status='pending' AND scheduled_at<=now``) is an O(index) scan; a guarded
    ``UPDATE ... WHERE status='pending'`` flip makes the claim safe against two
    concurrent runners.

    A brand-new table: rows are inserted and their ``status`` / ``attempts`` /
    ``result`` / ``error`` are mutated in place by the runner, but the opaque
    JSON ``platforms`` / ``result`` blobs are treated as replace-on-edit values
    (a new list/dict is assigned, never mutated) so SQLAlchemy reliably detects
    the change and the payload shape can grow without a migration.
    """

    __tablename__ = "scheduled_publish"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id"), index=True, nullable=False
    )
    # Target platforms (e.g. ["tiktok", "instagram", "youtube_shorts"]). Kept as
    # JSON so the list can grow without a migration. Assigned a fresh list on
    # edit (immutable update) so the change is reliably detected.
    platforms: Mapped[list] = mapped_column(JSON, default=list)
    youtube_privacy_status: Mapped[str] = mapped_column(
        String(20), default="private", server_default=text("'private'"),
        nullable=False,
    )
    # The future UTC time at which the reel should auto-publish. Indexed so the
    # due-claim query (scheduled_at <= now) is an O(index) range scan.
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    # pending | publishing | published | failed | canceled. Indexed so the hot
    # due-claim filter (status='pending') never scans the whole table.
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default=text("'pending'"),
        index=True, nullable=False,
    )
    # Number of publish attempts made (incremented on each failure) so a runner
    # can bound retries. Defaults to 0.
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # Opaque native-publish result. Kept as
    # JSON so the shape can grow without a migration.
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Workspace(Base):
    """A team workspace (Team Workspaces): a shared container that a user owns
    and invites teammates into.

    This is a purely **additive** membership layer — it deliberately does NOT
    touch the existing per-user job/credit ownership model (jobs, credit_ledger
    and every other table remain keyed on ``users.id``). A workspace is the
    foundation for future team plans and shared resources, but today it only
    records who the members are and what role each holds.

    ``owner_id`` denormalizes the creating user's id (also present as a
    ``role='owner'`` :class:`WorkspaceMember` row) so the canonical owner can be
    read without a membership join; it is indexed for owner-scoped listing.
    """

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    members: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="workspace"
    )


class WorkspaceMember(Base):
    """A user's membership of a :class:`Workspace` with a role.

    ``role`` is one of ``owner | admin | editor | viewer | billing`` (Enterprise
    Access & Governance). The workspace creator is always the single ``owner``.
    This ``role`` string is the **tenant-isolation gate + role input** to the
    Casbin RBAC decision engine (:mod:`app.services.rbac`): a lookup that returns
    no membership row is an outright deny (the caller is not in this tenant),
    while the returned role is fed to the enforcer to decide a permission. A
    composite UNIQUE constraint on ``(workspace_id, user_id)`` enforces that a
    given user is a member of a given workspace at most once, so a duplicate
    invite can never create a second membership row. Both foreign keys are
    indexed so "members of a workspace" and "workspaces for a user" are O(index)
    lookups.

    The column length (``String(20)``) already accommodates every role token so
    the expanded vocabulary needs no schema change — the legacy ``member`` value
    from the additive Team-Workspaces layer stays valid and simply carries no
    Casbin policy (an unknown role denies every permission, fail-closed).
    """

    __tablename__ = "workspace_members"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # owner | admin | editor | viewer | billing (creator == owner)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="members")

    # A user is a member of a given workspace at most once.
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "user_id", name="uq_workspace_members_ws_user"
        ),
    )


class WorkspaceInvite(Base):
    """A pending invitation into a :class:`Workspace` (people without accounts).

    Created by an admin+ for an email; carries only the SHA-256 of a random
    one-time token (the raw token is returned once, inside the shareable
    ``accept_url``). Accepting requires an authenticated user whose account
    email matches ``email`` (case-insensitive) and turns the invite into a
    :class:`WorkspaceMember` with ``role``. Terminal states are recorded as
    timestamps (``accepted_at`` / ``revoked_at``) — rows are never deleted so
    the invite history stays auditable. ``expires_at`` bounds the token life.
    """

    __tablename__ = "workspace_invites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    invited_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditLog(Base):
    """An APPEND-ONLY audit trail row (Enterprise Access & Governance).

    Every governance-relevant action — a role change, a member removal, a
    billing grant, a platform-admin impersonation — records exactly one row here
    and NEVER mutates or deletes it afterward (there is deliberately no update /
    delete API; :class:`AuditLogRepository` only ever INSERTs and reads). This is
    the tamper-evident ledger an enterprise admin reviews, mirroring the
    append-only discipline of ``job_events`` / ``credit_ledger``.

    ``workspace_id`` is NULLABLE: a workspace-scoped action (role change, invite)
    tags the workspace, while a platform-level action (a staff impersonation that
    is not bound to one tenant) may leave it NULL. Reads are tenant-scoped — the
    audit query first requires the caller hold ``audit.read`` in the target
    workspace, then returns ONLY that workspace's rows, so a member of one tenant
    can never read another tenant's trail. ``actor_user_id`` is the user who
    performed the action; ``action`` is a stable dotted verb (e.g.
    ``members.role_changed``); ``target_type`` / ``target_id`` identify the
    object acted upon (both optional); the opaque JSON ``meta`` (DB column
    ``metadata``) carries event-specific detail and ``ip`` the caller's source
    address (both optional).

    A composite ``(workspace_id, created_at)`` index backs the hot tenant-scoped,
    newest-first listing so a workspace's trail never scans the whole table.
    ``BigInteger`` id (INTEGER on SQLite so autoincrement works in tests) keeps
    the append-only insert cheap and ordered.
    """

    __tablename__ = "audit_log"

    # BigInteger on Postgres/Neon; INTEGER on SQLite so autoincrement works in
    # the test DB (SQLite only auto-increments an INTEGER PRIMARY KEY column).
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    # NULLABLE: a workspace-scoped action tags its tenant; a platform-level
    # action (e.g. a staff impersonation) may leave it NULL. Covered by the
    # composite (workspace_id, created_at) index below for tenant-scoped reads.
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True
    )
    # The user who performed the action. Indexed for actor-scoped review.
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # Stable dotted action verb (e.g. members.role_changed, billing.granted,
    # admin.impersonated). Never NULL.
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    # The object acted upon. Both optional ('' / NULL) for actions with no
    # single target.
    target_type: Mapped[str] = mapped_column(
        String(80), default="", server_default=text("''"), nullable=False
    )
    target_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )
    # Opaque per-event detail. Mapped to the DB column ``metadata`` while the ORM
    # attribute is ``meta`` because ``metadata`` is reserved on the declarative
    # Base. Kept as JSON so the shape can grow without a migration; assigned a
    # fresh dict on write (append-only, never mutated in place).
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, default=dict, nullable=True)
    # Best-effort source IP of the caller (optional).
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Composite index backing the hot tenant-scoped, newest-first audit listing
    # (filter on workspace_id, order by created_at).
    __table_args__ = (
        Index("ix_audit_log_workspace_id_created_at", "workspace_id", "created_at"),
    )


class UserApiKey(Base):
    """A power user's personal API key for programmatic ``/api/v1`` access.

    PUBLIC API KEYS feature: a user mints a personal key used as the
    ``x-api-key`` header (in addition to the Clerk JWT and the static app key)
    so scripts/CI can drive the REST API on their behalf. Resolution extends the
    existing ``User.api_key_hash`` path (jobs.py) — the raw key is hashed with
    SHA-256 and matched against a live (non-revoked) row here to identify the
    owning user.

    SECURITY: the raw key is **never** persisted. Only its SHA-256 hex digest is
    stored in ``key_hash`` (revealed once at creation, then unrecoverable). A
    short, non-secret ``prefix`` (e.g. ``rf_ab12…``) is stored for display so a
    user can tell their keys apart without exposing the secret.

    ``key_hash`` is UNIQUE + indexed so a key resolves to at most one row in an
    O(index) lookup. ``user_id`` is indexed for owner-scoped listing and
    ``revoked`` is indexed so the hot "live keys only" lookup never scans the
    whole table. ``revoked`` defaults to ``False`` (a freshly minted key is
    active) and a revoke is a soft-delete (the row is retained for audit /
    display, never physically removed).
    """

    __tablename__ = "user_api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # Human-friendly label so a user can tell their keys apart (e.g. "CI", "n8n").
    name: Mapped[str] = mapped_column(
        String(200), default="", server_default=text("''"), nullable=False
    )
    # SHA-256 hex digest (64 chars) of the raw key — the ONLY persisted form of
    # the secret. UNIQUE + indexed so a presented key resolves to one owner.
    key_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    # Non-secret display prefix (e.g. "rf_ab12…"). Safe to show in a list UI.
    prefix: Mapped[str] = mapped_column(
        String(16), default="", server_default=text("''"), nullable=False
    )
    # Best-effort last-use stamp for the UI ("last used 2h ago"); NULL until the
    # key is first used to authenticate a request.
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # Per-key rate + quota controls (POWER-USER TIER quotas). Both are NULLABLE so
    # the ADD COLUMN is safe on an already-populated table and a key created
    # before this feature simply inherits the plan default:
    #   * ``rate_limit_per_min`` — max requests/minute this key may make. NULL
    #     falls back to the plan/config default (``apikey_quota._default_rate_limit_per_min``);
    #     a non-positive value disables the per-minute limit.
    #   * ``monthly_quota`` — max requests this key may make per calendar month
    #     (counted in ``api_key_usage``). NULL means UNLIMITED (no monthly cap).
    rate_limit_per_min: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    monthly_quota: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    # Soft-delete flag: a revoked key can never authenticate (see
    # ``UserApiKeyRepository.get_by_hash``) but the row is retained for audit /
    # display. Indexed so the live-key lookup is an O(index) filter.
    revoked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ApiKeyUsage(Base):
    """Monthly request counter for one :class:`UserApiKey` (per-key quota).

    Backs the POWER-USER TIER monthly quota: every authenticated ``x-api-key``
    request atomically increments the counter for the key's *current* calendar
    month (``period_ym`` == ``'YYYY-MM'``), and the enforcement layer
    (:mod:`app.services.apikey_quota`) rejects the request once the count exceeds
    the key's ``monthly_quota``.

    Exactly ONE row exists per ``(api_key_id, period_ym)`` — a composite UNIQUE
    constraint enforces it so a concurrent increment updates the single row in
    place rather than accumulating duplicates, and a new month simply inserts a
    fresh row (the prior months are retained for audit / usage history).
    ``api_key_id`` is indexed for owner-scoped usage listing. ``count`` defaults
    to 0 (``server_default`` '0') so a freshly-inserted period row is valid.
    """

    __tablename__ = "api_key_usage"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    api_key_id: Mapped[str] = mapped_column(
        ForeignKey("user_api_keys.id"), index=True, nullable=False
    )
    # The calendar month this counter tracks, as a zero-padded ``'YYYY-MM'``
    # token (7 chars). One row per key per month; a new month inserts a new row.
    period_ym: Mapped[str] = mapped_column(String(7), nullable=False)
    # Number of authenticated requests made with this key during ``period_ym``.
    count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # One counter row per (key, month): a concurrent increment updates in place.
    __table_args__ = (
        UniqueConstraint(
            "api_key_id", "period_ym", name="uq_api_key_usage_key_period"
        ),
    )


class MarketplaceTemplate(Base):
    """A creator-published, PUBLIC job template in the Template Marketplace.

    A creator publishes one of their private job templates (title, description,
    prompt, a params snapshot, tags, language and compose ``layout``) to a shared
    marketplace so any other authenticated user can browse/search it, view its
    detail, CLONE it into their own private templates, and RATE it (1..5).

    IMMUTABLE SNAPSHOT: publishing *copies* the source template's content into
    this row (``prompt`` / ``params`` / ``tags`` / ``language`` / ``layout``), so
    a later edit to the author's private template never mutates the public
    listing. The JSON ``params`` / ``tags`` blobs are treated as replace-on-edit
    values (a fresh dict/list is assigned, never mutated in place) so SQLAlchemy
    reliably detects a change and the shapes can grow without a migration.

    Denormalized aggregates ``rating_avg`` / ``rating_count`` are maintained by
    :class:`TemplateRatingRepository.upsert_rating` (recomputed atomically from
    the child :class:`TemplateRating` rows) so the browse list can sort by rating
    without a per-row aggregate; ``clone_count`` is bumped on each clone. All
    three default to 0 so a freshly published listing sorts sanely.

    ``published`` (default ``True``) gates visibility: only the author can flip a
    listing to unpublished (a soft hide — the row is retained for the author and
    its clones/ratings). ``author_user_id`` is indexed for owner-scoped listing
    and ``published`` is indexed so the hot browse filter never scans the whole
    table.
    """

    __tablename__ = "marketplace_templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # The publishing creator. Indexed for owner-scoped listing + owner-scoped
    # edit/unpublish authorization (only the author may mutate their listing).
    author_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(300), default="", server_default=text("''"), nullable=False
    )
    description: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    # The immutable snapshot of the source template's prompt/brief scaffold.
    prompt: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    # Opaque params snapshot (caption_style, target_duration_s, etc). Kept as JSON
    # so the shape can grow without a migration; assigned a fresh dict on edit.
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    # Free-form discovery tags, e.g. ["saas", "demo"]. Kept as a JSON list
    # (mirrors ``ScheduledPublish.platforms``); assigned a fresh list on edit.
    tags: Mapped[list] = mapped_column(JSON, default=list)
    # Persona/language code (tr | en | auto) mirroring the rest of the pipeline.
    language: Mapped[str] = mapped_column(
        String(20), default="en", server_default=text("'en'"), nullable=False
    )
    # Suggested compose layout id (e.g. hook_intro | pip | split).
    layout: Mapped[str] = mapped_column(
        String(40), default="", server_default=text("''"), nullable=False
    )
    # Denormalized rating aggregate, recomputed atomically on each rating upsert
    # from the child TemplateRating rows (never mutated ad hoc). Both default to 0
    # so an unrated listing sorts last under the "top" ordering.
    rating_avg: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0"), nullable=False
    )
    rating_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # Bumped once per clone so the browse UI can surface "most cloned".
    clone_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # REMIX TREE provenance (Marketplace Remix Trees). When this listing was
    # itself published from a private preset that was CLONED from another
    # marketplace listing (the preset config carries ``source_marketplace_id``),
    # this records the PARENT listing it descends from — forming a remix tree.
    # A NULLABLE self-FK to ``marketplace_templates.id``: an original (non-cloned)
    # publish leaves it NULL. No cycles are possible because a parent is always an
    # already-published, strictly-older row (a listing can only descend from a
    # listing that existed before it). Indexed so "children of a listing"
    # (:meth:`MarketplaceRepository.get_children`) and the remix-tree lineage walk
    # are O(index) lookups. NULL default keeps the ADD COLUMN safe on an
    # already-populated table and existing rows / prior tests unaffected.
    parent_template_id: Mapped[str | None] = mapped_column(
        ForeignKey("marketplace_templates.id"),
        index=True,
        nullable=True,
        default=None,
    )
    # Bumped once per remix (a clone that gets re-published) so the browse UI can
    # surface a "most remixed" sort. Defaults to 0 so an un-remixed listing sorts
    # sanely; incremented in-place (never a read-modify-write) on each remix.
    remix_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # Visibility gate. Indexed so the hot browse filter (published=True) is an
    # O(index) scan; only the author may flip it (soft unpublish).
    published: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ratings: Mapped[list[TemplateRating]] = relationship(
        back_populates="template"
    )


class TemplateRating(Base):
    """One user's 1..5 star rating of a :class:`MarketplaceTemplate`.

    Exactly ONE rating exists per ``(template_id, user_id)`` — a composite UNIQUE
    constraint enforces it, so a re-rate is an UPSERT (the existing row's
    ``stars`` is updated) rather than a duplicate insert. After every upsert the
    parent listing's ``rating_avg`` / ``rating_count`` are recomputed atomically
    from these rows (see :class:`TemplateRatingRepository.upsert_rating`).

    Both foreign keys are indexed so "ratings of a template" and "did this user
    rate?" are O(index) lookups. ``stars`` is a plain integer the service layer
    validates into ``[1, 5]`` before it reaches the row.
    """

    __tablename__ = "template_ratings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("marketplace_templates.id"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    template: Mapped[MarketplaceTemplate] = relationship(back_populates="ratings")

    # One rating per (template, user): a re-rate updates in place, never dupes.
    __table_args__ = (
        UniqueConstraint(
            "template_id", "user_id", name="uq_template_ratings_template_user"
        ),
    )


class JobPerformance(Base):
    """A creator's self-reported real-world outcome for one posted reel
    (Hook Performance Loop).

    After a creator renders a :class:`Job` and posts it to TikTok / Instagram /
    YouTube, they LOG the metrics that reel actually earned (views, likes,
    comments, shares, saves and watch-through/retention). Those outcomes are
    aggregated per HOOK and per TEMPLATE to compute a "win score", which then
    biases the SPARK idea engine toward patterns that genuinely convert. Fully
    key-free: every metric is creator-entered — there is no external platform
    API involved.

    STRICTLY PER-USER + ONE ROW PER JOB: ``job_id`` is ``UNIQUE`` (and indexed)
    so re-logging a job's metrics UPSERTs the existing row rather than
    accumulating duplicates, and :class:`JobPerformanceRepository` resolves the
    singleton by owner-scoped id. ``user_id`` denormalizes the owning creator
    (always the job's ``user_id``, verified before insert) so every read/aggregate
    filters on the owner without a join and a creator can never log against — or
    read the outcomes of — another creator's job.

    All numeric counts default to 0 (``server_default`` '0') and are clamped
    non-negative at the repository boundary; ``retention_pct`` is a percentage
    clamped to ``[0, 100]``. ``platform`` is a normalized, lower-cased persona
    string (e.g. ``tiktok`` | ``instagram`` | ``youtube``), defaulting to
    ``'unknown'`` when unspecified. Every column declares its ``server_default``
    so the brand-new table's row shape is self-describing and Alembic
    autogenerate reports no drift.
    """

    __tablename__ = "job_performance"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Exactly one performance row per job: UNIQUE so a re-log can never create a
    # second row (the repository upserts in place), and indexed so the row
    # resolves by job id in an O(index) lookup.
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id"), unique=True, index=True, nullable=False
    )
    # The owning creator — always the job's ``user_id`` (verified before insert).
    # Indexed for owner-scoped listing + owner-scoped aggregation so no read ever
    # crosses users.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # Normalized, lower-cased platform the outcome was posted to
    # (tiktok | instagram | youtube | ...). '' is normalized to 'unknown'.
    platform: Mapped[str] = mapped_column(
        String(40), default="unknown",
        server_default=text("'unknown'"), nullable=False,
    )
    # Creator-entered engagement counts. All clamped non-negative at the
    # repository boundary; default 0 so a partially-filled log is always valid.
    views: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    likes: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    comments: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    shares: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    saves: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # Watch-through / retention percentage in [0, 100] (clamped at the boundary).
    retention_pct: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0"), nullable=False
    )
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SocialAccount(Base):
    """A user's OAuth-connected social platform account for DIRECT PUBLISH.

    Direct-Publish Account-Connect: a creator authorizes ReelForge (via a
    provider OAuth flow — TikTok / Instagram / YouTube) so a finished reel can be
    posted straight to their account. This row records that connection: which
    platform, which external account, and the OAuth credentials needed to publish
    on their behalf.

    AUTH-CRITICAL — TOKENS ARE SENSITIVE. The plaintext OAuth access/refresh
    tokens are **never** persisted. Only their symmetrically-encrypted blobs are
    stored (``access_token_enc`` / ``refresh_token_enc``); encryption/decryption
    happens at the service boundary (:mod:`app.services.crypto_tokens`) with a key
    sourced from config/env, so a database leak never exposes a usable token.
    ``access_token_enc`` is NOT NULL (a connection always has an access token);
    ``refresh_token_enc`` is nullable because not every provider issues one.

    STRICTLY PER-USER + ONE ACCOUNT PER (user, provider): ``user_id`` is indexed
    for owner-scoped listing and a composite UNIQUE constraint on
    ``(user_id, provider)`` guarantees a creator has at most one connection per
    platform — re-connecting a provider UPSERTs the existing row in place (fresh
    tokens replace the old blobs) rather than accumulating duplicates. Every read
    is owner-scoped so a creator can never read or publish with another creator's
    tokens.

    ``provider`` is a normalized, lower-cased token in
    ``{tiktok, instagram, youtube}`` (validated at the service/repository
    boundary). ``external_account_id`` is the provider-side account/user id (e.g.
    a TikTok ``open_id``) used to attribute posts. ``scopes`` is the granted OAuth
    scope string. ``token_expires_at`` (nullable) drives proactive refresh.
    """

    __tablename__ = "social_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # The owning creator. Indexed for owner-scoped listing; every read filters on
    # it so a caller can never touch another creator's connection.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # Normalized, lower-cased platform token in {tiktok, instagram, youtube}
    # (validated at the service/repository boundary).
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    # Provider-side account/user id (e.g. TikTok open_id) used to attribute posts.
    external_account_id: Mapped[str] = mapped_column(
        String(200), default="", server_default=text("''"), nullable=False
    )
    # ENCRYPTED OAuth access token blob — NEVER the plaintext token. Encrypted via
    # app.services.crypto_tokens with a config/env key. NOT NULL: a connection
    # always carries an access token.
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    # ENCRYPTED OAuth refresh token blob — NEVER plaintext. Nullable because not
    # every provider issues a refresh token.
    refresh_token_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    # When the access token expires (nullable — unknown/never for some providers).
    # Drives proactive refresh_if_needed before a publish.
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # Granted OAuth scope string (space/comma-delimited per provider). Kept as
    # Text so a long scope grant never truncates.
    scopes: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # At most one connection per (user, provider): a re-connect UPSERTs in place.
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", name="uq_social_accounts_user_provider"
        ),
    )


class StoreConnection(Base):
    """A user's connected developer-store credential (Phase 3 "Connect your store").

    A creator pastes an App Store Connect API key (issuer id, key id, ``.p8``
    private key) or uploads a Google Play service-account JSON so Menivor can
    read their published apps' current versions and ratings (fed into the
    App Store Audit tool) without the owner ever holding the creator's App Store
    Connect / Play Console password.

    AUTH-CRITICAL — CREDENTIALS ARE SENSITIVE. The whole credential (the ASC
    ``.p8`` private key PEM, or the entire Play service-account JSON) is never
    persisted in the clear: it is JSON-encoded and encrypted with
    :mod:`app.services.crypto_tokens` (the same Fernet helper that protects
    Direct-Publish OAuth tokens on :class:`SocialAccount`) before it reaches
    ``credentials_enc``. ``account_name`` holds only a NON-secret label (the ASC
    issuer id, or the Play service account's ``client_email``) so the UI can show
    which account is connected without decrypting anything.

    STRICTLY PER-USER + ONE CONNECTION PER (user, provider): mirrors
    :class:`SocialAccount`'s shape — a composite UNIQUE on
    ``(user_id, provider)`` means re-connecting a provider UPSERTs the existing
    row (fresh credentials replace the old blob) instead of accumulating
    duplicates, and every read is owner-scoped.

    ``provider`` is ``"appstore"`` or ``"play"``. ``meta`` is a small, NON-secret
    JSON bag: for ``play`` it holds ``{"package_names": [...]}`` — the package
    names the creator has registered, because the Play Developer API has no
    "list all my apps" endpoint and each package must be added individually.
    """

    __tablename__ = "store_connections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # "appstore" | "play" (validated/normalized at the service/repository boundary).
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    # NON-secret label: the ASC issuer id, or the Play service account's
    # client_email. Lets the UI show "which account" without decrypting anything.
    account_name: Mapped[str] = mapped_column(
        String(300), default="", server_default=text("''"), nullable=False
    )
    # ENCRYPTED JSON blob of the whole credential (ASC issuer_id/key_id/private
    # key PEM, or the full Play service-account JSON) — NEVER the plaintext.
    credentials_enc: Mapped[str] = mapped_column(Text, nullable=False)
    # Small NON-secret bookkeeping bag (e.g. Play's registered package names).
    meta: Mapped[dict] = mapped_column(
        jsonb_variant(), default=dict, server_default=text("'{}'"), nullable=False
    )
    # "connected" | "invalid" (credential rejected on last validation attempt).
    status: Mapped[str] = mapped_column(
        String(20), default="connected", server_default=text("'connected'"), nullable=False
    )
    status_note: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # At most one connection per (user, provider): a re-connect UPSERTs in place.
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", name="uq_store_connections_user_provider"
        ),
    )


class ShareLink(Base):
    """A public, unguessable, revocable share link for one of a creator's reels
    (Public Watermarked Share Pages).

    A creator turns one of THEIR OWN completed :class:`Job` reels into a public
    landing page: anyone (no auth) who has the link sees a WATERMARKED preview of
    the reel (never the clean output/``result_key``), the reel's title, and a
    soft call-to-action. Views are counted for social proof, and signup
    attribution is handled by the frontend via the sharer's referral code.

    SECURITY — SAFE PUBLIC SURFACE. The link is addressed only by ``token``, a
    128-bit ``secrets.token_urlsafe`` value (see :func:`_share_token`) that is
    UNIQUE + indexed so it resolves in an O(index) lookup and can never be
    enumerated. ``revoked`` (default ``False``) is a soft kill-switch: a revoked
    link is treated as non-existent by every public read (the row is retained for
    audit) so a creator can instantly and durably take a shared reel offline. The
    public view DTO built from this row exposes ONLY safe fields (title, a
    presigned GET of the watermarked preview/poster/cover key, the reel's
    ``created_at`` and the sharer's referral code) — never the clean ``result_key``,
    the owning ``user_id``, or any private financials.

    STRICTLY PER-USER + ONE ACTIVE LINK PER JOB. ``user_id`` denormalizes the
    owning creator (always the job's ``user_id``, verified before insert) so every
    owner-scoped mutation (revoke) filters on it without a join and a creator can
    never share — or revoke the share of — another creator's job. ``job_id`` is
    indexed so the "does an active link already exist for this job?" check
    (:meth:`ShareLinkRepository.create_for_job`) is an O(index) lookup that returns
    the existing active link rather than minting duplicates.
    """

    __tablename__ = "share_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # The shared reel. Indexed so the one-active-link-per-job lookup is O(index).
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id"), index=True, nullable=False
    )
    # The owning creator — always the job's ``user_id`` (verified before insert).
    # Indexed for owner-scoped listing; every owner-scoped mutation filters on it.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # Unguessable public handle (128-bit ``secrets.token_urlsafe``). UNIQUE +
    # indexed so it resolves to at most one row and can never be enumerated.
    token: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, default=_share_token
    )
    # Soft kill-switch: a revoked link is treated as non-existent by every public
    # read (the row is retained for audit). Defaults to ``False`` (a fresh link is
    # live).
    revoked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    # Public view counter (social proof). Bumped in-place on each public view.
    view_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CreatorFollow(Base):
    """A directed FOLLOW edge in the creator social graph (Creator Profiles +
    Follow Graph): ``follower_user_id`` follows ``followee_user_id``.

    Powers public follower/following counts on a creator profile and a
    "followers" leaderboard. A brand-new, append-friendly table: an edge is
    inserted on follow and physically removed on unfollow (there is no soft-delete
    — a follow relationship is either present or absent).

    IDEMPOTENT + NO SELF-FOLLOW: a composite UNIQUE constraint on
    ``(follower_user_id, followee_user_id)`` guarantees a given directed edge
    exists AT MOST ONCE, so a double-follow can never create a second row (the
    repository resolves the existing edge instead). A user following themselves is
    rejected at the service/repository boundary (never persisted). Both foreign
    keys are indexed so "who follows X?" (followers) and "who does X follow?"
    (following) are O(index) lookups / aggregates.

    This edge carries NO private data — it is a purely public social relationship,
    so its counts are safe to surface on a public profile.
    """

    __tablename__ = "creator_follows"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # The user doing the following. Indexed so "who does this user follow?"
    # (following_count / list) is an O(index) aggregate.
    follower_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # The user being followed. Indexed so "who follows this user?"
    # (follower_count / list) is an O(index) aggregate.
    followee_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # A directed follow edge is unique: a re-follow updates nothing (the row
    # already exists) rather than duplicating.
    __table_args__ = (
        UniqueConstraint(
            "follower_user_id",
            "followee_user_id",
            name="uq_creator_follows_follower_followee",
        ),
    )


class SSOConnection(Base):
    """A workspace's Enterprise IdP connection (SAML or OIDC) — Identity & SSO.

    Enterprise SSO is an ADDITIVE, NEW auth path for orgs that configure an
    identity provider; it does NOT replace Clerk (email + Google). Exactly ONE
    connection exists per workspace — ``workspace_id`` is ``UNIQUE`` (and
    indexed) — so :class:`SSOConnectionRepository.upsert` updates the single row
    in place rather than accumulating duplicates, and the ACS/login path resolves
    it by workspace id in an O(index) lookup. Only a workspace owner/admin
    (``require_permission workspace.settings``) may configure it (gated at the
    API), and every change writes an audit row (Epic 1).

    AUTH-CRITICAL — the IdP signing certificate is SENSITIVE. For SAML the IdP's
    X.509 signing certificate (used to VERIFY the assertion signature) is stored
    Fernet-encrypted in ``idp_x509_cert_enc`` (never plaintext), encrypted at the
    service boundary (:mod:`app.services.crypto_tokens`, ``SOCIAL_TOKEN_KEY``) —
    mirroring :class:`SocialAccount`'s token blobs. For OIDC the client secret is
    likewise stored encrypted in ``oidc_client_secret_enc``. Both are NULLABLE
    because a SAML connection has no OIDC secret and vice-versa.

    ``protocol`` is a normalized, lower-cased token in ``{saml, oidc}`` validated
    at the service/repository boundary. ``enabled`` gates whether the SSO login
    path is live for the workspace. Tenant isolation: a connection is scoped to
    ONE workspace and can never authenticate into another.
    """

    __tablename__ = "sso_connections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Exactly one connection per workspace: UNIQUE so an upsert can never create a
    # second row, and indexed so the ACS/login path resolves it in an O(index)
    # lookup. This is the tenant-isolation key — a connection authenticates into
    # its own workspace only.
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    # Normalized, lower-cased protocol token in {saml, oidc}.
    protocol: Mapped[str] = mapped_column(
        String(10), default="saml", server_default=text("'saml'"), nullable=False
    )
    # SAML: the IdP EntityID (issuer). OIDC: the issuer URL.
    idp_entity_id: Mapped[str] = mapped_column(
        String(512), default="", server_default=text("''"), nullable=False
    )
    # SAML: the IdP SSO (SingleSignOn) redirect endpoint. OIDC: the authorization
    # endpoint.
    idp_sso_url: Mapped[str] = mapped_column(
        String(1024), default="", server_default=text("''"), nullable=False
    )
    # ENCRYPTED IdP X.509 signing certificate (SAML) — NEVER plaintext. Used to
    # verify the assertion signature. Nullable (OIDC has none).
    idp_x509_cert_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    # The SP AssertionConsumerService URL the IdP posts the assertion back to.
    sp_acs_url: Mapped[str] = mapped_column(
        String(1024), default="", server_default=text("''"), nullable=False
    )
    # OIDC client id (public) + ENCRYPTED client secret (nullable — SAML has none).
    # OIDC is implemented on the existing httpx/oauth_connect patterns.
    oidc_client_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True, default=None
    )
    oidc_client_secret_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    # Whether the SSO login path is live for this workspace.
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_sso_connections_workspace"),
    )


class ScimToken(Base):
    """A bearer token for a workspace's SCIM 2.0 provisioning endpoint.

    An IdP (Okta / Azure AD / …) uses this token to provision + deprovision users
    into ONE workspace via SCIM. TENANT ISOLATION is the load-bearing invariant: a
    token is scoped to a single ``workspace_id`` and can NEVER provision into or
    read another workspace — the SCIM auth layer resolves the presented bearer to
    its row and asserts ``row.workspace_id`` matches the target workspace before
    any write/read.

    SECURITY — the raw token is NEVER persisted. Only its SHA-256 hex digest is
    stored in ``token_hash`` (revealed once at creation, then unrecoverable),
    mirroring :class:`UserApiKey`. ``token_hash`` is UNIQUE + indexed so a
    presented token resolves to at most one row in an O(index) lookup. A short,
    non-secret ``prefix`` is stored for display. ``revoked`` (default ``False``,
    indexed) is a soft kill-switch — a revoked token can never authenticate but
    the row is retained for audit.
    """

    __tablename__ = "scim_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # The single workspace this token may provision into. Indexed for
    # owner-scoped listing; the tenant-isolation check compares it to the target.
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    # SHA-256 hex digest (64 chars) of the raw bearer token — the ONLY persisted
    # form of the secret. UNIQUE + indexed so a presented token resolves to one row.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Non-secret display prefix (e.g. "scim_ab12…"). Safe to show in a list UI.
    prefix: Mapped[str] = mapped_column(
        String(16), default="", server_default=text("''"), nullable=False
    )
    # Soft-delete flag: a revoked token can never authenticate. Indexed so the
    # live-token lookup is an O(index) filter.
    revoked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), index=True, nullable=False
    )
    # Best-effort last-use stamp for the UI; NULL until first used.
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_scim_tokens_token_hash"),
    )


class SecurityPolicy(Base):
    """A workspace's enterprise login security policy (Identity & SSO).

    Exactly ONE policy per workspace — ``workspace_id`` is the PRIMARY KEY — so a
    policy is a singleton the login path reads by workspace id and
    :class:`SecurityPolicyRepository.upsert` updates in place. Only a workspace
    owner/admin (``workspace.settings``) may set it (RBAC-gated in the service),
    and every change writes an audit row.

    Fields drive :func:`app.services.security_policy.enforce_login_policy`:
    ``require_sso`` forces the SSO path (rejecting password/Clerk login when set);
    ``session_timeout_min`` bounds an issued session's lifetime (0 == no cap);
    ``allowed_email_domains`` (JSON list) restricts which email domains may sign
    in / be provisioned (empty == any); ``mfa_required`` demands MFA in the login
    context; ``ip_allowlist`` (JSON list) restricts source IPs (empty == any).
    The JSON lists are treated as replace-on-edit values (a fresh list is
    assigned, never mutated in place) so SQLAlchemy reliably detects a change and
    the shapes can grow without a migration.
    """

    __tablename__ = "security_policies"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), primary_key=True
    )
    require_sso: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    session_timeout_min: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # JSON list of allowed email domains (lower-cased, no '@'), e.g.
    # ["acme.com"]. Empty means any domain is allowed.
    allowed_email_domains: Mapped[list | None] = mapped_column(
        JSON, default=list, nullable=True
    )
    mfa_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    # JSON list of allowed source IPs / CIDRs. Empty means any IP is allowed.
    ip_allowlist: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExternalIdentity(Base):
    """A link between a ReelForge :class:`User` and an IdP subject in ONE workspace.

    Both the SAML ACS path and the SCIM provisioning path resolve/create a row
    here: it maps an IdP-side subject (SAML ``NameID`` / SCIM ``externalId``) to a
    local user within a single workspace. TENANT ISOLATION: a composite ``UNIQUE``
    on ``(workspace_id, idp_subject)`` guarantees a subject maps to at most one
    identity per workspace, and every lookup filters on ``workspace_id`` so an
    identity provisioned in workspace B can never be resolved from workspace A.

    ``provisioned`` (default ``False``) records whether the identity is currently
    active from the IdP's perspective — SCIM deactivation soft-disables the
    identity (flips it to ``False``) rather than deleting the row, so the mapping
    is retained for audit and re-activation. ``email`` denormalizes the subject's
    email for the domain-allowlist check and display. Both foreign keys are
    indexed for owner-scoped listing.
    """

    __tablename__ = "external_identities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # The workspace this identity belongs to — the tenant-isolation key. Indexed
    # for owner-scoped listing; every lookup filters on it.
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    # The IdP-side subject: SAML NameID / SCIM externalId. Unique per workspace.
    idp_subject: Mapped[str] = mapped_column(String(512), nullable=False)
    email: Mapped[str] = mapped_column(
        String(320), default="", server_default=text("''"), nullable=False
    )
    # Whether the identity is currently active from the IdP's perspective. SCIM
    # deactivation flips this to False (soft-disable) rather than deleting.
    provisioned: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # A subject maps to at most one identity per workspace: a re-provision updates
    # in place, never duplicates, and never crosses tenants.
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idp_subject", name="uq_external_identities_ws_subject"
        ),
    )


class Subscription(Base):
    """A workspace's billing subscription (Enterprise Billing Platform, Epic 3).

    Exactly ONE subscription per workspace: ``workspace_id`` is ``UNIQUE`` (and
    indexed) so a workspace can never accumulate two conflicting subscriptions —
    a plan change UPDATEs the single row in place and a duplicate provider event
    resolves to the same row. The row records which ``plan_key`` (free | starter
    | pro | enterprise) the workspace is on, which payment ``provider`` funds it
    (reuses the existing Stripe adapter) and the provider-side ``provider_ref``
    (the Stripe subscription id) used to correlate webhooks.

    ``status`` is one of ``active | past_due | canceled | trialing`` and gates
    entitlement resolution: :func:`app.services.entitlements.is_entitled` treats a
    NON-active subscription exactly like *no* subscription — the workspace falls
    back to the safe base/free plan entitlements, so a lapsed (``past_due`` /
    ``canceled``) subscription can never keep granting a premium extra. ``seats``
    bounds how many members the plan permits and ``current_period_end`` (nullable)
    records when the paid period lapses. Every column declares its
    ``server_default`` so the brand-new table's row shape is self-describing and
    Alembic autogenerate reports no drift.
    """

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Exactly one subscription per workspace (the tenant-isolation key): UNIQUE so
    # a plan change updates in place and indexed so a workspace's subscription is
    # an O(index) lookup.
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    # free | starter | pro | enterprise — the plan whose entitlement bundle the
    # workspace holds (see app.services.entitlements.PLAN_ENTITLEMENTS).
    plan_key: Mapped[str] = mapped_column(
        String(40), default="free", server_default=text("'free'"), nullable=False
    )
    # Payment rail funding the subscription (reuses the existing Stripe adapter).
    provider: Mapped[str] = mapped_column(
        String(40), default="stripe", server_default=text("'stripe'"), nullable=False
    )
    # Provider-side id (e.g. the Stripe subscription id ``sub_...``) used to
    # correlate webhooks back to this row. '' until the provider confirms.
    provider_ref: Mapped[str] = mapped_column(
        String(255), default="", server_default=text("''"), nullable=False
    )
    # active | past_due | canceled | trialing. Only ``active`` / ``trialing``
    # grant the plan's entitlements; the rest fall back to base/free.
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default=text("'active'"), nullable=False
    )
    # month | year billing cadence.
    interval: Mapped[str] = mapped_column(
        String(10), default="month", server_default=text("'month'"), nullable=False
    )
    # Number of member seats the plan permits.
    seats: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    # When the current paid period lapses (nullable until the provider confirms).
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_subscriptions_workspace"),
    )


class MeteredUsage(Base):
    """One idempotent unit of metered usage for a workspace (Billing, Epic 3).

    Backs usage-based billing and overage: each row records ``quantity`` units of
    a ``metric`` (e.g. ``render`` | ``api_call``) consumed by ``workspace_id`` in
    the calendar month ``period_ym`` (``'YYYY-MM'``). Usage cannot be gamed or
    double-counted: ``idempotency_key`` is ``UNIQUE`` so replaying the same
    metering event (same render job, same webhook) inserts at most one row — the
    repository swallows the resulting ``IntegrityError`` and returns the existing
    row rather than double-charging. ``workspace_id`` + ``period_ym`` are indexed
    together so per-metric aggregation for a billing period is an O(index) scan
    and never crosses tenants.
    """

    __tablename__ = "metered_usage"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    # The metered dimension (e.g. render | api_call | export). Normalized
    # lower-case at the service boundary.
    metric: Mapped[str] = mapped_column(String(60), nullable=False)
    # Units consumed by this event (clamped non-negative at the boundary).
    quantity: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # Calendar month this usage is billed to, as ``'YYYY-MM'`` (7 chars).
    period_ym: Mapped[str] = mapped_column(String(7), nullable=False)
    # The dedupe handle: UNIQUE so the SAME metering event can never be counted
    # twice (a replay hits the constraint and is ignored). Constructed by the
    # caller to be stable per real-world event (e.g. ``render:<job_id>``).
    idempotency_key: Mapped[str] = mapped_column(
        String(160), unique=True, nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Composite index backing the hot per-workspace, per-period aggregation.
    __table_args__ = (
        Index("ix_metered_usage_ws_period", "workspace_id", "period_ym"),
    )


class Invoice(Base):
    """A workspace's billing invoice (Enterprise Billing Platform, Epic 3).

    A tenant-scoped record of an amount owed/paid for a billing period. ``status``
    is one of ``draft | open | paid | void``; ``amount_cents`` is the integer
    minor-unit total (never a float, so money math is exact) in ``currency``.
    ``provider_ref`` correlates the invoice to the payment provider (e.g. the
    Stripe invoice id). ``workspace_id`` is indexed for the owner-scoped, tenant
    isolated listing — an invoice is only ever returned to a member of its own
    workspace. Line-item detail lives in child :class:`InvoiceLineItem` rows.
    """

    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    # Provider-side invoice id (e.g. Stripe ``in_...``); '' for an internally
    # generated invoice.
    provider_ref: Mapped[str] = mapped_column(
        String(255), default="", server_default=text("''"), nullable=False
    )
    # Integer minor units (cents) — exact money, never a float.
    amount_cents: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    currency: Mapped[str] = mapped_column(
        String(10), default="usd", server_default=text("'usd'"), nullable=False
    )
    # draft | open | paid | void.
    status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default=text("'draft'"), nullable=False
    )
    period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    line_items: Mapped[list[InvoiceLineItem]] = relationship(
        back_populates="invoice"
    )


class InvoiceLineItem(Base):
    """One line on an :class:`Invoice` (description + quantity + minor-unit amount).

    ``amount_cents`` is the integer minor-unit total for the line (``quantity`` ×
    unit price, computed at the service boundary) so an invoice total is the exact
    integer sum of its lines with no floating-point drift. ``invoice_id`` is
    indexed so a bill's lines are an O(index) lookup.
    """

    __tablename__ = "invoice_line_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("invoices.id"), index=True, nullable=False
    )
    description: Mapped[str] = mapped_column(
        String(300), default="", server_default=text("''"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    # Integer minor units (cents) for the whole line — exact money, never a float.
    amount_cents: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    invoice: Mapped[Invoice] = relationship(back_populates="line_items")


class WebhookSubscription(Base):
    """A workspace's subscription to outbound platform events (Enterprise API, Epic 4).

    A customer registers a callback ``url`` and the set of ``event_types`` (e.g.
    ``job.completed`` | ``publish.succeeded`` | ``performance.ingested``) they want
    pushed to it. When any subscribed event fires,
    :func:`app.services.webhook_subscriptions.dispatch` mints a
    :class:`WebhookDelivery` and hands it to the existing HMAC-signed, SSRF-guarded
    :func:`app.services.webhooks.deliver_webhook` primitive.

    SECURITY — SIGNING SECRET IS SENSITIVE. ``secret_enc`` is the subscription's
    HMAC signing key stored ONLY as a Fernet blob
    (:mod:`app.services.crypto_tokens`); the plaintext is shown exactly once at
    create time and is NEVER persisted or returned again. A database leak therefore
    never exposes a usable signing key.

    SECURITY — SSRF. ``url`` is validated through the SAME guard used by
    :func:`~app.services.webhooks.deliver_webhook`
    (``webhooks._validate_and_resolve``) BEFORE the row is ever persisted, so a
    customer can never register a loopback / link-local / RFC-1918 / metadata
    target to coerce the platform into calling an internal service.

    TENANT ISOLATION. ``workspace_id`` (indexed) owns the subscription; every read
    filters on it so workspace *B* can never see or deliver workspace *A*'s
    subscriptions. ``enabled`` is a soft kill-switch: a revoked subscription is
    retained for audit but is skipped by every dispatch.
    """

    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # The owning tenant. Indexed for tenant-scoped listing; every read filters on
    # it so a caller can never touch another workspace's subscription.
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=False
    )
    # The customer callback URL. Validated through the shared SSRF guard before
    # insert (never an internal/private/loopback target). Text so a long URL with
    # query params never truncates.
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # The subscribed event types as a JSON list (e.g. ["job.completed"]). A fresh
    # list is assigned on write (never mutated in place).
    event_types: Mapped[list] = mapped_column(
        jsonb_variant(), default=list, server_default=text("'[]'"), nullable=False
    )
    # ENCRYPTED HMAC signing secret blob — NEVER the plaintext. Encrypted via
    # app.services.crypto_tokens with a config/env key; shown once on create.
    secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    # Soft kill-switch: a disabled subscription is retained for audit but skipped
    # by every dispatch. Defaults to True (a fresh subscription is live).
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    deliveries: Mapped[list[WebhookDelivery]] = relationship(
        back_populates="subscription"
    )


class WebhookDelivery(Base):
    """One idempotent delivery attempt-record of an event to a subscription (Epic 4).

    Each real-world event carries a stable ``event_id``; a composite UNIQUE on
    ``(subscription_id, event_id)`` guarantees a given event is delivered to a
    given subscription AT MOST ONCE — a replayed event resolves to the existing
    row and never double-delivers. ``status`` moves ``pending -> delivered`` on a
    2xx or ``pending -> failed`` once ``attempts`` exhausts the retry budget.
    ``attempts`` / ``last_attempt_at`` / ``response_code`` drive the capped
    exponential backoff retry in
    :func:`app.services.webhook_subscriptions.retry_pending`.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # The target subscription. Indexed so a subscription's deliveries are an
    # O(index) lookup and the pending-retry scan is cheap.
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("webhook_subscriptions.id"), index=True, nullable=False
    )
    # The event type this delivery carries (e.g. job.completed).
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    # The stable per-event id — the dedupe handle (UNIQUE with subscription_id).
    event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    # The signed JSON body delivered to the subscription. A fresh dict on write.
    payload: Mapped[dict] = mapped_column(
        jsonb_variant(), default=dict, server_default=text("'{}'"), nullable=False
    )
    # pending | delivered | failed.
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default=text("'pending'"), nullable=False
    )
    # Delivery attempts made so far (bounded by the retry budget).
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # HTTP status of the most recent attempt (nullable — a transport error has no
    # status).
    response_code: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    subscription: Mapped[WebhookSubscription] = relationship(
        back_populates="deliveries"
    )

    # A given event is delivered to a given subscription at most once (idempotency).
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "event_id", name="uq_webhook_deliveries_sub_event"
        ),
    )


class RetentionPolicy(Base):
    """A workspace's data-retention policy (Compliance / GDPR retention, Epic 5).

    Exactly ONE policy per workspace — ``workspace_id`` is the PRIMARY KEY — so a
    policy is a singleton the retention sweep reads by workspace id and
    :class:`RetentionPolicyRepository.upsert` updates in place rather than
    accumulating rows. Only a workspace owner/admin (``workspace.settings``) may
    set it (RBAC-gated in :mod:`app.services.compliance.retention`), and every
    change writes an audit row (Epic 1).

    ``jobs_retention_days`` / ``assets_retention_days`` bound how long jobs /
    assets belonging to the workspace's members are kept before the periodic
    sweep (:func:`app.services.compliance.retention.sweep_retention`, wired to
    Celery beat) anonymizes/soft-purges the aged rows. Both are ``NULLABLE`` and
    default to NULL meaning **keep forever** — a workspace with no configured
    window is never swept, so the feature is strictly opt-in and existing tenants
    are unaffected. TENANT ISOLATION: the sweep only ever touches rows owned by
    members of ``workspace_id`` older than that workspace's own window.
    """

    __tablename__ = "retention_policies"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), primary_key=True
    )
    # Retain jobs for this many days; NULL == keep forever (never swept).
    jobs_retention_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    # Retain assets for this many days; NULL == keep forever (never swept).
    assets_retention_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConsentRecord(Base):
    """An APPEND-ONLY record of a user's consent decision (Compliance, Epic 5).

    Backs GDPR / SOC2 consent capture: each row records that ``user_id`` GRANTED
    or withdrew consent for one ``kind`` (e.g. ``tos`` | ``marketing`` |
    ``ai_disclosure``) at a given policy ``version``. The table is append-only —
    a consent change inserts a NEW row rather than mutating history, so the full
    consent trail is preserved for audit and the *current* decision is simply the
    newest row for a ``(user_id, kind)`` pair (see
    :class:`ConsentRepository.get_latest`). ``user_id`` is indexed for
    owner-scoped listing; every read is strictly scoped to the requesting user.
    """

    __tablename__ = "consent_records"

    # BigInteger on Postgres/Neon; INTEGER on SQLite so autoincrement works in
    # the test DB (SQLite only auto-increments an INTEGER PRIMARY KEY column). A
    # monotonic id makes "newest decision wins" a reliable id-ordered read even
    # when two rows share a coarse ``created_at`` second.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # Consent dimension: tos | marketing | ai_disclosure | ... (free-form,
    # normalized lower-case at the service boundary).
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    # Whether consent was GRANTED (True) or withdrawn/denied (False).
    granted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    # The policy/document version the decision was made against (e.g. "2026-08").
    version: Mapped[str] = mapped_column(
        String(40), default="", server_default=text("''"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ErasureRequest(Base):
    """A user's right-to-erasure request (GDPR Art. 17 — Compliance, Epic 5).

    Tracks the lifecycle of a user's request to have their PII anonymized:
    ``status`` moves ``requested -> processing -> completed`` as
    :func:`app.services.compliance.erasure.erase_user` runs. The erasure
    ANONYMIZES PII in place (email/name/handle/bio tombstoned, credentials
    revoked, job scripts/prompts blanked) while PRESERVING row structure and any
    legally-required financial / audit records — it never cascade-deletes rows
    that would break referential integrity. ``user_id`` is indexed for
    owner-scoped listing; ``scope`` records what was erased (e.g. ``user``).
    ``requested_at`` stamps the request and ``completed_at`` (nullable) stamps
    when the anonymization finished.
    """

    __tablename__ = "erasure_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # requested | processing | completed.
    status: Mapped[str] = mapped_column(
        String(20), default="requested", server_default=text("'requested'"),
        nullable=False,
    )
    # What the erasure covers (e.g. "user"). Free-form, defaults to 'user'.
    scope: Mapped[str] = mapped_column(
        String(40), default="user", server_default=text("'user'"), nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # When the anonymization completed (NULL until status == 'completed').
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


# Provider-marketplace / pay-as-you-go tables (catalog + wallet). Imported here
# so importing ``app.models.db.models`` anywhere (env.py autogenerate, tests'
# ``Base.metadata.create_all``, repository modules) registers these tables on
# the shared ``Base.metadata`` exactly like the models defined above.
from app.models.db.marketplace import (  # noqa: E402
    MICRODOLLARS_PER_USD,
    GenerationProfile,
    ModelCatalogEntry,
    PaymentIntent,
    PriceVersion,
    ProviderCatalog,
    ProviderHealthEvent,
    ProviderKey,
    SpendPolicy,
    UsageRecord,
    WalletAccount,
    WalletAccountOwner,
    WalletLedgerEntry,
    WalletSavedRecipient,
    WalletTransfer,
    WalletTransferAttestation,
    WalletTransferChallenge,
    WalletTransferPolicy,
)

# Repurposing-engine tables (long video -> ranked highlight clips). Imported for
# the same metadata-registration reason as the marketplace tables above.
from app.models.db.repurpose import (  # noqa: E402
    RepurposeClip,
    RepurposeJob,
)

# Personal monthly-plan subscriptions (web creators). Imported for the same
# metadata-registration reason as the marketplace tables above.
from app.models.db.creator_subscription import CreatorSubscription  # noqa: E402

# Dodo Payments usage-event outbox (metered monthly plans).
from app.models.db.dodo_usage_event import DodoUsageEvent  # noqa: E402

# Premium voice / AI-video credits (never paid for by standard credits).
from app.models.db.premium_credit import PremiumCreditLedger  # noqa: E402

# Activation funnel (first-time steps + weekly owner report ledger).
from app.models.db.funnel import FunnelEvent, FunnelReport  # noqa: E402
# Automatic performance tracking (tracked posts + per-read snapshots).
from app.domains.performance.models import PostSnapshot, TrackedPost  # noqa: E402,F401

__all__ = [
    "ApiKeyUsage",
    "Asset",
    "AuditLog",
    "AvatarPreset",
    "ConsentRecord",
    "CreatorFollow",
    "CreatorSubscription",
    "CreditLedger",
    "PremiumCreditLedger",
    "FunnelEvent",
    "FunnelReport",
    "ErasureRequest",
    "ExternalIdentity",
    "GenerationProfile",
    "Job",
    "JobEvent",
    "JobPerformance",
    "MICRODOLLARS_PER_USD",
    "MarketplaceTemplate",
    "Invoice",
    "InvoiceLineItem",
    "MeteredUsage",
    "ModelCatalogEntry",
    "Notification",
    "PaymentIntent",
    "PriceVersion",
    "ProviderCatalog",
    "ProviderHealthEvent",
    "ProviderKey",
    "RepurposeClip",
    "RepurposeJob",
    "RetentionPolicy",
    "SpendPolicy",
    "SSOConnection",
    "SavedIdea",
    "Subscription",
    "ScheduledPublish",
    "ScimToken",
    "SecurityPolicy",
    "ShareLink",
    "SocialAccount",
    "TemplateRating",
    "UsageRecord",
    "User",
    "UserApiKey",
    "UserBrand",
    "UserPreset",
    "UserVoice",
    "WalletAccount",
    "WalletAccountOwner",
    "WalletLedgerEntry",
    "WalletSavedRecipient",
    "WalletTransfer",
    "WalletTransferAttestation",
    "WalletTransferChallenge",
    "WalletTransferPolicy",
    "WebhookDelivery",
    "WebhookSubscription",
    "Workspace",
    "WorkspaceMember",
]
