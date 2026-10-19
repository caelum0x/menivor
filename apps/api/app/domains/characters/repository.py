"""Character repository — persist + reuse identity-locked characters.

Bridges the pure ``consistency.CharacterProfile`` to the ``characters`` row so a
creator's character is reusable across reels/episodes/projects. Saving computes
the ``identity_key`` from the profile; ``to_profile`` rebuilds the pure profile
for the shot-prompt builder.
"""

from __future__ import annotations

from typing import Any

from app.domains.characters.consistency import CharacterProfile
from app.models.db.characters import Character


def to_profile(row: Character) -> CharacterProfile:
    return CharacterProfile(
        character_id=row.id,
        name=row.name,
        descriptors=tuple(row.descriptors or ()),
        reference_images=tuple(row.reference_images or ()),
        style=row.style,
        lora_ref=row.lora_ref,
        negative=tuple(row.negative or ()),
    )


class CharacterRepository:
    """CRUD for reusable characters."""

    def __init__(self, session: Any) -> None:
        self._s = session

    def create(self, *, user_id: str, profile: CharacterProfile) -> Character:
        row = Character(
            user_id=user_id,
            name=profile.name,
            descriptors=list(profile.descriptors),
            reference_images=list(profile.reference_images),
            negative=list(profile.negative),
            style=profile.style,
            lora_ref=profile.lora_ref,
            identity_key=profile.identity_key(),
        )
        self._s.add(row)
        self._s.flush()
        return row

    def get(self, character_id: str) -> Character | None:
        return self._s.get(Character, character_id)

    def get_owned(self, character_id: str, user_id: str) -> Character | None:
        row = self.get(character_id)
        return row if row is not None and str(row.user_id) == str(user_id) else None

    def list_for_user(self, user_id: str, *, limit: int = 100) -> list[Character]:
        return (
            self._s.query(Character)
            .filter(Character.user_id == user_id)
            .order_by(Character.created_at.desc())
            .limit(limit)
            .all()
        )

    def find_duplicate(self, user_id: str, profile: CharacterProfile) -> Character | None:
        """Return an existing character with the same locked identity (dedupe)."""
        return (
            self._s.query(Character)
            .filter(Character.user_id == user_id, Character.identity_key == profile.identity_key())
            .first()
        )

    def delete_owned(self, character_id: str, user_id: str) -> bool:
        """Delete a character iff it belongs to ``user_id``. Returns True if removed."""
        row = self.get_owned(character_id, user_id)
        if row is None:
            return False
        self._s.delete(row)
        self._s.flush()
        return True

    def rename_owned(self, character_id: str, user_id: str, *, name: str) -> Character | None:
        """Rename an owned character (identity_key is unchanged — same lock)."""
        row = self.get_owned(character_id, user_id)
        if row is None:
            return None
        row.name = name
        self._s.flush()
        return row

    def set_lora_ref(self, character_id: str, lora_ref: str) -> Character | None:
        """Write back the trained LoRA weight key onto a character.

        Called by ``training_service`` when a ``character_lora`` job completes so
        every FUTURE shot of this character auto-injects the trained weights
        (``IdentityLock.lora_ref``). Setting the LoRA does NOT change the identity
        lock's reference-image digest, but it does re-key the identity (lora_ref
        is part of ``identity_key``); the stored ``identity_key`` is recomputed
        from the rebuilt profile so ``find_duplicate`` stays consistent. A blank
        value is coerced to ``""`` so the column is never written NULL.
        """
        row = self._s.get(Character, character_id)
        if row is None:
            return None
        row.lora_ref = lora_ref or ""
        row.identity_key = to_profile(row).identity_key()
        self._s.flush()
        return row
