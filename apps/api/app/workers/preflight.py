"""Render preflight (MG8): refuse before the disk fills, never after.

A render writes intermediate audio, frames and the final MP4 under the
storage directory. When free space there is below
``MENIVOR_MIN_FREE_DISK_GB`` (default 10 GB) a new render is refused with an
honest 503 before anything is debited, and the owner gets one alert (ntfy
and/or email, both free) at most every :data:`ALERT_EVERY_S` seconds per
process.

Callers (hand-off to M1.3, owner of ``workers/pipeline.py`` and admission):

* API admission, BEFORE the debit: ``preflight.require_capacity()`` and map
  :class:`PreflightError` to ``HttpException(503, err.message)``.
* Worker, before the first render stage: ``preflight.check()``; when not ``ok``
  fail the job with ``result.message`` so the existing failed-reel refund
  returns the credit.

``statvfs`` is injectable for tests. Never raises except
:class:`PreflightError` from :func:`require_capacity`.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

from loguru import logger

DEFAULT_MIN_FREE_GB = 10.0
ALERT_EVERY_S = 1800
_GB = 1024**3
BUSY_MESSAGE = (
    "Menivor is short on render space right now, so this reel was not started and "
    "nothing was charged. Try again in a few minutes."
)

_alert_lock = threading.Lock()
_last_alert_at = 0.0


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    free_gb: float
    min_free_gb: float
    path: str
    message: str = ""


class PreflightError(RuntimeError):
    """Raised by :func:`require_capacity`; map to HTTP 503 with no debit."""

    status = 503

    def __init__(self, result: PreflightResult) -> None:
        super().__init__(result.message)
        self.result = result
        self.message = result.message


def min_free_gb() -> float:
    raw = (os.environ.get("MENIVOR_MIN_FREE_DISK_GB") or "").strip()
    try:
        return max(0.0, float(raw)) if raw else DEFAULT_MIN_FREE_GB
    except ValueError:
        return DEFAULT_MIN_FREE_GB


def storage_path() -> str:
    """The directory renders write to (falls back to the working directory)."""
    raw = (os.environ.get("MENIVOR_RENDER_DIR") or "").strip()
    if raw:
        return raw
    try:
        from app.utils import utils

        return str(utils.storage_dir())
    except Exception:  # noqa: BLE001 - any readable path works for statvfs
        return os.getcwd()


def _free_bytes(path: str, statvfs: Callable[[str], os.statvfs_result]) -> int:
    probe = path
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe.rstrip(os.sep))
        if parent == probe:
            break
        probe = parent
    stats = statvfs(probe or os.sep)
    return int(stats.f_bavail) * int(stats.f_frsize)


def _alert_owner(text: str, *, now: float | None = None) -> bool:
    """One alert per :data:`ALERT_EVERY_S` per process (free channels only)."""
    global _last_alert_at
    moment = time.time() if now is None else now
    with _alert_lock:
        if moment - _last_alert_at < ALERT_EVERY_S:
            return False
        _last_alert_at = moment
    logger.error(f"owner alert: {text}")
    topic = (os.environ.get("MENIVOR_OWNER_NTFY_URL") or "").strip()
    if topic:
        try:
            import requests

            requests.post(topic, data=text.encode("utf-8"), timeout=5,
                          headers={"Title": "Menivor render disk", "Priority": "high"})
        except Exception as exc:  # noqa: BLE001 - alerting is best effort
            logger.warning(f"preflight ntfy alert failed: {type(exc).__name__}")
    to = (os.environ.get("MENIVOR_OWNER_ALERT_EMAIL") or "").strip()
    if to:
        try:
            from app.services import mailer

            mailer.send_email(to=to, subject="Menivor render disk low", text=text)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"preflight email alert failed: {type(exc).__name__}")
    return True


def check(
    path: str | None = None,
    *,
    statvfs: Callable[[str], os.statvfs_result] = os.statvfs,
) -> PreflightResult:
    """Free space at the render directory against the floor. Never raises."""
    target = path or storage_path()
    floor = min_free_gb()
    try:
        free = _free_bytes(target, statvfs) / _GB
    except Exception as exc:  # noqa: BLE001 - cannot measure: do not block renders
        logger.warning(f"preflight: statvfs failed for {target}: {exc}")
        return PreflightResult(ok=True, free_gb=-1.0, min_free_gb=floor, path=target)
    if free >= floor:
        return PreflightResult(ok=True, free_gb=round(free, 2), min_free_gb=floor, path=target)
    result = PreflightResult(
        ok=False, free_gb=round(free, 2), min_free_gb=floor, path=target, message=BUSY_MESSAGE
    )
    _alert_owner(
        f"Render disk low on {os.uname().nodename}: {result.free_gb} GB free at {target} "
        f"(floor {floor} GB). New renders are refused with 503 until space is freed."
    )
    return result


def require_capacity(
    path: str | None = None,
    *,
    statvfs: Callable[[str], os.statvfs_result] = os.statvfs,
) -> PreflightResult:
    """:func:`check`, raising :class:`PreflightError` (503, no debit) when short."""
    result = check(path, statvfs=statvfs)
    if not result.ok:
        raise PreflightError(result)
    return result


def _reset_alert_clock() -> None:
    """Test helper."""
    global _last_alert_at
    with _alert_lock:
        _last_alert_at = 0.0


__all__ = [
    "BUSY_MESSAGE",
    "DEFAULT_MIN_FREE_GB",
    "PreflightError",
    "PreflightResult",
    "check",
    "min_free_gb",
    "require_capacity",
    "storage_path",
]
