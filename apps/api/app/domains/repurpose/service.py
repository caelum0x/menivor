"""Repurpose service: create job, rank transcript into clips, promote to reels.

Transcription and LLM ranking are injectable seams so the product logic is
testable without external calls; the highlight selection is the pure
:mod:`policy`. Business failures raise :class:`RepurposeError`.

Auto mode: ranking with no caller-supplied segments queues
:func:`run_auto_repurpose` on a worker, which downloads the source (an owned
upload key or an https URL), transcribes it (WhisperX word timings, shared with
the clipping domain), windows the transcript and runs the virality ranker —
producing the job's suggested clips without the client ever handling a
transcript.
"""

from __future__ import annotations

import shutil
import tempfile
from typing import Callable

from loguru import logger

from sqlalchemy.orm import Session

from app.domains.repurpose import policy
from app.domains.repurpose.repository import RepurposeRepository
from app.domains.repurpose.schemas import clip_view, job_view
from app.models.db.repurpose import RepurposeClip, RepurposeJob

# A ranker scores + annotates raw transcript segments:
#   ranker(segments: list[dict], *, language: str) -> list[dict]  (adds 'score' etc.)
Ranker = Callable[..., list[dict]]


class RepurposeError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _needs_ranking(segments: list[dict]) -> bool:
    """True when any segment lacks a score (so the ranker must run)."""
    return any(s.get("score") in (None, "") for s in segments)


class RepurposeService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = RepurposeRepository(session)

    # ------------------------------------------------------------------ #
    def create_job(
        self,
        user_id: str,
        *,
        source_kind: str,
        source_ref: str,
        language: str = "auto",
        title: str = "",
    ) -> dict:
        source_ref = (source_ref or "").strip()
        if not source_ref:
            raise RepurposeError(400, "source_ref is required")
        if source_kind not in {"upload", "url"}:
            raise RepurposeError(400, "source_kind must be 'upload' or 'url'")
        if source_kind == "url" and not source_ref.lower().startswith("https://"):
            raise RepurposeError(400, "source URL must be an https:// link")
        if source_kind == "upload":
            from app.domains.media.service import MediaDomainError, require_owned_asset

            try:
                require_owned_asset(self._session, user_id=user_id, key=source_ref)
            except MediaDomainError as exc:
                raise RepurposeError(403, "source upload does not belong to the caller") from exc
        job = self._repo.create_job(
            RepurposeJob(
                user_id=user_id,
                source_kind=source_kind,
                source_ref=source_ref,
                language=language or "auto",
                title=title or "",
                status="created",
            )
        )
        return job_view(job)

    def get_job(self, job_id: str, user_id: str) -> dict:
        job = self._repo.get_job_owned(job_id, user_id)
        if job is None:
            raise RepurposeError(404, "repurpose job not found")
        return job_view(job)

    def list_jobs(self, user_id: str) -> list[dict]:
        return [job_view(j) for j in self._repo.list_jobs(user_id)]

    def list_clips(self, job_id: str, user_id: str) -> list[dict]:
        if self._repo.get_job_owned(job_id, user_id) is None:
            raise RepurposeError(404, "repurpose job not found")
        return [clip_view(c) for c in self._repo.list_clips(job_id, user_id)]

    # ------------------------------------------------------------------ #
    def rank(
        self,
        job_id: str,
        user_id: str,
        *,
        segments: list[dict],
        ranker: Ranker | None = None,
        max_clips: int = policy.DEFAULT_MAX_CLIPS,
        min_len_s: int = policy.DEFAULT_MIN_LEN_S,
        max_len_s: int = policy.DEFAULT_MAX_LEN_S,
        min_score: int = policy.DEFAULT_MIN_SCORE,
    ) -> list[dict]:
        """Rank transcript ``segments`` into highlight clips and persist them.

        Pre-scored segments are used directly (deterministic); unscored segments
        are passed to ``ranker`` (default: the LLM ranker). The pure policy then
        selects the top non-overlapping clips within the duration band.
        """
        job = self._repo.get_job_owned(job_id, user_id)
        if job is None:
            raise RepurposeError(404, "repurpose job not found")
        if not segments:
            raise RepurposeError(400, "at least one transcript segment is required")

        self._repo.set_job_status(job, "ranking")
        try:
            scored = list(segments)
            if _needs_ranking(scored):
                rank_fn = ranker or _default_ranker
                scored = rank_fn(scored, language=job.language)
            candidates = [policy.candidate_from_dict(s) for s in scored]
            selected = policy.select_highlights(
                candidates,
                max_clips=max_clips,
                min_len_s=min_len_s,
                max_len_s=max_len_s,
                min_score=min_score,
            )
        except RepurposeError:
            self._repo.set_job_status(job, "failed", error="ranking failed")
            raise
        except Exception as exc:  # noqa: BLE001 - surface as a clean 502 + failed job
            self._repo.set_job_status(job, "failed", error=str(exc)[:500])
            raise RepurposeError(502, f"ranking failed: {exc}") from exc

        rows = [
            RepurposeClip(
                repurpose_job_id=job_id,
                user_id=user_id,
                start_s=c.start_s,
                end_s=c.end_s,
                title=c.title,
                hook=c.hook,
                transcript=c.transcript,
                virality_score=c.score,
                reason=c.reason,
                status="suggested",
            )
            for c in selected
        ]
        self._repo.replace_clips(job_id, user_id, rows)
        self._repo.set_job_status(job, "ready", clip_count=len(rows))
        return [clip_view(c) for c in rows]

    def request_auto_rank(self, job_id: str, user_id: str) -> dict:
        """Mark a job for server-side transcription + ranking; return its view.

        Idempotent while a run is in flight (a job already ``transcribing`` or
        ``ranking`` is returned unchanged, and the caller must not enqueue again —
        signalled by ``queued=False``).
        """
        job = self._repo.get_job_owned(job_id, user_id)
        if job is None:
            raise RepurposeError(404, "repurpose job not found")
        if job.status in AUTO_ACTIVE_STATUSES:
            return {**job_view(job), "queued": False}
        job.error = ""
        self._repo.set_job_status(job, "transcribing")
        return {**job_view(job), "queued": True}

    def promote_clip(self, clip_id: str, user_id: str) -> dict:
        """Mark a clip promoted and return a ready-to-submit reel draft.

        The draft maps the clip onto a reel create (``video_script`` = the clip
        transcript; the source window carries the recording key + in/out). The
        client submits it to ``POST /jobs`` — this domain never spends credits.
        """
        clip = self._repo.get_clip_owned(clip_id, user_id)
        if clip is None:
            raise RepurposeError(404, "clip not found")
        job = self._session.get(RepurposeJob, clip.repurpose_job_id)
        clip.status = "promoted"
        self._session.flush()
        return {
            "clip": clip_view(clip),
            "reel_draft": {
                "video_subject": clip.title or (clip.hook or "Repurposed clip"),
                "video_script": clip.transcript,
                "source_kind": getattr(job, "source_kind", "upload"),
                "source_ref": getattr(job, "source_ref", ""),
                "start_s": clip.start_s,
                "end_s": clip.end_s,
            },
        }


def _default_ranker(segments: list[dict], *, language: str = "auto") -> list[dict]:
    """LLM virality ranker (lazy). Raises 503 when the LLM layer is unavailable.

    Delegates to the script/LLM service to score each transcript window 0..100
    and add a hook/title/reason. Kept lazy + guarded so the domain imports even
    when the LLM stack is absent; tests inject a fake ranker instead.
    """
    try:
        from app.services.repurpose_rank import rank_segments  # type: ignore
    except Exception as exc:  # noqa: BLE001 - optional integration
        raise RepurposeError(
            503,
            "automatic ranking is unavailable; submit pre-scored segments",
        ) from exc
    return rank_segments(segments, language=language)


AUTO_ACTIVE_STATUSES = ("transcribing", "ranking")


def run_auto_repurpose(
    job_id: str,
    *,
    max_clips: int = policy.DEFAULT_MAX_CLIPS,
    min_len_s: int = policy.DEFAULT_MIN_LEN_S,
    max_len_s: int = policy.DEFAULT_MAX_LEN_S,
    min_score: int = policy.DEFAULT_MIN_SCORE,
) -> dict:
    """Worker entry: download -> transcribe -> window -> rank -> persist clips.

    Never leaves a job stuck: any failure marks it ``failed`` with a short,
    secret-free reason the client shows.
    """
    from app.domains.clipping.policy import segments_from_words
    from app.domains.clipping.service import (
        ClippingError,
        _resolve_source,
        default_transcriber,
    )
    from app.models.db.base import get_session

    with get_session() as session:
        job = session.get(RepurposeJob, job_id)
        if job is None:
            return {"job_id": job_id, "status": "missing"}
        user_id = str(job.user_id)
        language = job.language or "auto"
        params = (
            {"source_video_key": job.source_ref}
            if job.source_kind == "upload"
            else {"source_url": job.source_ref}
        )

    workdir = tempfile.mkdtemp(prefix=f"repurpose-{job_id}-")
    try:
        try:
            source_path, _ref = _resolve_source(params, workdir)
            words = list(default_transcriber(source_path, language) or [])
        except ClippingError as exc:
            _fail(job_id, exc.message)
            return {"job_id": job_id, "status": "failed"}
        except Exception as exc:  # noqa: BLE001 - surface a clean failure
            logger.error(f"repurpose {job_id}: transcription failed: {exc}")
            _fail(job_id, "could not download or transcribe the source video")
            return {"job_id": job_id, "status": "failed"}

        if not words:
            _fail(job_id, "no speech was detected in this video")
            return {"job_id": job_id, "status": "failed"}

        segments = segments_from_words(words, window_s=max_len_s)
        duration_s = int(max((float(getattr(w, "end_s", 0) or 0) for w in words), default=0))
        with get_session() as session:
            job = session.get(RepurposeJob, job_id)
            if job is not None:
                job.duration_s = duration_s
            try:
                clips = RepurposeService(session).rank(
                    job_id,
                    user_id,
                    segments=segments,
                    max_clips=max_clips,
                    min_len_s=min_len_s,
                    max_len_s=max_len_s,
                    min_score=min_score,
                )
            except RepurposeError as exc:
                # rank() already marked the job failed inside this session.
                logger.warning(f"repurpose {job_id}: ranking failed: {exc.message}")
                return {"job_id": job_id, "status": "failed"}
        return {"job_id": job_id, "status": "ready", "clip_count": len(clips)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _fail(job_id: str, reason: str) -> None:
    """Mark a repurpose job failed with ``reason`` (best-effort, never raises)."""
    try:
        from app.models.db.base import get_session

        with get_session() as session:
            job = session.get(RepurposeJob, job_id)
            if job is not None:
                RepurposeRepository(session).set_job_status(
                    job, "failed", error=str(reason)[:500]
                )
    except Exception as exc:  # noqa: BLE001 - bookkeeping only
        logger.error(f"repurpose {job_id}: could not record failure: {exc}")
