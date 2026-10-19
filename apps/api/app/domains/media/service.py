"""Media upload transactions independent of HTTP and reel orchestration."""

from __future__ import annotations

import os
from typing import Any

from app.domains.media.repository import MediaRepository
from app.platform.storage.r2 import get_r2_client


class MediaDomainError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def create_upload_intent(
    session: Any,
    *,
    user_id: str,
    filename: str,
    content_type: str,
    size: int,
) -> dict[str, Any]:
    try:
        result = get_r2_client().presign_upload(filename, content_type, size)
    except Exception as exc:  # noqa: BLE001 - normalized at the domain boundary
        raise MediaDomainError(502, "object storage is unavailable") from exc
    asset = MediaRepository(session).reserve_owned_upload(
        user_id,
        result.key,
        content_type=content_type,
        size=size,
        filename=os.path.basename(filename or ""),
    )
    if asset is None:
        raise MediaDomainError(409, "upload key collision")
    return {
        "upload_url": result.put_url,
        "get_url": result.get_url,
        "key": result.key,
        "headers": result.headers,
    }


def register_upload(
    session: Any,
    *,
    user_id: str,
    key: str,
    kind: str,
) -> dict[str, str]:
    normalized_key = (key or "").strip()
    if not normalized_key.startswith("uploads/"):
        raise MediaDomainError(400, "only uploads/ keys can be registered")
    normalized_kind = (kind or "image").strip() or "image"
    asset = MediaRepository(session).register_owned_upload(
        user_id,
        normalized_key,
        normalized_kind,
    )
    if asset is None:
        # Unknown and foreign keys intentionally share one response so object
        # existence is not disclosed and ownership cannot be claimed after the
        # presign transaction.
        raise MediaDomainError(403, "upload intent does not belong to the caller")
    return {
        "asset_id": str(asset.id),
        "key": normalized_key,
        "kind": normalized_kind,
    }


def require_owned_asset(session: Any, *, user_id: str, key: str) -> None:
    """Fail closed unless ``key`` belongs to the authenticated principal."""
    if MediaRepository(session).find_owned_asset(user_id, key) is None:
        raise MediaDomainError(403, "media key does not belong to the caller")


def _asset_view(asset: Any, r2: Any) -> dict[str, Any]:
    key = str(asset.r2_key or "")
    meta = dict(asset.meta or {})
    filename = str(meta.get("filename") or key.rsplit("/", 1)[-1])
    view: dict[str, Any] = {
        "id": str(asset.id),
        "asset_id": str(asset.id),
        "key": key,
        "kind": str(asset.kind or ""),
        "state": "pending" if asset.kind == "upload_pending" else "ready",
        "content_type": str(asset.content_type or ""),
        "size_bytes": int(asset.size_bytes or 0),
        "duration_s": float(asset.duration_s or 0.0),
        "filename": filename,
        "job_id": asset.job_id or None,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "url": None,
        "download_url": None,
    }
    if r2 is not None and key:
        try:
            view["url"] = r2.presign_get(key, expires=3600)
            view["download_url"] = r2.presign_get(key, expires=3600, download_name=filename)
        except Exception:  # noqa: BLE001 - a list never fails on one presign
            pass
    return view


def list_uploads(
    session: Any,
    *,
    user_id: str,
    limit: int,
    offset: int,
    kind: str | None = None,
    include_pending: bool = False,
) -> dict[str, Any]:
    rows, total = MediaRepository(session).list_owned_uploads(
        user_id, limit=limit, offset=offset, kind=kind, include_pending=include_pending,
    )
    try:
        r2 = get_r2_client()
    except Exception:  # noqa: BLE001 - listing works without signing (urls None)
        r2 = None
    items = [_asset_view(asset, r2) for asset in rows]
    return {
        "uploads": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
        "storage_available": r2 is not None,
    }


def delete_upload(session: Any, *, user_id: str, asset_id: str) -> str:
    """Delete the caller's upload row; returns its key for storage cleanup."""
    repo = MediaRepository(session)
    asset = repo.get_owned_upload(user_id, asset_id)
    if asset is None:
        raise MediaDomainError(404, "upload not found")
    key = str(asset.r2_key or "")
    repo.delete(asset)
    return key


def delete_stored_object(key: str) -> bool:
    """Best-effort removal of an object from R2 (never raises)."""
    if not key:
        return False
    try:
        return bool(get_r2_client().delete_object(key))
    except Exception:  # noqa: BLE001 - row is already gone; storage is best-effort
        return False
