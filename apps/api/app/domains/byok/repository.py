"""BYOK persistence: owner-scoped provider-key CRUD + audit touches.

Pure query/persistence over ``provider_keys``. Every read is owner-scoped so a
caller can never see or use another user's key. The raw secret column is loaded
only by :meth:`highest_priority_active` for decryption at routing time.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db.marketplace import ProviderKey

STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"


class BYOKRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, key: ProviderKey) -> ProviderKey:
        self._session.add(key)
        self._session.flush()
        return key

    def get_owned(self, key_id: str, user_id: str) -> ProviderKey | None:
        """Load a key by id only when it belongs to ``user_id`` (else None)."""
        row = self._session.get(ProviderKey, key_id)
        if row is None or row.user_id != user_id:
            return None
        return row

    def list_for_user(
        self, user_id: str, *, include_revoked: bool = True
    ) -> list[ProviderKey]:
        stmt = select(ProviderKey).where(ProviderKey.user_id == user_id)
        if not include_revoked:
            stmt = stmt.where(ProviderKey.status == STATUS_ACTIVE)
        stmt = stmt.order_by(
            ProviderKey.provider_key,
            ProviderKey.priority.desc(),
            ProviderKey.created_at.desc(),
        )
        return list(self._session.execute(stmt).scalars().all())

    def highest_priority_active(
        self, user_id: str, provider_key: str
    ) -> ProviderKey | None:
        """The active key for a user+provider with the highest priority."""
        stmt = (
            select(ProviderKey)
            .where(
                ProviderKey.user_id == user_id,
                ProviderKey.provider_key == provider_key,
                ProviderKey.status == STATUS_ACTIVE,
            )
            .order_by(ProviderKey.priority.desc(), ProviderKey.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def revoke(self, key: ProviderKey) -> ProviderKey:
        key.status = STATUS_REVOKED
        key.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return key

    def touch_use(self, key: ProviderKey) -> None:
        """Audit one use: bump the counter + stamp last_used_at."""
        key.use_count = int(key.use_count or 0) + 1
        key.last_used_at = datetime.now(timezone.utc)
        self._session.flush()
