"""MO1 paid-gate matrix: no non-commercial model can back a paid output.

Covers every place a paying user can be charged for a model:

* the route gate (``routing.license_class``) on every paid plan;
* the media gateway (every call is wallet funded);
* the reviewed catalog's live promotion (MusicGen is never purchasable);
* the speak lipsync gate (LatentSync fails closed until MO12b);
* the paid presenter stage and its pre-debit capability check.

It also pins the register: every gateway and catalog row carries a recorded
licence, and ``docs/THIRD_PARTY_MODELS.md`` lists every licence key.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.domains.routing import license_class as lc

TODAY = date(2026, 9, 29)
REPO_ROOT = Path(__file__).resolve().parents[4]

# PLAN-menivor MO1 acceptance list plus the rows MO1 adds.
MUST_BLOCK = (
    "latentsync",
    "wav2lip",
    "f5_tts",
    "xtts",
    "musicgen",
    "flux_dev",
    "flux_krea",
    "liveportrait",
    "mmaudio",
    "flux2_klein_9b",
    "rmbg2",
    "hunyuanvideo",
)
MUST_ALLOW = ("kling", "veo", "musetalk", "kokoro", "chatterbox", "flux_schnell", "wan22", "heygen")


def _paid_plan_keys() -> list[str]:
    from app.services.billing import creator_plans, plans

    keys = [p.key for p in plans.list_plans() if p.key != plans.FREE_KEY]
    keys += [f"creator:{p.key}" for p in creator_plans.list_plans()]
    return keys


# --------------------------------------------------------------------------- #
# Route gate, per paid plan
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("plan_key", _paid_plan_keys())
@pytest.mark.parametrize("model_key", MUST_BLOCK)
def test_non_commercial_is_blocked_on_every_paid_plan(plan_key, model_key):
    assert plan_key  # the gate is plan-agnostic: any paid plan is paid=True
    assert lc.is_paid_safe(model_key) is False
    assert lc.is_route_allowed(model_key, paid=True, on=TODAY) is False
    assert lc.is_model_sellable(model_key) is False
    with pytest.raises(lc.LicenseError):
        lc.assert_route_allowed(model_key, paid=True, on=TODAY)
    with pytest.raises(lc.LicenseError):
        lc.assert_model_sellable(model_key)


@pytest.mark.parametrize("model_key", MUST_BLOCK)
def test_free_and_research_paths_still_run(model_key):
    # Nothing is removed: the free path may still route to these weights.
    assert lc.get_license(model_key) is not None
    assert lc.is_route_allowed(model_key, paid=False, on=TODAY) is True


@pytest.mark.parametrize("model_key", MUST_ALLOW)
def test_commercial_models_stay_sellable(model_key):
    assert lc.is_model_sellable(model_key) is True
    assert lc.is_route_allowed(model_key, paid=True, on=TODAY) is True


def test_unknown_model_fails_closed():
    assert lc.license_key_for_model("mystery-lab/unknown-model") is None
    assert lc.is_model_sellable("mystery-lab/unknown-model") is False
    assert lc.is_model_sellable("") is False
    with pytest.raises(lc.LicenseError, match="no recorded licence"):
        lc.assert_model_sellable("mystery-lab/unknown-model")


def test_exact_id_beats_vendor_namespace():
    # flux-dev lives under the BFL namespace but is not the BFL commercial API.
    assert lc.license_key_for_model("black-forest-labs/flux-dev") == "flux_dev"
    assert lc.license_key_for_model("black-forest-labs/flux-1.1-pro") == "bfl_api"
    assert lc.is_model_sellable("black-forest-labs/flux-1.1-pro") is True


def test_every_row_has_a_known_class():
    for row in lc.all_licenses():
        assert row.license_class in lc.ALL_CLASSES, row


# --------------------------------------------------------------------------- #
# Media gateway: every row recorded; no blocked row can be charged
# --------------------------------------------------------------------------- #
def _media_rows():
    from app.domains.gateway.media_catalog import list_models

    return list_models()


def test_every_gateway_row_has_a_recorded_licence():
    missing = [m.id for m in _media_rows() if lc.model_license(m.id) is None]
    assert missing == [], f"add a licence row in routing/license_class.py for: {missing}"


def test_gateway_refuses_every_blocked_row_and_serves_the_rest():
    from app.domains.gateway import media_gateway as gw

    blocked = []
    for m in _media_rows():
        if lc.is_model_sellable(m.id):
            assert gw._model_or_raise(m.id, m.modality) is not None  # noqa: SLF001
            continue
        blocked.append(m.id)
        with pytest.raises(gw.GatewayError) as exc:
            gw._model_or_raise(m.id, m.modality)  # noqa: SLF001
        assert exc.value.status_code == 403
    assert "black-forest-labs/flux-dev" in blocked
    assert "tencent/hunyuan-video" in blocked


def test_gateway_listing_keeps_rows_and_flags_sellable():
    from app.domains.gateway.media_router import _model_view
    from app.domains.gateway.media_catalog import get_model

    dev = _model_view(get_model("black-forest-labs/flux-dev"))
    assert dev["sellable"] is False and dev["license_class"] == lc.NON_COMMERCIAL
    schnell = _model_view(get_model("black-forest-labs/flux-schnell"))
    assert schnell["sellable"] is True


# --------------------------------------------------------------------------- #
# Reviewed catalog: MusicGen is never purchasable
# --------------------------------------------------------------------------- #
def test_every_catalog_seed_row_has_a_recorded_licence():
    from app.domains.catalog.seed_data import MODELS

    missing = [m["model_id"] for m in MODELS if lc.model_license(m["model_id"]) is None]
    assert missing == [], f"add a licence row in routing/license_class.py for: {missing}"


@pytest.fixture()
def catalog_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.domains.catalog.seed_data import seed_default_catalog
    from app.models.db.base import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as s:
        seed_default_catalog(s)
        s.commit()
    with factory() as s:
        yield s


class _AnyAdapter:
    def __init__(self, key: str) -> None:
        self._key = key

    @property
    def provider_key(self) -> str:
        return self._key


def test_musicgen_catalog_item_is_not_purchasable(catalog_session):
    from app.domains.catalog.admin import CatalogAdmin, PromotionError
    from app.domains.routing.base import ProviderRegistry

    reg = ProviderRegistry()
    reg.register(_AnyAdapter("meta"))  # even with an adapter and a price
    admin = CatalogAdmin(catalog_session)
    readiness = admin.promotion_readiness("meta/musicgen-large", provider_registry=reg)
    assert readiness["has_adapter"] is True
    assert readiness["license_ok"] is False
    assert readiness["ready"] is False
    assert any("non_commercial" in r for r in readiness["reasons"])
    with pytest.raises(PromotionError):
        admin.promote_model_live("meta/musicgen-large", provider_registry=reg)


def test_commercial_catalog_item_still_promotes(catalog_session):
    from app.domains.catalog.admin import CatalogAdmin
    from app.domains.routing.base import ProviderRegistry

    reg = ProviderRegistry()
    reg.register(_AnyAdapter("suno"))
    out = CatalogAdmin(catalog_session).promote_model_live("suno/v4", provider_registry=reg)
    assert out["release_status"] == "ga"


# --------------------------------------------------------------------------- #
# Speak lipsync and the paid presenter stage
# --------------------------------------------------------------------------- #
def test_speak_gate_blocks_latentsync_and_wav2lip():
    from app.domains.speak import licensing as sp

    for key in ("latentsync", "wav2lip"):
        assert sp.is_commercial_ok(key) is False
        with pytest.raises(sp.LicenseClassError):
            sp.require_commercial_ok(key)
    assert sp.is_commercial_ok("musetalk") is True


def test_paid_presenter_stage_refuses_latentsync(monkeypatch):
    from app.domains.reels import premium
    from app.services import reelforge

    monkeypatch.setattr(premium, "ai_video_funded", lambda job_id, ctx: True)
    params = reelforge.ReelForgeParams(
        video_subject="demo", avatar_id="ref.png", avatar_provider="latentsync", layout="pip"
    )
    with pytest.raises(reelforge.ReelForgeStageError, match="not licensed for paid output"):
        reelforge.stage_avatar("job-mo1", params, {"audio_url": "https://example.test/a.mp3"})


def test_pre_debit_capability_never_offers_latentsync(monkeypatch):
    from app.core.launch import formats

    monkeypatch.setattr(formats, "avatar_provider_enabled", lambda provider_id="heygen": True)
    assert formats._paid_avatar_enabled("latentsync") is False  # noqa: SLF001
    assert formats._paid_avatar_enabled("heygen") is True  # noqa: SLF001


# --------------------------------------------------------------------------- #
# The human-readable register stays in sync
# --------------------------------------------------------------------------- #
def test_third_party_models_doc_lists_every_licence_key():
    doc = (REPO_ROOT / "docs" / "THIRD_PARTY_MODELS.md").read_text(encoding="utf-8")
    missing = [row.model_key for row in lc.all_licenses() if f"`{row.model_key}`" not in doc]
    assert missing == [], f"docs/THIRD_PARTY_MODELS.md is missing: {missing}"
