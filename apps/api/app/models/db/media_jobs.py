"""Unified media-gateway generation persistence.

Every accepted image, video, or audio request owns one durable row. Async jobs
are reconciled from their provider reference; synchronous images are written as
terminal rows so account history survives a client restart. Registered on
``Base.metadata`` via ``migrations/env.py``. Nullability per repo rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base, jsonb_variant


def _uuid() -> str:
    return uuid.uuid4().hex


class MediaJob(Base):
    """One owner-scoped media generation and its settlement snapshot."""

    __tablename__ = "media_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Stable business request id shared by Prism, Mint, Passport, Abacus and
    # downstream evidence/margin projections. It is not an HTTP trace id.
    correlation_id: Mapped[str] = mapped_column(
        String(128), default="", server_default=text("''"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    modality: Mapped[str] = mapped_column(String(10), default="video", server_default=text("'video'"), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_ref: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"), nullable=False)
    status_url: Mapped[str] = mapped_column(String(500), default="", server_default=text("''"), nullable=False)
    response_url: Mapped[str] = mapped_column(String(500), default="", server_default=text("''"), nullable=False)
    # Versioned, secret-free provider-adapter-kit result/handle snapshot.  The
    # legacy split columns remain during dual-read migration and for public
    # projections; recovery prefers this immutable submit-time model/adapter
    # record so catalog changes cannot redirect an accepted job.
    provider_execution: Mapped[dict] = mapped_column(
        jsonb_variant(),
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    # queued | in_progress | completed | failed
    status: Mapped[str] = mapped_column(
        String(20), default="queued", server_default=text("'queued'"), index=True, nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    seconds: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    output_url: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    held_cost_micros: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    actual_cost_micros: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    # Optional immutable Identity Lock binding. Empty fields mean this is an
    # ordinary legacy generation. Bound jobs must progress resolved -> attested.
    identity_passport_id: Mapped[str] = mapped_column(String(160), default="", server_default=text("''"), nullable=False)
    identity_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    identity_content_digest: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"), nullable=False)
    identity_provider: Mapped[str] = mapped_column(String(80), default="", server_default=text("''"), nullable=False)
    identity_provenance_id: Mapped[str] = mapped_column(String(180), default="", server_default=text("''"), nullable=False)
    identity_status: Mapped[str] = mapped_column(String(20), default="none", server_default=text("'none'"), nullable=False)
    # Settlement rail is chosen once before provider I/O and never inferred from
    # the current rollout stage again.  ``settlement_intent`` is secret-free and
    # durably fences the one remote Mint operation that recovery may replay.
    settlement_rail: Mapped[str] = mapped_column(
        String(12), default="local", server_default=text("'local'"), nullable=False
    )
    settlement_outcome: Mapped[str] = mapped_column(
        String(20), default="", server_default=text("''"), nullable=False
    )
    settlement_intent: Mapped[dict] = mapped_column(
        jsonb_variant(),
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    # Generic Mint hold + authentic signed capture/release receipt. Identity
    # attestation consumes the same capture proof; ordinary media persists it too.
    mint_hold_id: Mapped[str] = mapped_column(String(160), default="", server_default=text("''"), nullable=False)
    settlement_request_id: Mapped[str] = mapped_column(String(128), default="", server_default=text("''"), nullable=False)
    settlement_payer_account: Mapped[str] = mapped_column(String(160), default="", server_default=text("''"), nullable=False)
    settlement_receipt: Mapped[dict] = mapped_column(
        jsonb_variant(),
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    settlement_attestation: Mapped[dict] = mapped_column(
        jsonb_variant(),
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    settlement_settled_at_ms: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"), nullable=False)
    settlement_verified_at_ms: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    error: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
