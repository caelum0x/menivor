"""Canon — the brand/character lock domain.

A *Canon* hashes and LOCKS the brand/character values a campaign is produced
under (character identity from Wave 4, style/palette/typography, voice, product,
brand tone) so every video, image, and ad is generated *consistently* and its
provenance is *verifiable*. Locking = a deterministic content hash over a
canonical serialization of the normalized values; changing any value yields a
new immutable, versioned lock. Every generated asset records the canon hash it
was produced under, so an ad can be verified as having used the correct locked
brand/character — and regenerated identically.

This is its own domain (not folded into ``characters``/``templates``) to obey
the characters<->templates import-cycle guardrail: the pure core
(:mod:`canon_hash`, :mod:`binding`) imports nothing from those domains and
returns primitives; only :mod:`service` lazy-imports ``characters`` to fold a
bound character's ``identity_key`` in as a primitive string.
"""
