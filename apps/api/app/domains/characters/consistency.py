"""Character / style lock — the consistency moat (Soul-ID-like).

A recurring AI character must look the same across every shot, episode, and
project. This core turns a :class:`CharacterProfile` (reference images + locked
visual descriptors + a deterministic identity seed) into (a) a stable per-shot
generation seed and (b) a consistency-injected prompt, so any routed image/video
model reproduces the same identity.

Pure + deterministic: the identity seed is content-addressed from the locked
descriptors, so the same character yields the same seed everywhere (across
processes and machines) without a shared RNG.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import NamedTuple

_SEED_SPACE = 2**31  # positive 31-bit seed, safe for most samplers

# Hash-version prefix stamped on an identity_key that folds the reference-image
# sheet into the lock (Wave 4). A character with NO reference images keeps the
# original (unprefixed) v1 hash byte-for-byte, so existing rows + the
# find_duplicate / identity_key index are never orphaned by this change.
IDENTITY_KEY_V2_PREFIX = "v2|"


def reference_digest(reference_images: tuple[str, ...] | list[str]) -> str:
    """Stable, order-independent sha256 of a character's reference r2 keys.

    Empty input yields ``""`` (so an image-less character stays on the v1 key).
    Blank/duplicate keys are ignored; the surviving keys are sorted before
    hashing so the digest is independent of insertion order.
    """
    keys = sorted({str(k).strip() for k in (reference_images or ()) if str(k).strip()})
    if not keys:
        return ""
    return hashlib.sha256("|".join(keys).encode("utf-8")).hexdigest()


def _identity_hex_body(identity_key: str) -> str:
    """Return the pure-hex body of an identity key, stripping any ``vN|`` prefix.

    ``base_seed`` slices the first hex bytes of the key; a version prefix (e.g.
    ``"v2|"``) is not valid hex, so it must be removed before the ``int(.., 16)``.
    """
    key = identity_key or ""
    if "|" in key:
        return key.rsplit("|", 1)[-1]
    return key


@dataclass(frozen=True)
class CharacterProfile:
    """A locked character identity reused across shots/episodes/projects."""

    character_id: str
    name: str
    descriptors: tuple[str, ...] = ()     # locked visual tokens (hair, wardrobe, palette…)
    reference_images: tuple[str, ...] = ()  # R2 keys of the character sheet
    style: str = ""                        # global style token (e.g. "3D pixar")
    lora_ref: str = ""                     # optional trained Wan/LoRA weight ref
    negative: tuple[str, ...] = ()         # things to keep OUT (identity drift)

    def identity_key(self) -> str:
        """Stable content hash of the locked identity (order-independent).

        The base payload (id/name/descriptors/style/lora) is unchanged. When the
        character carries reference images, their digest is folded in behind the
        ``v2|`` version prefix so the sheet participates in dedupe/drift; an
        image-less character returns the original v1 hash unchanged.
        """
        payload = "|".join([
            self.character_id,
            self.name,
            ",".join(sorted(self.descriptors)),
            self.style,
            self.lora_ref,
        ])
        base = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        digest = reference_digest(self.reference_images)
        if not digest:
            return base  # v1 — byte-identical to the pre-Wave-4 key
        folded = hashlib.sha256(f"{base}|refs:{digest}".encode("utf-8")).hexdigest()
        return f"{IDENTITY_KEY_V2_PREFIX}{folded}"

    def base_seed(self) -> int:
        """Deterministic base sampler seed derived from the identity."""
        return int(_identity_hex_body(self.identity_key())[:8], 16) % _SEED_SPACE


@dataclass(frozen=True)
class ShotPrompt:
    """A consistency-locked prompt + seed for one shot."""

    prompt: str
    negative_prompt: str
    seed: int
    reference_images: tuple[str, ...] = field(default_factory=tuple)
    lora_ref: str = ""


def shot_seed(profile: CharacterProfile, shot_index: int) -> int:
    """A per-shot seed that is stable for (character, shot) but varies per shot.

    Same character + same shot index → same seed (reproducible re-renders); a
    different shot index → a different but deterministic seed (variety without
    drift).
    """
    mixed = hashlib.sha256(f"{profile.identity_key()}:{int(shot_index)}".encode()).hexdigest()
    return int(mixed[:8], 16) % _SEED_SPACE


def build_shot_prompt(
    profile: CharacterProfile,
    action: str,
    *,
    shot_index: int = 0,
    scene: str = "",
    extra_negative: tuple[str, ...] = (),
) -> ShotPrompt:
    """Compose a consistency-injected prompt for a shot.

    The locked descriptors + style are prepended so the identity leads the prompt;
    the action/scene follow. Negatives combine the profile's drift-guards with any
    per-shot extras.
    """
    identity = ", ".join([profile.name, *profile.descriptors]).strip(", ")
    parts = [p for p in [identity, profile.style, scene, action] if p]
    prompt = ", ".join(parts)
    negative = ", ".join([*profile.negative, *extra_negative]).strip(", ")
    return ShotPrompt(
        prompt=prompt,
        negative_prompt=negative,
        seed=shot_seed(profile, shot_index),
        reference_images=profile.reference_images,
        lora_ref=profile.lora_ref,
    )


class IdentityLockFields(NamedTuple):
    """Primitive identity-lock fields the compiler hangs on a SegmentSpec.

    Returned by :func:`build_identity_lock` so this pure module never imports
    ``render_spec`` (avoiding a templates↔characters import cycle): the compiler
    receives primitives and constructs the frozen ``IdentityLock`` itself.
    """

    character_id: str
    identity_key: str
    seed: int
    reference_images: tuple[str, ...]
    lora_ref: str
    negative_prompt: str


def build_identity_lock(
    profile: CharacterProfile, *, shot_index: int = 0
) -> IdentityLockFields:
    """Produce the per-shot identity-lock primitives for a bound character.

    Pure + deterministic: the ``seed`` is the reproducible per-shot seed, the
    ``negative_prompt`` carries the character's drift-guards, and the reference
    sheet + LoRA ref are passed through so the render worker can feed the real
    IPAdapter / LoRA nodes. Independent of any per-shot action text.
    """
    negative = ", ".join(profile.negative).strip(", ")
    return IdentityLockFields(
        character_id=profile.character_id,
        identity_key=profile.identity_key(),
        seed=shot_seed(profile, shot_index),
        reference_images=tuple(profile.reference_images),
        lora_ref=profile.lora_ref,
        negative_prompt=negative,
    )
