"""Resumable multipart uploads straight to R2 (MV2). The API never carries the video bytes.

The browser asks for a multipart upload, then presigned part URLs (any time,
so an interrupted upload resumes from the parts it already sent), PUTs each
part to R2 and completes. Only the creator's own upload id is accepted.
"""

from __future__ import annotations

import os
import re
from typing import Any, Protocol

PART_BYTES = 16 * 1024 * 1024
MAX_BYTES = 20 * 1024 ** 3
MAX_PARTS = 10000
PART_URL_TTL_S = 3600
BUCKET_ENV = "R2_OTT_BUCKET"
DEFAULT_BUCKET = "menivor-ott"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
ALLOWED_TYPES = ("video/mp4", "video/quicktime", "video/webm", "video/x-matroska", "audio/mpeg", "audio/mp4")


class UploadError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class Storage(Protocol):
    def create(self, key: str, content_type: str) -> str: ...
    def part_url(self, key: str, upload_id: str, part: int) -> str: ...
    def complete(self, key: str, upload_id: str, parts: list[dict[str, Any]]) -> None: ...
    def abort(self, key: str, upload_id: str) -> None: ...
    def presign_get(self, key: str, ttl_s: int) -> str: ...
    def read(self, key: str) -> bytes: ...
    def presign_put(self, key: str, content_type: str, ttl_s: int) -> str: ...


class R2Storage:
    """Multipart on the OTT bucket through the existing R2 client's boto3 handle."""

    def __init__(self) -> None:
        from app.platform.storage.r2 import R2Client

        self._client = R2Client(bucket=os.getenv(BUCKET_ENV) or DEFAULT_BUCKET)
        self._s3, self._bucket = self._client._s3, self._client._bucket

    def create(self, key: str, content_type: str) -> str:
        return self._s3.create_multipart_upload(Bucket=self._bucket, Key=key, ContentType=content_type)["UploadId"]

    def part_url(self, key: str, upload_id: str, part: int) -> str:
        return self._s3.generate_presigned_url("upload_part", Params={
            "Bucket": self._bucket, "Key": key, "UploadId": upload_id, "PartNumber": part}, ExpiresIn=PART_URL_TTL_S)

    def complete(self, key: str, upload_id: str, parts: list[dict[str, Any]]) -> None:
        self._s3.complete_multipart_upload(Bucket=self._bucket, Key=key, UploadId=upload_id,
                                           MultipartUpload={"Parts": parts})

    def abort(self, key: str, upload_id: str) -> None:
        self._s3.abort_multipart_upload(Bucket=self._bucket, Key=key, UploadId=upload_id)

    def size(self, key: str) -> int:
        """The stored object's real length (the quota never trusts the size the client reported)."""
        return int(self._s3.head_object(Bucket=self._bucket, Key=key)["ContentLength"])

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self._bucket, Key=key)

    def presign_get(self, key: str, ttl_s: int) -> str:
        return self._s3.generate_presigned_url("get_object", Params={"Bucket": self._bucket, "Key": key},
                                               ExpiresIn=ttl_s)

    def read(self, key: str) -> bytes:
        return self._s3.get_object(Bucket=self._bucket, Key=key)["Body"].read()

    def presign_put(self, key: str, content_type: str, ttl_s: int) -> str:
        return self._s3.generate_presigned_url("put_object", Params={
            "Bucket": self._bucket, "Key": key, "ContentType": content_type}, ExpiresIn=ttl_s)


def upload_key(user_id: str, upload_ref: str, filename: str) -> str:
    name = _SAFE.sub("-", filename or "upload.mp4").strip("-")[:80] or "upload.mp4"
    return f"ott-uploads/{user_id}/{upload_ref}/{name}"


def check_start(size_bytes: int, content_type: str) -> int:
    if content_type not in ALLOWED_TYPES:
        raise UploadError(400, "type", "upload a video or audio file")
    if size_bytes <= 0 or size_bytes > MAX_BYTES:
        raise UploadError(400, "size", "files up to 20 GB")
    return -(-int(size_bytes) // PART_BYTES)


def owns(key: str, user_id: str) -> bool:
    return key.startswith(f"ott-uploads/{user_id}/")


# --------------------------------------------------------------------------- #
# Per-user quota (Wave Q QM1.2, P-M6): applies whatever the plans flag says
# --------------------------------------------------------------------------- #
GB = 1024 ** 3
#: Free accounts: 2 GB of uploads stored and 60 encode minutes a month.
FREE_QUOTA_GB = 2.0
FREE_QUOTA_ENCODE_MIN = 60.0
UPGRADE_URL = "/pricing"


class QuotaExceeded(UploadError):
    def __init__(self, message: str) -> None:
        super().__init__(402, "upload_quota", message)
        self.upgrade_url = UPGRADE_URL


def quota_for(session: Any, user_id: str, *, paid: bool) -> tuple[float, float]:
    """(GB stored, encode minutes a month) for this creator: the plan caps when paid, else the free quota."""
    if not paid:
        return FREE_QUOTA_GB, FREE_QUOTA_ENCODE_MIN
    from app.services.billing import ott_plans

    caps = ott_plans.caps_for(session, user_id)
    if caps == ott_plans.PLAN_CAPS["free"]:  # paid through another path (packs): the smallest paid plan
        caps = ott_plans.PLAN_CAPS["creator"]
    return float(caps.gb_stored), float(caps.encode_minutes)


def usage(session: Any, user_id: str, *, now: Any = None) -> tuple[float, float]:
    """(GB of uploads stored, encode minutes this month) so far."""
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from app.domains.ott.models import OttTitle
    from app.domains.ott.upload_check import OttUploadCheck

    from .models import OttEncodeJob

    moment = now or datetime.now(timezone.utc)
    stored = session.execute(select(func.coalesce(func.sum(OttUploadCheck.size_bytes), 0))
                             .join(OttTitle, OttTitle.id == OttUploadCheck.title_id)
                             .where(OttUploadCheck.user_id == str(user_id))).scalar() or 0
    month = datetime(moment.year, moment.month, 1, tzinfo=timezone.utc)
    seconds = session.execute(select(func.coalesce(func.sum(OttEncodeJob.source_seconds), 0.0))
                              .where(OttEncodeJob.user_id == str(user_id), OttEncodeJob.created_at >= month)
                              ).scalar() or 0.0
    return float(stored) / GB, float(seconds) / 60.0


def lock_quota(session: Any, user_id: str) -> None:
    """Serialise quota check + record per user, so parallel completes cannot each pass the same headroom.

    A transaction-scoped Postgres advisory lock (released at commit or rollback). Other
    databases (SQLite in tests) run one writer at a time already.
    """
    from sqlalchemy import text

    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"ott-upload-quota:{user_id}"})


def measured_size(store: Any, key: str, fallback: int) -> int:
    """The real stored size when the store can tell it, else ``fallback`` (test doubles)."""
    size = getattr(store, "size", None)
    return int(size(key)) if callable(size) else int(fallback)


def require_quota(session: Any, user_id: str, *, paid: bool, add_bytes: int = 0, add_seconds: float = 0.0) -> None:
    """Raise :class:`QuotaExceeded` (402, with the upgrade path) when this upload would pass the quota."""
    cap_gb, cap_min = quota_for(session, user_id, paid=paid)
    used_gb, used_min = usage(session, user_id)
    if used_gb + add_bytes / GB > cap_gb + 1e-9:
        raise QuotaExceeded(f"This upload would pass your {cap_gb:g} GB of video storage. "
                            "Upgrade your plan to upload more.")
    if used_min + float(add_seconds or 0) / 60.0 > cap_min + 1e-9:
        raise QuotaExceeded(f"This upload would pass your {cap_min:g} encoding minutes this month. "
                            "Upgrade your plan to keep going.")


__all__ = ["ALLOWED_TYPES", "FREE_QUOTA_ENCODE_MIN", "FREE_QUOTA_GB", "PART_BYTES", "QuotaExceeded", "R2Storage",
           "Storage", "UploadError", "check_start", "lock_quota", "measured_size", "owns", "quota_for", "require_quota", "upload_key", "usage"]
