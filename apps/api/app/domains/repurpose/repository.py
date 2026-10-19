"""Repurpose persistence: owner-scoped jobs + clips."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db.repurpose import RepurposeClip, RepurposeJob


class RepurposeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # Jobs -------------------------------------------------------------- #
    def create_job(self, job: RepurposeJob) -> RepurposeJob:
        self._session.add(job)
        self._session.flush()
        return job

    def get_job_owned(self, job_id: str, user_id: str) -> RepurposeJob | None:
        row = self._session.get(RepurposeJob, job_id)
        if row is None or row.user_id != user_id:
            return None
        return row

    def list_jobs(self, user_id: str, *, limit: int = 50, offset: int = 0) -> list[RepurposeJob]:
        stmt = (
            select(RepurposeJob)
            .where(RepurposeJob.user_id == user_id)
            .order_by(RepurposeJob.created_at.desc(), RepurposeJob.id)
            .limit(max(1, min(200, limit)))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())

    def set_job_status(
        self, job: RepurposeJob, status: str, *, error: str = "", clip_count: int | None = None
    ) -> None:
        job.status = status
        if error:
            job.error = error
        if clip_count is not None:
            job.clip_count = int(clip_count)
        job.updated_at = datetime.now(timezone.utc)
        self._session.flush()

    # Clips ------------------------------------------------------------- #
    def replace_clips(self, job_id: str, user_id: str, clips: list[RepurposeClip]) -> None:
        """Delete any prior clips for the job and insert the new set."""
        existing = self._session.execute(
            select(RepurposeClip).where(RepurposeClip.repurpose_job_id == job_id)
        ).scalars().all()
        for row in existing:
            self._session.delete(row)
        for clip in clips:
            self._session.add(clip)
        self._session.flush()

    def list_clips(self, job_id: str, user_id: str) -> list[RepurposeClip]:
        stmt = (
            select(RepurposeClip)
            .where(
                RepurposeClip.repurpose_job_id == job_id,
                RepurposeClip.user_id == user_id,
            )
            .order_by(RepurposeClip.virality_score.desc(), RepurposeClip.start_s)
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_clip_owned(self, clip_id: str, user_id: str) -> RepurposeClip | None:
        row = self._session.get(RepurposeClip, clip_id)
        if row is None or row.user_id != user_id:
            return None
        return row
