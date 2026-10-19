"""Tier-1 content keys (MV3/MV5): one random 16-byte key per paid title, encrypted at rest.

Encrypted with Fernet under ``OTT_CONTENT_KEY_SECRET`` (stretched with SHA-256,
the same construction as ``services/crypto_tokens.py``). Without the secret no
key is created or read (fail closed): a paid title then cannot be packaged.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets

from sqlalchemy.orm import Session

from .models import OttContentKey

SECRET_ENV = "OTT_CONTENT_KEY_SECRET"


class KeyUnavailable(RuntimeError):
    pass


def _fernet():
    from cryptography.fernet import Fernet

    secret = (os.getenv(SECRET_ENV) or "").strip()
    if len(secret) < 16:
        raise KeyUnavailable("content keys are not configured")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def ensure_key(session: Session, title_id: str) -> tuple[str, str]:
    """``(key_id_hex, key_hex)`` for a title, created on first use."""
    row = session.get(OttContentKey, title_id)
    fernet = _fernet()
    if row is None:
        key_hex = secrets.token_hex(16)
        row = OttContentKey(title_id=title_id, key_id_hex=secrets.token_hex(16),
                            key_enc=fernet.encrypt(key_hex.encode()).decode())
        session.add(row)
        session.flush()
        return row.key_id_hex, key_hex
    return row.key_id_hex, fernet.decrypt(row.key_enc.encode()).decode()


def read_key(session: Session, title_id: str) -> bytes | None:
    row = session.get(OttContentKey, title_id)
    if row is None:
        return None
    return bytes.fromhex(_fernet().decrypt(row.key_enc.encode()).decode())


def version(session: Session, title_id: str) -> int:
    row = session.get(OttContentKey, title_id)
    return int(row.version or 1) if row is not None else 0


def rotate_key(session: Session, title_id: str) -> int:
    """A fresh key for the title (QM1.2, P-M7); returns the new version. Old playlists stop decrypting."""
    fernet = _fernet()
    row = session.get(OttContentKey, title_id)
    key_hex = secrets.token_hex(16)
    if row is None:
        row = OttContentKey(title_id=title_id, key_id_hex=secrets.token_hex(16),
                            key_enc=fernet.encrypt(key_hex.encode()).decode(), version=1)
        session.add(row)
    else:
        row.key_id_hex = secrets.token_hex(16)
        row.key_enc = fernet.encrypt(key_hex.encode()).decode()
        row.version = int(row.version or 1) + 1
    session.flush()
    return int(row.version)


__all__ = ["KeyUnavailable", "SECRET_ENV", "ensure_key", "read_key", "rotate_key", "version"]
