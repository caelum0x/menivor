"""Persistence queries owned by the media domain."""

from typing import Any

from app.models.db.models import Asset
from app.models.db.repositories import AssetRepository


class MediaRepository:
    def __init__(self, session: Any) -> None:
        self._session = session

    def reserve_owned_upload(
        self,
        user_id: str,
        key: str,
        *,
        content_type: str,
        size: int,
        filename: str = "",
    ) -> Any:
        """Persist ownership at presign time, before the object can be uploaded."""
        existing = self._session.query(Asset).filter(Asset.r2_key == key).first()
        if existing is not None:
            return existing if str(existing.user_id) == str(user_id) else None
        return AssetRepository(self._session).create(
            user_id=user_id,
            kind="upload_pending",
            r2_key=key,
            content_type=content_type,
            size_bytes=size,
            meta={
                "upload_state": "presigned",
                **({"filename": filename[:255]} if filename else {}),
            },
        )

    def register_owned_upload(self, user_id: str, key: str, kind: str) -> Any | None:
        existing = self._session.query(Asset).filter(Asset.r2_key == key).first()
        if existing is None or str(existing.user_id) != str(user_id):
            return None
        existing.kind = kind
        existing.meta = {**dict(existing.meta or {}), "upload_state": "registered"}
        self._session.flush()
        return existing

    def find_owned_asset(self, user_id: str, key: str) -> Any | None:
        return (
            self._session.query(Asset)
            .filter(Asset.r2_key == key, Asset.user_id == user_id)
            .first()
        )

    def list_owned_uploads(
        self,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        kind: str | None = None,
        include_pending: bool = False,
    ) -> tuple[list[Any], int]:
        """The caller's ``uploads/`` assets, newest first, plus the total count."""
        query = self._session.query(Asset).filter(
            Asset.user_id == user_id,
            Asset.r2_key.like("uploads/%"),
        )
        if not include_pending:
            query = query.filter(Asset.kind != "upload_pending")
        if kind:
            query = query.filter(Asset.kind == kind)
        total = int(query.count())
        rows = (
            query.order_by(Asset.created_at.desc(), Asset.id.desc())
            .offset(max(0, int(offset)))
            .limit(max(1, int(limit)))
            .all()
        )
        return rows, total

    def get_owned_upload(self, user_id: str, asset_id: str) -> Any | None:
        asset = self._session.get(Asset, asset_id)
        if (
            asset is None
            or str(asset.user_id) != str(user_id)
            or not str(asset.r2_key or "").startswith("uploads/")
        ):
            return None
        return asset

    def delete(self, asset: Any) -> None:
        self._session.delete(asset)
        self._session.flush()
