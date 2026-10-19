"""Reference-image binding for the character identity lock (Wave 4).

A pure-ish delegate that binds an OWNED ``uploads/`` object to a character as a
face / body / outfit / pose / sheet reference — the IP-Adapter / LoRA
conditioning inputs that keep a recurring AI character visually identical.

Boundary rules (§5, §8):

* Ownership is validated with ``media.service.require_owned_asset`` BEFORE any
  row is persisted — only an upload the caller owns can be bound; there is no new
  upload path (uploads reuse the existing two-step presign→PUT→register flow).
* Only ``uploads/`` keys are accepted; a raw client URL / foreign key is refused.
* Returned values are immutable snapshots (plain dicts / tuples), never live ORM
  rows, so a caller can never mutate persisted state through them.

The sorted digest of a character's bound references is exposed via
:func:`reference_digest` (delegating to the pure ``consistency`` implementation)
so the identity_key rehash and this store agree on one canonical digest.
"""

from __future__ import annotations

from typing import Any

from app.domains.characters.consistency import reference_digest as _reference_digest
from app.domains.media.service import require_owned_asset
from app.models.db.character_refs import CharacterReference

# Roles a reference image can play in the identity lock.
VALID_ROLES: frozenset[str] = frozenset({"face", "body", "outfit", "pose", "sheet"})
_DEFAULT_ROLE = "sheet"


class ReferenceBindingError(Exception):
    """A boundary validation failure (bad role / non-uploads key)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _view(row: CharacterReference) -> dict[str, Any]:
    """Immutable snapshot of a bound reference (never the live ORM row)."""
    return {
        "id": row.id,
        "character_id": row.character_id,
        "user_id": row.user_id,
        "r2_key": row.r2_key,
        "role": row.role,
        "content_type": row.content_type or "",
        "width": int(row.width or 0),
        "height": int(row.height or 0),
        "embedding_key": row.embedding_key or "",
    }


def bind_reference(
    session: Any,
    *,
    user_id: str,
    character_id: str,
    r2_key: str,
    role: str = _DEFAULT_ROLE,
    content_type: str = "",
    width: int = 0,
    height: int = 0,
) -> dict[str, Any]:
    """Bind an OWNED ``uploads/`` key to ``character_id`` as a reference image.

    Validates the role + key shape, then verifies ownership via
    ``require_owned_asset`` (raises ``MediaDomainError`` when the key is not the
    caller's) BEFORE persisting the row. Returns an immutable snapshot.
    """
    normalized_role = (role or _DEFAULT_ROLE).strip().lower() or _DEFAULT_ROLE
    if normalized_role not in VALID_ROLES:
        raise ReferenceBindingError(
            400, f"role must be one of {sorted(VALID_ROLES)}"
        )
    key = (r2_key or "").strip()
    if not key.startswith("uploads/"):
        raise ReferenceBindingError(400, "only owned uploads/ keys can be bound")

    # Ownership boundary: fail closed unless the key belongs to the caller. This
    # raises MediaDomainError (403) which the controller maps to an HTTP error.
    require_owned_asset(session, user_id=user_id, key=key)

    row = CharacterReference(
        character_id=character_id,
        user_id=user_id,
        r2_key=key,
        role=normalized_role,
        content_type=(content_type or "").strip(),
        width=int(width or 0),
        height=int(height or 0),
    )
    session.add(row)
    session.flush()
    # Fold the newly-bound key into the character's canonical identity so the
    # bound sheet is the single source of truth: ``Character.reference_images``
    # (which the compiler's IdentityLock + ``find_duplicate`` dedupe read via
    # ``to_profile``) and the stored ``identity_key`` are recomputed in the SAME
    # transaction. No-op when the character row is absent (bind-before-create).
    _sync_character_identity(session, character_id)
    return _view(row)


def _sync_character_identity(session: Any, character_id: str) -> None:
    """Write the sorted bound r2 keys back onto the character + rehash identity.

    Keeps the ``character_references`` store and ``Character.reference_images``
    in agreement (they are no longer disjoint): after every bind/unbind the
    character's JSON reference column mirrors the bound sheet and
    ``identity_key`` is recomputed from the rebuilt profile so identity/dedupe/
    drift and the compiled IdentityLock all see the bound references. Import is
    lazy to avoid a domain import cycle; a missing character row is a silent
    no-op (a reference can be bound before the character is persisted in tests).
    """
    from app.domains.characters.repository import to_profile
    from app.models.db.characters import Character

    row = session.get(Character, character_id)
    if row is None:
        return
    row.reference_images = list(reference_keys(session, character_id))
    row.identity_key = to_profile(row).identity_key()
    session.flush()


def list_references(session: Any, character_id: str) -> tuple[dict[str, Any], ...]:
    """Return every reference bound to ``character_id`` (oldest first), immutably."""
    rows = (
        session.query(CharacterReference)
        .filter(CharacterReference.character_id == character_id)
        .order_by(CharacterReference.created_at.asc())
        .all()
    )
    return tuple(_view(r) for r in rows)


def reference_keys(session: Any, character_id: str) -> tuple[str, ...]:
    """Return the sorted, de-duplicated r2 keys bound to a character."""
    rows = list_references(session, character_id)
    return tuple(sorted({r["r2_key"] for r in rows if r["r2_key"]}))


def reference_digest(refs: Any) -> str:
    """Stable sha256 of sorted reference r2 keys (the identity_key fold input).

    Accepts either an iterable of r2-key strings or an iterable of reference view
    dicts (as returned by :func:`list_references`). Delegates to the pure
    ``consistency.reference_digest`` so the store and the identity_key rehash
    share one canonical digest.
    """
    keys: list[str] = []
    for item in refs or ():
        if isinstance(item, dict):
            value = item.get("r2_key", "")
        else:
            value = item
        if value:
            keys.append(str(value))
    return _reference_digest(tuple(keys))
