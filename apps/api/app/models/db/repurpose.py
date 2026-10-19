"""Repurposing-engine ORM models: long video -> ranked highlight clips.

A creator submits a long recording/URL; ReelForge transcribes it, an LLM ranks
transcript windows for virality, and the top non-overlapping clips become
suggested short-form cuts — each promotable into a reel/generation job. Two
tables: ``repurpose_jobs`` (the source + lifecycle) and ``repurpose_clips`` (the
suggested cuts). Shares the design rules of :mod:`app.models.db.models`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class RepurposeJob(Base):
    """A long-video repurposing request and its transcribe/rank lifecycle."""

    __tablename__ = "repurpose_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # upload (R2 key) | url (external video URL)
    source_kind: Mapped[str] = mapped_column(
        String(20), default="upload", server_default=text("'upload'"), nullable=False
    )
    source_ref: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    language: Mapped[str] = mapped_column(
        String(16), default="auto", server_default=text("'auto'"), nullable=False
    )
    # created | transcribing | ranking | ready | failed
    status: Mapped[str] = mapped_column(
        String(20), default="created", server_default=text("'created'"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), default="")
    duration_s: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    clip_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    error: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RepurposeClip(Base):
    """One suggested short-form cut from a repurpose job (a scored window)."""

    __tablename__ = "repurpose_clips"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    repurpose_job_id: Mapped[str] = mapped_column(
        ForeignKey("repurpose_jobs.id"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # Clip window within the source, in whole seconds.
    start_s: Mapped[int] = mapped_column(Integer, nullable=False)
    end_s: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="")
    hook: Mapped[str] = mapped_column(String(300), default="")
    transcript: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    # 0..100 virality score from the ranker.
    virality_score: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    reason: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    # suggested | promoted | dismissed
    status: Mapped[str] = mapped_column(
        String(20), default="suggested", server_default=text("'suggested'"), nullable=False
    )
    # Set when the clip is promoted into a reel/generation job.
    reel_job_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Rank clips within a job by score for the review list.
        Index("ix_repurpose_clips_job_score", "repurpose_job_id", "virality_score"),
    )


__all__ = ["RepurposeJob", "RepurposeClip"]
