"""MH0: catalog refresh, price sources, legacy rows, licence rows and the drift check."""

from __future__ import annotations

import re
from datetime import date

import pytest

from app.domains.gateway import media_catalog as mc
from app.domains.routing import license_class as lc
from app.services.loops import price_drift as pd

MH0_NEW_IDS = (
    "kwaivgi/kling-v2.5-turbo-pro",
    "kwaivgi/kling-v3-pro",
    "bytedance/seedance-2.0",
    "bytedance/seedance-2.0-fast",
    "google/veo-3.1-fast-fal",
    "alibaba/wan-2.2-fal",
    "alibaba/wan-2.5",
    "minimax/hailuo-02-pro-fal",
    "lightricks/ltx-2",
    "bytedance/seedream-v4",
    "black-forest-labs/flux-kontext-pro",
    "qwen/qwen-image",
)
MH0_STAGE_IDS = ("sync/lipsync-2", "meigen/infinitetalk", "bytedance/seedvr2-upscale")


def test_every_row_has_a_price_source_and_date():
    for m in mc.all_rows():
        assert re.match(r"^(https://|internal:)", m.price_source), m.id
        assert date.fromisoformat(m.price_date), m.id


def test_new_rows_are_verified_current_and_sourced():
    for mid in MH0_NEW_IDS:
        m = mc.get_model(mid)
        assert m is not None, mid
        assert m.price_verified and not m.legacy, mid
        assert m.price_source.startswith("https://fal.ai/models/"), mid
        assert m.price_date >= "2026-09-28", mid
        assert m.price_micros > 0


def test_stage_rows_are_listed_but_not_on_the_prompt_gateway():
    for mid in MH0_STAGE_IDS:
        assert mc.get_stage_model(mid) is not None
        assert mc.get_model(mid) is None  # /media/* cannot submit a prompt-only job to them
        assert mc.get_stage_model(mid).inputs != ("prompt",)


def test_old_rows_are_kept_and_relabelled_legacy():
    old = mc.get_model("kwaivgi/kling-v1.6")
    assert old is not None and old.legacy and not old.price_verified
    assert old.description.startswith("Legacy:")
    assert old.price_source == "https://fal.ai/models/fal-ai/kling-video/v1.6/standard/text-to-video"
    # No row was removed: the pre-MH0 catalog had 68 gateway rows.
    assert len(mc.list_models()) >= 68 + len(MH0_NEW_IDS) - 3  # 3 refreshed in place
    assert all(m.description.startswith("Legacy:") for m in mc.list_models() if m.legacy)
    assert {m.id for m in mc.current_models()} >= set(MH0_NEW_IDS)


def test_refreshed_prices_match_the_source():
    assert mc.get_model("alibaba/wan-2.2-fal").price_micros == 80_000
    assert mc.get_model("minimax/hailuo-02-fal").price_micros == 45_000
    assert mc.get_model("kwaivgi/kling-v2.5-turbo-pro").price_micros == 70_000  # $0.35 / 5 s


def test_every_row_has_a_licence_and_no_blocked_row_is_current():
    for m in mc.all_rows():
        assert lc.model_license(m.id) is not None, m.id
    for m in [*mc.current_models(), *mc.stage_models()]:
        assert lc.is_model_sellable(m.id), m.id


def test_mh0_licence_rows():
    assert lc.model_license("lightricks/ltx-2").license_class == lc.RESTRICTED
    assert "$10M" in lc.get_license("ltx2").note
    assert lc.model_license("meigen/infinitetalk").license_class == lc.PERMISSIVE
    assert lc.license_key_for_model("black-forest-labs/flux-kontext-pro") == "bfl_api"
    # Blocked rows stay blocked after the refresh.
    assert not lc.is_model_sellable("black-forest-labs/flux-dev")
    assert not lc.is_model_sellable("kwai/kolors")


def test_fal_adapter_accepts_the_bytedance_namespace():
    from app.domains.routing.providers.kling_fal import KlingError, KlingFalAdapter

    for mid in ("bytedance/seedance-2.0", "bytedance/seedance-2.0-fast"):
        ref = mc.get_model(mid).model_ref
        assert KlingFalAdapter(model=ref, api_key="k")._model_id == ref  # noqa: SLF001
    with pytest.raises(KlingError):
        KlingFalAdapter(model="not-a-fal/path", api_key="k")


# --------------------------------------------------------------------------- #
# Drift check
# --------------------------------------------------------------------------- #
def _row(mid="x/y", price=100_000, unit="second", provider="kling-fal", ref="fal-ai/x"):
    return mc.MediaModel(mid, mc.VIDEO, provider, ref, price, unit,
                         price_source="https://fal.ai/models/fal-ai/x", price_date="2026-09-29")


def test_drift_flags_over_ten_percent_only():
    row = _row()
    assert pd.compare(row, pd.LivePrice("fal-ai/x", 0.109, "second")).status == pd.OK
    hit = pd.compare(row, pd.LivePrice("fal-ai/x", 0.111, "second"))
    assert hit.status == pd.DRIFT and hit.delta_pct == 11.0
    low = pd.compare(row, pd.LivePrice("fal-ai/x", 0.05, "second"))
    assert low.status == pd.DRIFT and low.delta_pct == -50.0


def test_drift_converts_minutes_and_refuses_unknown_units():
    row = _row(price=50_000)
    assert pd.compare(row, pd.LivePrice("fal-ai/x", 3.0, "minute")).status == pd.OK
    odd = pd.compare(row, pd.LivePrice("fal-ai/x", 0.35, "video"))
    assert odd.status == pd.UNIT_MISMATCH and odd.live_micros is None
    assert pd.compare(row, None).status == pd.MISSING


def test_check_reads_fal_once_and_lists_other_vendors_as_manual():
    calls = []

    def fake_fetch(ids):
        calls.append(list(ids))
        return {"fal-ai/x": pd.LivePrice("fal-ai/x", 0.2, "second")}

    # A verified vendor row stays "manual"; an unverified sellable one is "unverified" (Wave Q QM1.1).
    rows = [_row(), mc.MediaModel("runwayml/z", mc.VIDEO, "runway", "gen4_turbo", 50_000, "second",
                                  price_source="https://docs.dev.runwayml.com/guides/pricing/",
                                  price_date="2026-09-30", price_verified=True)]
    res = {r.model_id: r for r in pd.check(rows, fal_fetch=fake_fetch)}
    assert calls == [["fal-ai/x"]]
    assert res["x/y"].status == pd.DRIFT
    assert res["runwayml/z"].status == pd.MANUAL


def test_check_reports_unreadable_without_crashing():
    def boom(ids):
        raise RuntimeError("FAL_KEY is not set")

    res = pd.check([_row()], fal_fetch=boom)
    assert res[0].status == pd.UNREADABLE and "FAL_KEY" in res[0].note


def test_full_catalog_drift_run_alerts_the_owner():
    def fetch(ids):
        # Every fal row at its catalog price except Kling 3.0 Pro (+50%).
        out = {}
        for m in mc.all_rows():
            if m.provider in pd.FAL_PROVIDERS:
                ep = pd.fal_endpoint(m)
                usd = m.price_micros / 1_000_000
                if m.id == "kwaivgi/kling-v3-pro":
                    usd *= 1.5
                out[ep] = pd.LivePrice(ep, usd, "megapixel" if m.unit == "megapixel" else m.unit)
        return out

    sent = []
    summary = pd.run(fal_fetch=fetch, send=lambda a: sent.append(a) or True)
    drift_ids = [f["model_id"] for f in summary["flagged"] if f["status"] == pd.DRIFT]
    assert "kwaivgi/kling-v3-pro" in drift_ids
    assert summary["alerted"] is True and "kling-v3-pro" in sent[0].message


def test_quiet_week_sends_nothing():
    summary = pd.summarize([pd.compare(_row(), pd.LivePrice("fal-ai/x", 0.1, "second"))])
    assert pd.alert_for(summary) is None


def test_fal_pricing_fetch_pages_and_batches():
    pages = iter([
        {"prices": [{"endpoint_id": "a", "unit_price": 0.1, "unit": "second", "currency": "USD"}],
         "has_more": True, "next_cursor": "c1"},
        {"prices": [{"endpoint_id": "b", "unit_price": 0.2, "unit": "image"}, {"bad": 1}],
         "has_more": False, "next_cursor": None},
    ])
    seen = []

    def get(url, params):
        seen.append(params)
        return next(pages)

    out = pd.fal_pricing_fetch(api_key="k", get=get)(["a", "b"])
    assert set(out) == {"a", "b"} and out["b"].unit == "image"
    assert ("cursor", "c1") in seen[1]
    with pytest.raises(RuntimeError):
        pd.fal_pricing_fetch(api_key="")


def test_weekly_beat_is_registered():
    from app.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["menivor-price-drift-weekly"]
    assert entry["task"] == pd.TASK_NAME
