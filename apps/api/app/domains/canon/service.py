"""Canon service — bridge the pure core to the DB and fold in Wave-4 identity.

The pure core (:mod:`canon_hash`, :mod:`binding`) never imports
``characters``/``templates`` (import-cycle guardrail). This service is the one
place that LAZY-imports ``app.domains.characters`` to compute a bound
character's ``identity_key`` and fold it into :class:`CanonValues` as a
primitive string, then drives :class:`CanonRepository`.

It also exposes :func:`verify_asset`, which loads an ``Asset`` row and the
matching ``CanonVersion`` (by the asset's stamped hash within the canon, else
the canon's current version) and runs :func:`binding.verify_asset`.
"""

from __future__ import annotations

from typing import Any

from app.domains.canon import binding
from app.domains.canon.binding import VerifyResult
from app.domains.canon.canon_hash import CanonValues
from app.domains.canon.repository import CanonRepository


def _character_identity_key(session: Any, character_id: str | None) -> str:
    """Return the bound character's durable Wave-4 ``identity_key``, or ``""``.

    Lazy-imports ``characters`` so the pure canon core stays cycle-free. The
    STORED ``identity_key`` is folded in — it is the durable, indexed content
    hash the characters domain persists and dedupes on (recomputed in-transaction
    on every write via ``repository.set_lora_ref``), so the canon lock cross-checks
    against exactly the value other systems reference. A missing/invalid character
    folds an empty string (the canon simply carries no character component).
    """
    if not character_id:
        return ""
    from app.models.db.characters import Character

    row = session.get(Character, character_id)
    if row is None or not row.identity_key:
        return ""
    return str(row.identity_key)


def build_values(
    session: Any,
    *,
    character_id: str | None = None,
    style: str = "",
    palette: Any = (),
    typography: Any = (),
    voice_id: str = "",
    voice_tone: str = "",
    language: str = "",
    product_name: str = "",
    product_descriptors: Any = (),
    product_claims: Any = (),
    brand_tone: Any = (),
    brand_avoid: Any = (),
) -> CanonValues:
    """Assemble a :class:`CanonValues`, folding the bound character identity in."""
    return CanonValues(
        character_identity_key=_character_identity_key(session, character_id),
        style=style,
        palette=tuple(palette or ()),
        typography=tuple(typography or ()),
        voice_id=voice_id,
        voice_tone=voice_tone,
        language=language,
        product_name=product_name,
        product_descriptors=tuple(product_descriptors or ()),
        product_claims=tuple(product_claims or ()),
        brand_tone=tuple(brand_tone or ()),
        brand_avoid=tuple(brand_avoid or ()),
    )


def verify_asset(session: Any, asset_id: str, canon_id: str) -> VerifyResult:
    """Verify that ``asset_id`` was produced under ``canon_id``'s locked values.

    Resolves the CanonVersion by the asset's stamped ``canon_hash`` (scoped to
    the canon), falling back to the canon's current version so an unstamped or
    wrongly-stamped asset still fails the provenance gate rather than erroring.
    """
    from app.models.db.models import Asset

    asset = session.get(Asset, asset_id)
    if asset is None:
        return VerifyResult(False, "asset not found")

    repo = CanonRepository(session)
    meta = dict(asset.meta or {})
    stamped_hash = str(meta.get("canon_hash") or "")

    version_row = None
    if stamped_hash:
        version_row = repo.get_version_by_hash(canon_id, stamped_hash)
    if version_row is None:
        canon = repo.get(canon_id)
        if canon is not None:
            version_row = repo.get_version(canon_id, canon.current_version)
    if version_row is None:
        return VerifyResult(False, "canon version not found")

    return binding.verify_asset(meta, version_row)
