"""Canon hash-lock — deterministic, order-independent, versioned content hash (pure)."""

from __future__ import annotations

import re

from app.domains.canon.canon_hash import (
    CANON_HASH_V1_PREFIX,
    CanonValues,
    canon_hash,
)

_HEX64 = re.compile(r"^cv1\|[0-9a-f]{64}$")


def _values(**over) -> CanonValues:
    base = dict(
        character_identity_key="v2|deadbeef",
        style="3D pixar",
        palette=("#FF0000", "#00ff00"),
        typography=("Inter", "Roboto"),
        voice_id="voice_42",
        voice_tone="warm",
        language="en",
        product_name="Nova Cola",
        product_descriptors=("fizzy", "cold"),
        product_claims=("zero sugar", "vegan"),
        brand_tone=("bold", "playful"),
        brand_avoid=("cheap", "boring"),
    )
    base.update(over)
    return CanonValues(**base)


def test_hash_shape_prefix_and_hex_body():
    h = canon_hash(_values())
    assert _HEX64.match(h), h
    assert h.startswith(CANON_HASH_V1_PREFIX)


def test_deterministic_same_values_same_hash():
    assert canon_hash(_values()) == canon_hash(_values())
    # And the instance method agrees with the module function.
    assert _values().canon_hash() == canon_hash(_values())


def test_order_independent_normalization():
    a = canon_hash(_values(palette=("#FF0000", "#00ff00"),
                           product_descriptors=("fizzy", "cold"),
                           product_claims=("zero sugar", "vegan"),
                           brand_tone=("bold", "playful"),
                           brand_avoid=("cheap", "boring")))
    b = canon_hash(_values(palette=("#00FF00", "#ff0000"),
                           product_descriptors=("cold", "fizzy"),
                           product_claims=("vegan", "zero sugar"),
                           brand_tone=("playful", "bold"),
                           brand_avoid=("boring", "cheap")))
    assert a == b  # reordering + case of hex palette must not change the hash


def test_blank_and_duplicate_tokens_are_dropped():
    a = canon_hash(_values(brand_tone=("bold", "playful")))
    b = canon_hash(_values(brand_tone=("bold", "  ", "playful", "bold", "")))
    assert a == b


def test_characterless_canon_hashes_stably():
    v = CanonValues(style="minimal", palette=("#000000",))
    assert _HEX64.match(canon_hash(v))
    assert canon_hash(v) == canon_hash(CanonValues(style="minimal", palette=("#000000",)))


def test_changing_any_value_changes_hash():
    base = canon_hash(_values())
    assert canon_hash(_values(style="watercolor")) != base
    assert canon_hash(_values(palette=("#123456",))) != base
    assert canon_hash(_values(voice_id="other")) != base
    assert canon_hash(_values(product_claims=("zero sugar",))) != base  # dropped a claim
    assert canon_hash(_values(brand_avoid=("cheap", "boring", "loud"))) != base
    assert canon_hash(_values(character_identity_key="v2|feedface")) != base
