"""Capture business rules: validation, lifecycle, owner-scoped queries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.domains.adstudio.fetch import FetchError, normalize_public_url
from app.domains.capture.models import (
    KIND_APP_STORE,
    KIND_NATIVE_GAME,
    KIND_PLAY_STORE,
    LEGACY_KINDS,
    STATUS_CANCELED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    CaptureJob,
)
from app.domains.capture.native import NativeTarget, NativeTargetError, parse_target
from app.domains.capture.sources import KIND_AUTO, Source, SourceError, classify
from app.domains.capture.worker import STALE_CAPTURE_S, _config_value

FORMATS: tuple[str, ...] = ("9:16", "16:9", "1:1")
DURATION_LIMITS: dict[str, tuple[int, int, int]] = {
    # kind: (min, default, max) seconds
    "website": (10, 20, 45),
    KIND_NATIVE_GAME: (10, 30, 60),
}
MAX_ACTIVE_PER_USER = 3


class CaptureError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def resolve_source(url: str, kind: str = KIND_AUTO) -> Source:
    try:
        normalized = normalize_public_url(url)
    except FetchError as exc:
        raise CaptureError(422, exc.message.replace("product URL", "URL")) from exc
    try:
        return classify(normalized, kind)
    except SourceError as exc:
        raise CaptureError(422, str(exc)) from exc


def native_enabled() -> bool:
    """Operator switch: ``[app] capture_native_game = true`` on a host with a simulator/emulator."""
    return bool(_config_value("capture_native_game", False))


def native_allowed_app_ids() -> tuple[str, ...]:
    raw = _config_value("capture_native_app_ids", []) or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return tuple(str(v).strip() for v in raw if str(v).strip())


def resolve_native(raw: dict[str, Any] | None) -> tuple[Source, NativeTarget]:
    """Validate a native game target (simulator/emulator on the capture host)."""
    if not native_enabled():
        raise CaptureError(
            422,
            "native game capture is not enabled on this server; the operator sets capture_native_game = true "
            "on a host with an iOS Simulator or Android emulator",
        )
    try:
        target = parse_target(raw, allowed_app_ids=native_allowed_app_ids())
    except NativeTargetError as exc:
        raise CaptureError(422, str(exc)) from exc
    return Source(KIND_NATIVE_GAME, target.source_url(), {}), target


def build_options(source: Source, formats: list[str], duration_s: int | None, cursor: bool,
                  native: NativeTarget | None = None) -> dict[str, Any]:
    picked = [f for f in dict.fromkeys(formats or [])]
    if not picked:
        raise CaptureError(422, "pick at least one format")
    unknown = [f for f in picked if f not in FORMATS]
    if unknown:
        raise CaptureError(422, f"unsupported format(s): {', '.join(unknown)}")
    options: dict[str, Any] = {"formats": picked, "cursor": bool(cursor)}
    if source.kind in DURATION_LIMITS:
        low, default, high = DURATION_LIMITS[source.kind]
        value = default if duration_s is None else int(duration_s)
        if not low <= value <= high:
            raise CaptureError(422, f"recording length must be between {low} and {high} seconds")
        options["duration_s"] = value
    if source.ref:
        options["ref"] = dict(source.ref)
    if native is not None:
        options["native"] = native.as_options()
        options["cursor"] = False
    return options


def sweep_stale(session: Any, user_id: str) -> None:
    """Fail captures a crashed worker left running/queued past the budget."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_CAPTURE_S)
    stale = (
        session.query(CaptureJob)
        .filter(
            CaptureJob.user_id == user_id,
            CaptureJob.status.in_((STATUS_QUEUED, STATUS_RUNNING)),
            CaptureJob.updated_at < cutoff,
        )
        .all()
    )
    for job in stale:
        job.status = STATUS_FAILED
        job.error = "the capture stopped responding; retry it"
        job.finished_at = datetime.now(timezone.utc)


def _active_count(session: Any, user_id: str) -> int:
    return (
        session.query(CaptureJob)
        .filter(CaptureJob.user_id == user_id, CaptureJob.status.in_((STATUS_QUEUED, STATUS_RUNNING)))
        .count()
    )


def create_capture(session: Any, *, user_id: str, source: Source, options: dict[str, Any]) -> CaptureJob:
    sweep_stale(session, user_id)
    if _active_count(session, user_id) >= MAX_ACTIVE_PER_USER:
        raise CaptureError(429, f"at most {MAX_ACTIVE_PER_USER} captures can run at once; wait for one to finish")
    job = CaptureJob(
        user_id=user_id, source_url=source.url, source_kind=source.kind, status=STATUS_QUEUED,
        progress=0, options=options, screenshots=[], meta={},
    )
    session.add(job)
    session.flush()
    return job


def get_owned(session: Any, user_id: str, capture_id: str) -> CaptureJob | None:
    return session.query(CaptureJob).filter(CaptureJob.id == capture_id, CaptureJob.user_id == user_id).first()


def list_owned(session: Any, user_id: str, *, limit: int, offset: int) -> tuple[list[CaptureJob], int]:
    query = session.query(CaptureJob).filter(CaptureJob.user_id == user_id)
    total = query.count()
    rows = query.order_by(CaptureJob.created_at.desc(), CaptureJob.id.desc()).offset(offset).limit(limit).all()
    return rows, total


def retry(session: Any, job: CaptureJob) -> None:
    if job.status not in (STATUS_FAILED, STATUS_CANCELED):
        raise CaptureError(409, "only failed or canceled captures can be retried")
    if job.source_kind in LEGACY_KINDS:
        raise CaptureError(409, "web game capture was removed; start a native game capture instead")
    if job.source_kind == KIND_NATIVE_GAME and not native_enabled():
        raise CaptureError(409, "native game capture is not enabled on this server")
    if _active_count(session, job.user_id) >= MAX_ACTIVE_PER_USER:
        raise CaptureError(429, f"at most {MAX_ACTIVE_PER_USER} captures can run at once; wait for one to finish")
    job.status, job.progress, job.error = STATUS_QUEUED, 0, ""
    job.output_video_key, job.screenshots, job.meta = "", [], {}
    job.started_at = job.finished_at = None


def cancel(job: CaptureJob) -> None:
    if job.status not in (STATUS_QUEUED, STATUS_RUNNING):
        raise CaptureError(409, "this capture is not running")
    job.status, job.error = STATUS_CANCELED, "canceled"
    job.finished_at = datetime.now(timezone.utc)


def is_store(kind: str) -> bool:
    return kind in (KIND_APP_STORE, KIND_PLAY_STORE)


__all__ = [
    "CaptureError",
    "DURATION_LIMITS",
    "FORMATS",
    "MAX_ACTIVE_PER_USER",
    "build_options",
    "cancel",
    "create_capture",
    "get_owned",
    "is_store",
    "list_owned",
    "native_enabled",
    "resolve_native",
    "resolve_source",
    "retry",
    "sweep_stale",
]
