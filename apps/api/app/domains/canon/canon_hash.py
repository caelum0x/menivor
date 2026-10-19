"""Canon hash-lock — the pure, deterministic content address of locked values.

A :class:`CanonValues` bundle carries every value a campaign locks: the Wave-4
character ``identity_key`` (folded in as a PRIMITIVE string — this module never
imports ``characters``), the visual style/palette/typography, the voice, the
product facts, and the brand tone / drift-guards. ``canon_hash`` canonicalizes
and hashes that bundle to a stable, versioned content address.

Determinism (identical to ``consistency.identity_key``): every list field is
stripped of blanks, de-duplicated, and sorted so the hash is independent of
insertion order (and, for the palette, of hex case); scalars are stripped. The
same locked values therefore yield a byte-identical hash across calls,
processes, and machines — no shared RNG, no floats in the hash.

Immutable + versioned: the hash IS the content address. There is no in-place
edit primitive — changing ANY value changes the canonical bytes, hence the hash,
hence the version. The ``"cv1|"`` prefix versions the *scheme* itself (a future
normalization/algorithm change becomes ``"cv2|"``) exactly like
``consistency.IDENTITY_KEY_V2_PREFIX``, so old locked rows are never orphaned.

Algorithm note: ``sha256`` (``hashlib``, the house standard — ``blake3`` is not
a repo dependency). The founder's "blake3/sha256" is satisfied by sha256; a
later swap is isolated to :func:`canon_hash`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

# Version prefix stamped on every canon hash. Bumping the normalization or the
# digest algorithm becomes ``"cv2|"`` without orphaning existing ``"cv1|"`` rows.
CANON_HASH_V1_PREFIX = "cv1|"


def _dedupe_sorted(values: object) -> tuple[str, ...]:
    """Strip blanks, de-duplicate, and sort — order-independent normalization."""
    if not values:
        return ()
    return tuple(sorted({str(v).strip() for v in values if str(v).strip()}))


def _dedupe_sorted_lower(values: object) -> tuple[str, ...]:
    """Like :func:`_dedupe_sorted` but lower-cased (hex palette entries)."""
    if not values:
        return ()
    return tuple(sorted({str(v).strip().lower() for v in values if str(v).strip()}))


@dataclass(frozen=True)
class CanonValues:
    """The frozen bundle of values a campaign locks under one canon version.

    All list fields are normalized (strip/dedupe/sort) at hash time so field
    ordering is irrelevant to the content address. ``character_identity_key`` is
    passed through verbatim — it is already a Wave-4 content hash (a primitive),
    so this module needs no knowledge of how it was produced.
    """

    character_identity_key: str = ""
    style: str = ""
    palette: tuple[str, ...] = ()        # hex colors, sorted + lowercased
    typography: tuple[str, ...] = ()     # font names, sorted
    voice_id: str = ""
    voice_tone: str = ""
    language: str = ""
    product_name: str = ""
    product_descriptors: tuple[str, ...] = ()
    product_claims: tuple[str, ...] = ()
    brand_tone: tuple[str, ...] = ()
    brand_avoid: tuple[str, ...] = ()    # the drift-guards

    def normalized_dict(self) -> dict:
        """Return the canonical, order-independent dict that gets hashed.

        This is also the exact payload persisted in ``canon_versions.values`` so
        that integrity can be recomputed and the values regenerated from later.
        The output is idempotent — re-normalizing a normalized dict is a no-op —
        so a stored row always recomputes to its stored hash.
        """
        return {
            "character_identity_key": (self.character_identity_key or ""),
            "style": (self.style or "").strip(),
            "palette": list(_dedupe_sorted_lower(self.palette)),
            "typography": list(_dedupe_sorted(self.typography)),
            "voice_id": (self.voice_id or "").strip(),
            "voice_tone": (self.voice_tone or "").strip(),
            "language": (self.language or "").strip(),
            "product_name": (self.product_name or "").strip(),
            "product_descriptors": list(_dedupe_sorted(self.product_descriptors)),
            "product_claims": list(_dedupe_sorted(self.product_claims)),
            "brand_tone": list(_dedupe_sorted(self.brand_tone)),
            "brand_avoid": list(_dedupe_sorted(self.brand_avoid)),
        }

    def canon_hash(self) -> str:
        """The versioned content hash of these locked values."""
        return canon_hash(self)


def _canonical_bytes(values_dict: dict) -> bytes:
    """Deterministic byte encoding of a normalized values dict.

    Mirrors ``catalog.policy._canonical_quote_bytes``: sorted keys, no
    whitespace. ``ensure_ascii=False`` keeps unicode brand terms stable under a
    single UTF-8 encoding.
    """
    return json.dumps(
        values_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canon_hash(values: CanonValues) -> str:
    """Return the versioned ``"cv1|"`` + sha256-hex content address of ``values``."""
    body = hashlib.sha256(_canonical_bytes(values.normalized_dict())).hexdigest()
    return f"{CANON_HASH_V1_PREFIX}{body}"
