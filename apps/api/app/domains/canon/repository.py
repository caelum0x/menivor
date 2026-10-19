"""Canon repository — append-only versioning with a never-stale content hash.

Mirrors ``CharacterRepository`` discipline: every write recomputes the content
hash IN-TRANSACTION from the values being stored, so a persisted
``current_canon_hash`` / ``canon_versions.canon_hash`` is never stale relative to
its own locked values. Locking a new version is APPEND-ONLY — the prior
snapshot (old hash + old values) is retained untouched — and re-locking
identical values is a dedupe no-op (like ``CharacterRepository.find_duplicate``).
All hash lookups are O(index).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func

from app.domains.canon.canon_hash import CanonValues, canon_hash
from app.models.db.canon import Canon, CanonVersion


class CanonRepository:
    """CRUD + immutable versioning for canons."""

    def __init__(self, session: Any) -> None:
        self._s = session

    # -- writes -------------------------------------------------------------- #

    def create_canon(
        self, *, user_id: str, name: str, values: CanonValues, character_id: str | None = None
    ) -> Canon:
        """Insert the header + the first immutable version (v1) in one flush."""
        content_hash = canon_hash(values)
        canon = Canon(
            user_id=user_id,
            name=name,
            character_id=character_id,
            current_canon_hash=content_hash,
            current_version=1,
        )
        self._s.add(canon)
        self._s.flush()  # obtain canon.id
        self._s.add(self._new_version(canon.id, 1, content_hash, values))
        self._s.flush()
        return canon

    def lock_new_version(self, canon_id: str, values: CanonValues) -> CanonVersion | None:
        """Lock a NEW immutable version from ``values``; retain all prior rows.

        Returns ``None`` if the canon is missing. If the new hash equals the
        current hash it is a dedupe no-op: no row is inserted and the existing
        current version row is returned.
        """
        canon = self._s.get(Canon, canon_id)
        if canon is None:
            return None
        content_hash = canon_hash(values)
        if content_hash == canon.current_canon_hash:
            return self.get_version(canon_id, canon.current_version)  # dedupe no-op

        next_version = self._max_version(canon_id) + 1
        row = self._new_version(canon_id, next_version, content_hash, values)
        self._s.add(row)
        # Move the header pointer forward; old canon_versions rows are untouched.
        canon.current_canon_hash = content_hash
        canon.current_version = next_version
        self._s.flush()
        return row

    @staticmethod
    def _new_version(
        canon_id: str, version: int, content_hash: str, values: CanonValues
    ) -> CanonVersion:
        return CanonVersion(
            canon_id=canon_id,
            version=version,
            canon_hash=content_hash,
            values=values.normalized_dict(),
            character_identity_key=(values.character_identity_key or None),
        )

    def _max_version(self, canon_id: str) -> int:
        return (
            self._s.query(func.max(CanonVersion.version))
            .filter(CanonVersion.canon_id == canon_id)
            .scalar()
            or 0
        )

    # -- reads --------------------------------------------------------------- #

    def get(self, canon_id: str) -> Canon | None:
        return self._s.get(Canon, canon_id)

    def get_owned(self, canon_id: str, user_id: str) -> Canon | None:
        row = self._s.get(Canon, canon_id)
        return row if row is not None and str(row.user_id) == str(user_id) else None

    def list_for_user(self, user_id: str, *, limit: int = 100) -> list[Canon]:
        return (
            self._s.query(Canon)
            .filter(Canon.user_id == user_id)
            .order_by(Canon.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_version(self, canon_id: str, version: int) -> CanonVersion | None:
        return (
            self._s.query(CanonVersion)
            .filter(CanonVersion.canon_id == canon_id, CanonVersion.version == version)
            .first()
        )

    def get_version_by_hash(self, canon_id: str, content_hash: str) -> CanonVersion | None:
        """Resolve a version by content hash WITHIN a canon (O(index))."""
        return (
            self._s.query(CanonVersion)
            .filter(
                CanonVersion.canon_id == canon_id,
                CanonVersion.canon_hash == content_hash,
            )
            .first()
        )

    def list_versions(self, canon_id: str) -> list[CanonVersion]:
        return (
            self._s.query(CanonVersion)
            .filter(CanonVersion.canon_id == canon_id)
            .order_by(CanonVersion.version.asc())
            .all()
        )

    def find_by_hash(self, content_hash: str) -> Canon | None:
        """Return the canon whose ACTIVE version has this hash (O(index))."""
        return (
            self._s.query(Canon)
            .filter(Canon.current_canon_hash == content_hash)
            .first()
        )
