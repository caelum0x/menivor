"""BYOK service: store (encrypted), list, revoke, and resolve provider keys.

Encrypts the raw secret at rest with the same Fernet scheme as the OAuth token
store (``app.services.crypto_tokens``); the plaintext is never persisted or
returned. :meth:`resolve_secret` is the routing seam — it decrypts the
highest-priority active key for a user+provider and audits the use. Business
failures raise :class:`BYOKError` for the thin router to map.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.byok.repository import BYOKRepository
from app.domains.byok.schemas import key_view, mask_secret
from app.models.db.marketplace import ProviderKey


class BYOKError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _encrypt(secret: str) -> str:
    from app.services import crypto_tokens

    return crypto_tokens.encrypt(secret)


def _decrypt(blob: str) -> str:
    from app.services import crypto_tokens

    return crypto_tokens.decrypt(blob)


class BYOKService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = BYOKRepository(session)

    def add_key(
        self,
        user_id: str,
        *,
        provider_key: str,
        secret: str,
        label: str = "",
        priority: int = 0,
    ) -> dict:
        """Store a customer's provider key encrypted at rest; return a safe view."""
        provider_key = (provider_key or "").strip()
        secret = str(secret or "").strip()
        if not provider_key:
            raise BYOKError(400, "provider_key is required")
        if not secret:
            raise BYOKError(400, "a non-empty secret is required")
        try:
            ciphertext = _encrypt(secret)
        except Exception as exc:  # noqa: BLE001 - never persist an unencrypted key
            raise BYOKError(
                503, "key encryption is not configured; cannot store a provider key"
            ) from exc
        row = ProviderKey(
            user_id=user_id,
            provider_key=provider_key,
            label=label or "",
            key_prefix=mask_secret(secret),
            encrypted_secret=ciphertext,
            priority=int(priority or 0),
            status="active",
        )
        self._repo.add(row)
        return key_view(row)

    def list_keys(self, user_id: str) -> list[dict]:
        return [key_view(k) for k in self._repo.list_for_user(user_id)]

    def revoke_key(self, user_id: str, key_id: str) -> dict:
        row = self._repo.get_owned(key_id, user_id)
        if row is None:
            raise BYOKError(404, "provider key not found")
        self._repo.revoke(row)
        return key_view(row)

    def resolve_secret(self, user_id: str, provider_key: str) -> str | None:
        """Decrypt the active key for routing + audit the use; None if none.

        Called at generation time when BYOK routing is consented. A decryption
        failure returns None (the routing layer falls back to the platform key)
        rather than raising, so a corrupted stored key never breaks a job.
        """
        row = self._repo.highest_priority_active(user_id, (provider_key or "").strip())
        if row is None:
            return None
        try:
            secret = _decrypt(row.encrypted_secret)
        except Exception:  # noqa: BLE001 - corrupted/unreadable key -> platform key
            return None
        self._repo.touch_use(row)
        return secret
