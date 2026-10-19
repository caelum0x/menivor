"""Provider-marketplace / pay-as-you-go ORM models.

Implements the durable records from ``docs/reelforge/PROVIDER_MARKETPLACE_PLAN.md``
§4.2: a reviewed model **catalog** (providers, model listings, versioned prices,
generation profiles) and a USD **wallet** (accounts, an append-only ledger,
checkout payment intents, and normalized provider usage records).

Design rules (shared with :mod:`app.models.db.models`)
------------------------------------------------------
* Non-sequence primary keys are 32-char uuid hex strings (:func:`_uuid`).
* Timestamps are ``TIMESTAMP(timezone=True)`` defaulting to server ``now()``.
* **Money is integer microdollars** (``1 USD = 1_000_000`` units) — never a
  float and never a mutable balance row treated as the source of truth.
* ``wallet_ledger_entries`` is **append-only**: rows are never mutated after
  insert. The running ``available_after`` / ``reserved_after`` are materialized
  for O(1) balance reads, and :class:`WalletAccount` merely caches the latest
  pair. A refund is a new compensating row, never an edit of a historical one.

This module is imported by :mod:`app.models.db.models` so importing the ORM
package registers these tables on the shared ``Base.metadata`` for Alembic
autogenerate and ``create_all`` in tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
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

from app.models.db.base import Base

# One USD expressed in the integer accounting unit used across every money
# column in this module. Kept here so services/policies import a single source
# of truth instead of re-deriving the scale.
MICRODOLLARS_PER_USD = 1_000_000


def _uuid() -> str:
    """Generate a 32-char hex uuid4 primary key (mirrors ``models._uuid``)."""
    return uuid.uuid4().hex


# =========================================================================== #
# Catalog — reviewed providers, model listings, versioned prices, profiles
# =========================================================================== #
class ProviderCatalog(Base):
    """A reviewed upstream provider (Anthropic, ElevenLabs, HeyGen, …).

    A provider groups one or more :class:`ModelCatalogEntry` listings. It is
    never a client-supplied value — only an operator publishes one. ``enabled``
    keeps a provider in *shadow mode* (browsable/quotable internally but not yet
    a live product route) until its adapter, license, and health checks pass.
    """

    __tablename__ = "provider_catalogs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Stable machine key, e.g. "anthropic" / "elevenlabs" / "openrouter".
    provider_key: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(200), default="")
    # Data-residency / retention policy label surfaced to the user (free-form).
    region: Mapped[str] = mapped_column(String(80), default="")
    data_policy: Mapped[str] = mapped_column(String(200), default="")
    # healthy | degraded | down | unknown — an observation, never a gate on its
    # own (routing/policy decides admissibility).
    health_state: Mapped[str] = mapped_column(
        String(20), default="unknown", server_default=text("'unknown'"), nullable=False
    )
    # unconfigured | configured | revoked — whether the server holds working
    # credentials for this provider. Never stores the credential itself.
    credential_state: Mapped[str] = mapped_column(
        String(20),
        default="unconfigured",
        server_default=text("'unconfigured'"),
        nullable=False,
    )
    # Shadow-mode gate: a provider is browsable but not a live product route
    # until an operator flips this to true behind a launch flag.
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ModelCatalogEntry(Base):
    """A reviewed model/capability listing a user may select.

    One listing has exactly one ``capability`` and one ``metering_unit``; it
    never exposes a raw engine checkpoint or arbitrary provider URL. ``model_id``
    is the stable ReelForge catalog id (e.g. ``anthropic/claude-sonnet``) that a
    client submits — clients never send a raw provider identifier.
    """

    __tablename__ = "model_catalog_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Stable ReelForge catalog id submitted by clients, e.g. "pixelle/wan-i2v".
    model_id: Mapped[str] = mapped_column(
        String(160), unique=True, index=True, nullable=False
    )
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("provider_catalogs.id"), index=True, nullable=False
    )
    # script | voice | avatar | broll | image | music
    capability: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    # The unit this model is metered in, e.g. "output_tokens" / "characters" /
    # "seconds" / "clip" / "image". Must match the active price version's unit.
    metering_unit: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    # Opaque, growable metadata blobs (no migration needed to extend them).
    supported_inputs: Mapped[list] = mapped_column(JSON, default=list)
    output_limits: Mapped[dict] = mapped_column(JSON, default=dict)
    region: Mapped[str] = mapped_column(String(80), default="")
    data_policy: Mapped[str] = mapped_column(String(200), default="")
    # fast | standard | slow | "" (unknown)
    latency_band: Mapped[str] = mapped_column(String(20), default="")
    # available | limited | unavailable — routing availability.
    availability_state: Mapped[str] = mapped_column(
        String(20),
        default="available",
        server_default=text("'available'"),
        nullable=False,
    )
    # shadow | preview | ga | deprecated. Shadow = browsable/quotable internally
    # but not a live billable route; the default keeps new imports non-billable.
    release_status: Mapped[str] = mapped_column(
        String(20), default="shadow", server_default=text("'shadow'"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Hot browse query filters on (capability, release_status/availability).
        Index("ix_model_catalog_capability_release", "capability", "release_status"),
    )


class PriceVersion(Base):
    """An immutable price snapshot for one model, effective over a time window.

    A quote resolves the *active* version (``effective_from <= now`` and
    ``effective_to`` null-or-future, highest ``version``) and stores its id on
    the job so a later catalog/price change can never re-price an accepted job.
    All money is integer microdollars.
    """

    __tablename__ = "price_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    model_entry_id: Mapped[str] = mapped_column(
        ForeignKey("model_catalog_entries.id"), index=True, nullable=False
    )
    # Denormalized catalog id so a quote can resolve a price without a join.
    model_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), default="USD", server_default=text("'USD'"), nullable=False
    )
    # The metering unit this price is quoted in (mirrors the model's unit).
    unit: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    # Microdollars per one ``unit`` (e.g. $0.10/sec -> 100_000).
    unit_price_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), default=0, nullable=False
    )
    # Minimum charge per operation regardless of quantity (0 = none).
    min_charge_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    # Fixed per-operation surcharge (e.g. a flat per-clip video price).
    flat_fee_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    # Growable quote rules (default estimate quantity, rounding, caps, …).
    quote_rules: Mapped[dict] = mapped_column(JSON, default=dict)
    # Monotonic per-model version; a new price is a new row, never an edit.
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    # manual | provider_import | shadow — provenance of the price for audit.
    source: Mapped[str] = mapped_column(
        String(40), default="manual", server_default=text("'manual'"), nullable=False
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("model_id", "version", name="uq_price_versions_model_version"),
        Index("ix_price_versions_model_effective", "model_id", "effective_from"),
    )


class GenerationProfile(Base):
    """A named stage->model selection for a reel (script/voice/avatar/broll).

    Either **curated** (``owner_user_id`` null, ``is_curated`` true) so every
    user can pick it, or **owned** by a user/workspace. ``stages`` and
    ``routing`` are opaque JSON so the profile schema can grow without a
    migration; ``routing.max_cost_usd`` is mirrored into ``max_cost_micros`` for
    integer enforcement at quote time.
    """

    __tablename__ = "generation_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Stable public slug, e.g. "creator-fast-v1". Unique across the catalog.
    slug: Mapped[str] = mapped_column(
        String(120), unique=True, index=True, nullable=False
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True, default=None
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True, default=None
    )
    display_name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    # {"script": {"model_id": …}, "voice": {"model_id": …}, …}
    stages: Mapped[dict] = mapped_column(JSON, default=dict)
    # {"fallback": "none", "max_cost_usd": "2.50"}
    routing: Mapped[dict] = mapped_column(JSON, default=dict)
    # Integer mirror of routing.max_cost_usd; 0 means "no profile-level cap".
    max_cost_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    is_curated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# =========================================================================== #
# Wallet — accounts, append-only ledger, payment intents, usage records
# =========================================================================== #
class WalletAccount(Base):
    """A per-user or per-workspace USD wallet.

    ``available_micros`` is spendable now; ``reserved_micros`` is held against
    in-flight jobs. Both are **caches** of the newest ``wallet_ledger_entries``
    row for this account — the ledger, not this row, is the accounting source of
    truth. Exactly one of ``user_id`` / ``workspace_id`` identifies the owner.
    """

    __tablename__ = "wallet_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True, default=None
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True, default=None
    )
    currency: Mapped[str] = mapped_column(
        String(8), default="USD", server_default=text("'USD'"), nullable=False
    )
    available_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    reserved_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    # Mint-settlement rail: the payer's mint-server ``acct_...`` id, provisioned
    # lazily on the owner's first Mint hold (NULL until then). Additive +
    # backward-compatible — the local microdollar ledger ignores this column.
    mint_account_id: Mapped[str | None] = mapped_column(
        String(40), nullable=True, default=None
    )
    # Stable public destination for inbound Mint transfers. This is safe to
    # share and cannot authorize a debit from the owning account.
    mint_receive_address: Mapped[str | None] = mapped_column(
        String(128), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # A user (or workspace) has at most one wallet. Multiple NULLs are
        # allowed on both SQLite and Postgres, so a personal account (NULL
        # workspace_id) and a workspace account (NULL user_id) never collide.
        UniqueConstraint("user_id", name="uq_wallet_accounts_user"),
        UniqueConstraint("workspace_id", name="uq_wallet_accounts_workspace"),
        # Mint rails are enforced by a UNIQUE INDEX (not a table UniqueConstraint)
        # because these columns are ALTER-added to an already-populated
        # ``wallet_accounts`` table: a unique index is created cross-dialect via
        # ``CREATE UNIQUE INDEX`` (see migrations ``b8e4f02ad573`` /
        # ``e1b7c4d92f60``), whereas ADD CONSTRAINT would force a SQLite table
        # rebuild of this money table. Nullable columns permit multiple NULLs, so
        # a not-yet-provisioned account is unconstrained until its first hold.
        Index(
            "uq_wallet_accounts_mint_account_id",
            "mint_account_id",
            unique=True,
        ),
        Index(
            "uq_wallet_accounts_mint_receive_address",
            "mint_receive_address",
            unique=True,
        ),
    )


class WalletAccountOwner(Base):
    """One typed principal ownership edge for a wallet ledger account.

    The account remains the only balance/ledger node.  This edge lets Menivor
    authorize personal and workspace sources today without adding another
    ledger, while reserving the same representation for future agent/service
    principals.  Agent/service edges are data-representable but the wallet
    source resolver deliberately does not authorize them yet.
    """

    __tablename__ = "wallet_account_owners"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_accounts.id", ondelete="CASCADE"), nullable=False
    )
    principal_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    principal_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("account_id", name="uq_wallet_account_owners_account"),
        UniqueConstraint(
            "principal_kind",
            "principal_ref",
            name="uq_wallet_account_owners_principal",
        ),
        Index(
            "ix_wallet_account_owners_principal",
            "principal_kind",
            "principal_ref",
        ),
    )


class WalletDestinationProfile(Base):
    """A public workspace, agent, or service identity backed by one wallet.

    These are product identities, not aliases. Agent/service profiles own a
    dedicated Mint-backed account; workspace profiles route to the workspace's
    existing shared account. ``handle`` is an explicit typed destination such
    as ``agent:caption-bot`` so it cannot collide with a person's ``@handle``.
    """

    __tablename__ = "wallet_destination_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    handle: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_accounts.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=True
    )
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('workspace', 'agent', 'service')",
            name="ck_wallet_destination_profiles_kind",
        ),
    )


class WalletTransferPolicy(Base):
    """Account-native outbound transfer limits (0 means no configured limit)."""

    __tablename__ = "wallet_transfer_policies"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    per_transfer_limit_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=1_000_000_000,
        server_default=text("1000000000"),
        nullable=False,
    )
    daily_limit_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WalletLedgerEntry(Base):
    """Append-only wallet event. Balance == cumulative deltas; cached in *_after.

    Each row records how one event moved ``available`` and ``reserved`` money
    and the resulting running totals. Reservation lifecycle:

    * ``reserve``  : available -R, reserved +R  (hold the max quoted cost)
    * ``settle``   : available +(R-C), reserved -R  (charge actual C<=R, free rest)
    * ``release``  : available +R, reserved -R  (cancel before charge)
    * ``grant``    : available +credit  (verified payment webhook only)
    * ``refund``   : available +amount  (compensating entry)
    * ``adjustment``: operator/opening-balance correction (audited)

    Rows are never mutated after insert.
    """

    __tablename__ = "wallet_ledger_entries"

    # BigInteger on Postgres/Neon; INTEGER on SQLite so autoincrement works.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    account_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_accounts.id"), index=True, nullable=False
    )
    # grant | reserve | settle | release | refund | adjustment
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Finer-grained reason: purchase | job_reserve | job_settle | job_release |
    # provider_refund | opening_balance | correction | …
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    available_delta: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), default=0, nullable=False
    )
    reserved_delta: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), default=0, nullable=False
    )
    available_after: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False
    )
    reserved_after: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False
    )
    # Optional linkage for reconciliation (all nullable, all indexed where hot).
    # ``job_id`` is a cross-table reconciliation pointer: the classic pipeline
    # sets it to a ``jobs.id`` while the media gateway sets it to a
    # ``media_jobs.id``. It therefore cannot carry a hard FK to a single table;
    # it is a plain indexed string. (A FK to ``jobs.id`` here silently passed
    # under SQLite — which does not enforce FKs by default — but raised a
    # ForeignKeyViolation on Postgres for every media-gateway reservation.)
    job_id: Mapped[str | None] = mapped_column(
        String(32), index=True, nullable=True, default=None
    )
    payment_intent_id: Mapped[str | None] = mapped_column(
        ForeignKey("payment_intents.id"), index=True, nullable=True, default=None
    )
    usage_record_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    price_version_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    correlation_id: Mapped[str] = mapped_column(
        String(64), default="", server_default=text("''"), nullable=False
    )
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (
        # Newest-first activity list is an O(index) scan per account.
        Index("ix_wallet_ledger_account_id_id", "account_id", "id"),
    )


class WalletTransfer(Base):
    """Durable person-to-person Mint transfer command and result.

    This row is orchestration/audit state, not a second balance ledger. The
    authoritative debit and credit happen atomically in Mint; Menivor records
    the public identities involved and the complete signed Mint receipt so
    retries can return the same product result without exposing either Mint
    account id. ``pending`` is committed before the external call: it is the
    durable reconciliation command for an ambiguous Mint response.
    """

    __tablename__ = "wallet_transfers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    sender_account_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_accounts.id"), index=True, nullable=False
    )
    recipient_account_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_accounts.id"), index=True, nullable=False
    )
    sender_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    recipient_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True, default=None
    )
    sender_handle: Mapped[str] = mapped_column(String(64), nullable=False)
    # Compatibility name: stores either an exact Menivor handle or a public
    # Mint `ait1...` destination. Typed identity lives in kind/ref/label.
    recipient_handle: Mapped[str] = mapped_column(String(128), nullable=False)
    recipient_kind: Mapped[str] = mapped_column(
        String(20),
        default="personal",
        server_default=text("'personal'"),
        nullable=False,
    )
    recipient_ref: Mapped[str] = mapped_column(
        String(128), default="", server_default=text("''"), nullable=False
    )
    recipient_label: Mapped[str] = mapped_column(
        String(200), default="", server_default=text("''"), nullable=False
    )
    sender_source_kind: Mapped[str] = mapped_column(
        String(20),
        default="personal",
        server_default=text("'personal'"),
        nullable=False,
    )
    sender_source_ref: Mapped[str] = mapped_column(
        String(128), default="", server_default=text("''"), nullable=False
    )
    sender_source_label: Mapped[str] = mapped_column(
        String(200), default="", server_default=text("''"), nullable=False
    )
    challenge_id: Mapped[str | None] = mapped_column(
        ForeignKey("wallet_transfer_challenges.id"), nullable=True, default=None
    )
    amount_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default=text("'pending'"), nullable=False
    )
    mint_operation: Mapped[str] = mapped_column(
        String(96), default="", server_default=text("''"), nullable=False
    )
    mint_receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    mint_first_seq: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=True, default=None
    )
    mint_idempotent_replay: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    reconcile_lease_owner: Mapped[str | None] = mapped_column(
        String(96), nullable=True, default=None
    )
    reconcile_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    reconcile_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    reconcile_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    reconcile_last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    reconcile_last_error: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    attestation: Mapped["WalletTransferAttestation | None"] = relationship(
        back_populates="transfer",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "sender_account_id",
            "idempotency_key",
            name="uq_wallet_transfers_sender_idempotency",
        ),
        Index(
            "ix_wallet_transfers_reconcile_ready",
            "status",
            "reconcile_after",
            "reconcile_lease_expires_at",
            "created_at",
        ),
        Index(
            "ix_wallet_transfers_sender_status_created",
            "sender_account_id",
            "status",
            "created_at",
        ),
        UniqueConstraint("challenge_id", name="uq_wallet_transfers_challenge"),
    )


class WalletTransferChallenge(Base):
    """One-time review binding consumed with a durable transfer command."""

    __tablename__ = "wallet_transfer_challenges"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    source_account_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_accounts.id"), index=True, nullable=False
    )
    recipient_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, default=None
    )
    recipient_account_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_accounts.id"), nullable=False
    )
    recipient_handle: Mapped[str] = mapped_column(String(128), nullable=False)
    recipient_kind: Mapped[str] = mapped_column(
        String(20),
        default="personal",
        server_default=text("'personal'"),
        nullable=False,
    )
    recipient_ref: Mapped[str] = mapped_column(
        String(128), default="", server_default=text("''"), nullable=False
    )
    recipient_label: Mapped[str] = mapped_column(
        String(200), default="", server_default=text("''"), nullable=False
    )
    binding_version: Mapped[int] = mapped_column(
        Integer, default=2, server_default=text("2"), nullable=False
    )
    recipient_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    consumed_transfer_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "source_account_id",
            "idempotency_key",
            name="uq_wallet_transfer_challenges_source_key",
        ),
    )


class WalletSavedRecipient(Base):
    """An actor-owned recipient shortcut bound to immutable account identity."""

    __tablename__ = "wallet_saved_recipients"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_account_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_accounts.id", ondelete="CASCADE"), nullable=False
    )
    recipient_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    recipient_account_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_accounts.id"), nullable=False
    )
    recipient_handle: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(
        String(100), default="", server_default=text("''"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "source_account_id",
            "recipient_account_id",
            name="uq_wallet_saved_recipients_owner_source_recipient",
        ),
        Index(
            "ix_wallet_saved_recipients_owner_source",
            "owner_user_id",
            "source_account_id",
            "created_at",
        ),
    )


class WalletTransferAttestation(Base):
    """A separately persisted, locally verified Mint transfer attestation.

    ``payload_base64url`` preserves the exact bytes Mint signed. This record
    proves verification of one transfer against a pinned key and local command
    mappings; it is not a second ledger or a claim about global conservation.
    """

    __tablename__ = "wallet_transfer_attestations"

    transfer_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_transfers.id", ondelete="CASCADE"), primary_key=True
    )
    format: Mapped[str] = mapped_column(String(64), nullable=False)
    signer_key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_base64url: Mapped[str] = mapped_column(Text, nullable=False)
    digest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_hex: Mapped[str] = mapped_column(String(128), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    transfer: Mapped[WalletTransfer] = relationship(back_populates="attestation")


class PaymentIntent(Base):
    """A wallet top-up checkout: idempotent quote snapshot + provider status.

    A credit **grant** may only occur when a verified provider webhook flips a
    matching intent to ``confirmed`` — never from a browser success redirect.
    The platform fee/tax/processor amounts are retained here (separate from the
    wallet balance) so the customer sees the exact card charge before paying.
    All money is integer microdollars.
    """

    __tablename__ = "payment_intents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("wallet_accounts.id"), index=True, nullable=False
    )
    # The acting user (audit); a workspace top-up records the actor here.
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True, default=None
    )
    # Client-supplied checkout idempotency key (scoped per account).
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), default="USD", server_default=text("'USD'"), nullable=False
    )
    # Wallet credit the customer will receive on confirmation.
    credit_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False
    )
    # Disclosed platform fee, tax and processor pass-through (0 when N/A).
    fee_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    tax_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    processor_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    # The total charged to the card = credit + fee + tax + processor.
    total_charge_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False
    )
    # Fee rate applied, in basis points (500 = 5%), snapshotted for audit.
    fee_rate_bps: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # Versioned fee schedule that produced this quote (governance/audit).
    fee_schedule_version: Mapped[str] = mapped_column(
        String(40), default="", server_default=text("''"), nullable=False
    )
    payment_provider: Mapped[str] = mapped_column(String(40), default="")
    provider_ref: Mapped[str] = mapped_column(String(200), default="")
    # quoted | pending | confirmed | failed | canceled | expired
    status: Mapped[str] = mapped_column(
        String(20), default="quoted", server_default=text("'quoted'"), nullable=False
    )
    quote_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # A repeated checkout submit with the same key resolves to one intent,
        # so a duplicate can never create two charges.
        UniqueConstraint(
            "account_id", "idempotency_key", name="uq_payment_intents_account_key"
        ),
    )


class UsageRecord(Base):
    """Normalized provider usage/cost for one job stage, kept for reconciliation.

    Retains provider-reported usage, the ReelForge-normalized ``cost_micros``,
    the resolved ``price_version_id``, and a ``correlation_id`` so every provider
    invoice line can be tied back to one or more jobs/stages. Append-only.
    """

    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id"), index=True, nullable=True, default=None
    )
    account_id: Mapped[str | None] = mapped_column(
        ForeignKey("wallet_accounts.id"), index=True, nullable=True, default=None
    )
    stage: Mapped[str] = mapped_column(String(40), default="")
    model_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    provider_key: Mapped[str] = mapped_column(String(64), default="")
    price_version_id: Mapped[str] = mapped_column(String(32), default="")
    unit: Mapped[str] = mapped_column(String(40), default="")
    # Provider-reported quantity in ``unit`` (e.g. seconds, characters, tokens).
    quantity_units: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    cost_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(8), default="USD", server_default=text("'USD'"), nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(64), default="")
    # Opaque provider payload for audit; growable without a migration.
    raw_usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ProviderKey(Base):
    """A customer's own (BYOK) provider credential, encrypted at rest.

    Stores a user/workspace-owned upstream API key so a job can route through the
    customer's own provider account (PROVIDER_MARKETPLACE_PLAN.md §4.1/§8.4). The
    raw secret is NEVER stored or returned — only a Fernet ciphertext
    (``encrypted_secret``) and a non-secret ``key_prefix`` display hint. Every use
    is audited (``last_used_at`` / ``use_count``) and a key can be revoked
    immediately (``status='revoked'``) without deletion so the audit trail stays
    intact. Envelope/KMS encryption is a later hardening; this reuses the same
    Fernet at-rest scheme as the OAuth token store.
    """

    __tablename__ = "provider_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True, default=None
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True, default=None
    )
    provider_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), default="")
    # Non-secret display hint (e.g. "sk-…AB"); safe to return to the owner.
    key_prefix: Mapped[str] = mapped_column(String(40), default="")
    # Fernet ciphertext of the raw key. Never returned by any endpoint.
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(
        String(40),
        default="generation",
        server_default=text("'generation'"),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # active | revoked
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default=text("'active'"), nullable=False
    )
    use_count: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Hot lookup: the active key(s) for a user + provider, by priority.
        Index("ix_provider_keys_user_provider", "user_id", "provider_key", "status"),
    )


class SpendPolicy(Base):
    """Per-user/workspace spend controls: a monthly budget cap + BYOK consent.

    ``monthly_budget_micros`` = 0 means unlimited; otherwise a reservation is
    refused once the calendar-month settled spend would exceed it.
    ``byok_allowed`` is the explicit consent gate before a customer's own
    provider key is ever used for outbound calls (PROVIDER_MARKETPLACE_PLAN.md
    §1.3/§8.4). Exactly one of ``user_id`` / ``workspace_id`` identifies the owner.
    """

    __tablename__ = "spend_policies"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True, default=None
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True, default=None
    )
    monthly_budget_micros: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    byok_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    # Minimum workspace role allowed to SPEND the shared pool (owner|admin|member).
    # Personal policies ignore this. Lets a team restrict spending to admins.
    spend_min_role: Mapped[str] = mapped_column(
        String(20), default="member", server_default=text("'member'"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_spend_policies_user"),
        UniqueConstraint("workspace_id", name="uq_spend_policies_workspace"),
    )


class ProviderHealthEvent(Base):
    """Append-only provider execution observation (for health/uptime routing).

    Each provider run records one row (``ok`` + ``latency_ms``); an uptime % and
    latency band are derived over a recent window and fed back into routing
    (health-weighted selection, à la OpenRouter avoiding unstable providers) and
    a public status view. Rows are never mutated.
    """

    __tablename__ = "provider_health_events"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    provider_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    capability: Mapped[str] = mapped_column(String(40), default="")
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (
        Index("ix_provider_health_provider_created", "provider_key", "created_at"),
    )


__all__ = [
    "MICRODOLLARS_PER_USD",
    "ProviderCatalog",
    "ProviderHealthEvent",
    "ModelCatalogEntry",
    "PriceVersion",
    "GenerationProfile",
    "WalletAccount",
    "WalletAccountOwner",
    "WalletLedgerEntry",
    "WalletSavedRecipient",
    "WalletTransfer",
    "WalletTransferAttestation",
    "WalletTransferChallenge",
    "WalletTransferPolicy",
    "PaymentIntent",
    "ProviderKey",
    "SpendPolicy",
    "UsageRecord",
]
