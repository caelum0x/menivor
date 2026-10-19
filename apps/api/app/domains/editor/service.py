"""Editor command transactions; media execution lives in ``workflows``."""

from __future__ import annotations

from typing import Any

from app.core.idempotency import hash_request_payload, reserve_idempotency_key
from app.models.const import TASK_STATE_COMPLETE
from app.models.db.repositories import JobRepository

EDITOR_EXPORT_KIND = "editor_export"
EDITOR_EXPORT_STAGE = "export"


class EditorDomainError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def create_export_job(
    session: Any,
    *,
    user_id: str,
    source_job_id: str,
    in_point: float,
    out_point: float,
    idempotency_key: str | None,
    request_id: str,
) -> tuple[dict[str, Any], bool]:
    """Persist one owner-scoped export job and return ``(response, replay)``."""
    source = JobRepository(session).get(source_job_id)
    if source is None or str(source.user_id) != str(user_id):
        raise EditorDomainError(404, "source job was not found")
    if source.state != TASK_STATE_COMPLETE or not str(source.result_key or "").strip():
        raise EditorDomainError(409, "source reel is not ready for export")

    payload = {
        "operation": "editor_export",
        "source_job_id": source_job_id,
        "in_point": float(in_point),
        "out_point": float(out_point),
    }
    reservation = None
    if idempotency_key is not None:
        reservation, replay = reserve_idempotency_key(
            session,
            user_id,
            idempotency_key,
            hash_request_payload(payload),
            request_id,
        )
        if replay is not None:
            return replay, True

    job = JobRepository(session).create(
        user_id=user_id,
        kind=EDITOR_EXPORT_KIND,
        params={**payload, "_correlation_id": request_id},
    )
    JobRepository(session).update_stage(job.id, EDITOR_EXPORT_STAGE, "queued")
    response = {
        "job_id": job.id,
        "state": job.state,
        "progress": job.progress,
        "correlation_id": request_id,
    }
    if reservation is not None:
        reservation.response_data = response
        session.flush()
    return response, False


TIMELINE_EXPORT_KIND = "editor_timeline_export"


def create_timeline_export_job(
    session: Any,
    *,
    user_id: str,
    source_job_id: str,
    segments: list[dict],
    overlays: list[dict],
    idempotency_key: str | None,
    request_id: str,
    music: dict | None = None,
) -> tuple[dict[str, Any], bool]:
    """Validate a timeline EDL and persist one owner-scoped export job.

    Reuses the same ownership/readiness gate as the single-trim export, then
    validates the multi-segment EDL (bounds, speeds, overlay windows, optional
    background-music track) with the pure :mod:`timeline` policy before
    enqueuing. Idempotent via the shared key.
    """
    from app.domains.editor.timeline import (
        Music,
        Overlay,
        Segment,
        Timeline,
        TimelineError,
        normalize_edl,
        validate_timeline,
    )

    source = JobRepository(session).get(source_job_id)
    if source is None or str(source.user_id) != str(user_id):
        raise EditorDomainError(404, "source job was not found")
    if source.state != TASK_STATE_COMPLETE or not str(source.result_key or "").strip():
        raise EditorDomainError(409, "source reel is not ready for export")

    timeline = Timeline(
        segments=[
            Segment(
                source_in=float(s["source_in"]),
                source_out=float(s["source_out"]),
                speed=float(s.get("speed", 1.0)),
                caption=s.get("caption"),
            )
            for s in segments
        ],
        overlays=[
            Overlay(
                text=str(o["text"]),
                start_s=float(o["start_s"]),
                end_s=float(o["end_s"]),
                position=str(o.get("position", "bottom")),
            )
            for o in overlays
        ],
        music=(
            Music(
                music_id=str(music["music_id"]),
                volume=float(music.get("volume", 1.0)),
            )
            if music
            else None
        ),
    )
    try:
        validate_timeline(timeline)
    except TimelineError as exc:
        raise EditorDomainError(422, str(exc)) from exc

    edl = normalize_edl(timeline)
    payload = {
        "operation": "editor_timeline_export",
        "source_job_id": source_job_id,
        "edl": edl,
    }
    reservation = None
    if idempotency_key is not None:
        reservation, replay = reserve_idempotency_key(
            session,
            user_id,
            idempotency_key,
            hash_request_payload(payload),
            request_id,
        )
        if replay is not None:
            return replay, True

    job = JobRepository(session).create(
        user_id=user_id,
        kind=TIMELINE_EXPORT_KIND,
        params={**payload, "_correlation_id": request_id},
    )
    JobRepository(session).update_stage(job.id, EDITOR_EXPORT_STAGE, "queued")
    response = {
        "job_id": job.id,
        "state": job.state,
        "progress": job.progress,
        "output_duration_s": edl["output_duration_s"],
        "segments": len(edl["segments"]),
        "overlays": len(edl["overlays"]),
        "correlation_id": request_id,
    }
    if reservation is not None:
        reservation.response_data = response
        session.flush()
    return response, False


def mark_enqueue_failure(job_id: str, message: str) -> None:
    """Persist a terminal dispatch failure in a fresh transaction."""
    from app.models.db.base import get_session

    with get_session() as session:
        JobRepository(session).mark_failed(job_id, "enqueue", message)


__all__ = [
    "EDITOR_EXPORT_KIND",
    "EDITOR_EXPORT_STAGE",
    "TIMELINE_EXPORT_KIND",
    "EditorDomainError",
    "create_export_job",
    "create_timeline_export_job",
    "mark_enqueue_failure",
]
