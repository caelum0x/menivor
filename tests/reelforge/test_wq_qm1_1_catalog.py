"""Wave Q QM1.1: catalogue currency and visible credit sinks (H1, H4, H13, H22).

1. A Nano Banana row and a ``gpt-image-1`` successor row, each priced from its
   source page on the day, with a licence class and the source URL.
2. ``gpt-image-1`` ends 2026-10-23 and routing falls over to the successor
   before that date (clock test). The DALL-E 2 and 3 rows are hidden from
   routing, not deleted. Seedream 4.5 points at the v4.5 path. The dedicated
   ``minimax/hailuo-02`` row is re-priced from the vendor page.
3. The weekly drift check fails on any sellable row without a verified price.
4. App previews: the create-flow apps reuse a live public showcase loop and are
   recorded live; the rest have a render plan and a dry-run record path. Model
   preset previews have a budgeted plan inside the owner's M1 budget.
5. Tiles show no vendor or model names.
"""

from __future__ import annotations

import json
from datetime import date
from importlib import util
from pathlib import Path

import pytest

from app.domains.apps_shelf import catalog as apps
from app.domains.gateway import media_catalog as mc
from app.domains.presets_hub import catalog as presets
from app.domains.routing import license_class as lc
from app.services.loops import price_drift as pd

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "apps" / "api" / "tools" / "ops"
SUCCESSOR = "openai/gpt-image-2.5-flare"


def _tool(name: str):
    spec = util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# 1-2. Rows, end dates, fall-over
# --------------------------------------------------------------------------- #
def test_image_rows_are_current():
    flare = mc.get_row(SUCCESSOR)
    assert flare is not None and flare.modality == mc.IMAGE and flare.price_verified and not flare.legacy
    assert flare.model_ref == "openai/gpt-image-2.5/flare/text-to-image" and flare.provider == "fal-image"
    assert flare.price_micros == 52_680  # fal's default quality is "high": $0.05268 at 1024x1024
    assert flare.price_source == "https://fal.ai/models/openai/gpt-image-2.5/flare/text-to-image"
    nb2 = mc.get_row("google/nano-banana-2")
    assert nb2.model_ref == "fal-ai/nano-banana-2" and nb2.price_micros == 80_000 and nb2.price_verified
    nano = mc.get_row("google/nano-banana")
    assert nano.model_ref == "fal-ai/nano-banana" and nano.price_micros == 39_000 and nano.price_verified
    assert nano.retired_on == "2026-10-02" and nano.successor == "google/nano-banana-2"
    for mid in (SUCCESSOR, "google/nano-banana", "google/nano-banana-2"):
        row = mc.get_row(mid)
        assert row.price_date == "2026-09-30" and row.price_source.startswith("https://")
        assert lc.is_model_sellable(mid) and lc.model_license(mid).license_class == lc.COMMERCIAL_API


def test_gpt_image_1_falls_over_before_its_end_date():
    old = mc.get_row("openai/gpt-image-1")
    assert old.retired_on == "2026-10-23" and old.successor == SUCCESSOR
    assert mc.get_model("openai/gpt-image-1", on=date(2026, 10, 1)).id == "openai/gpt-image-1"
    lead = date.fromisoformat("2026-10-23").toordinal() - mc.FALLOVER_LEAD_DAYS
    assert mc.get_model("openai/gpt-image-1", on=date.fromordinal(lead - 1)).id == "openai/gpt-image-1"
    assert mc.get_model("openai/gpt-image-1", on=date.fromordinal(lead)).id == SUCCESSOR
    assert mc.get_model("openai/gpt-image-1", on=date(2026, 11, 1)).id == SUCCESSOR
    listed = {m.id for m in mc.list_models(on=date(2026, 11, 1))}
    assert "openai/gpt-image-1" not in listed and SUCCESSOR in listed
    assert "openai/gpt-image-1" in {m.id for m in mc.history_rows()}
    lic = lc.get_license(lc.license_key_for_model("openai/gpt-image-1"))
    assert lic.sunset_on == date(2026, 10, 23) and lic.replacement == SUCCESSOR
    # Nano Banana (Gemini 2.5 Flash Image) is shut down 2026-10-02; it already routes to Nano Banana 2.
    assert mc.get_model("google/nano-banana", on=date(2026, 10, 2)).id == "google/nano-banana-2"


def test_dead_rows_are_hidden_from_routing_not_deleted():
    for mid in ("openai/dall-e-3", "openai/dall-e-2"):
        row = mc.get_row(mid)
        assert row is not None and row.retired_on == "2026-05-12"
        assert mc.get_model(mid) is None
        assert mid not in {m.id for m in mc.list_models()}
        assert mc.retired(mid) is not None
        assert mid in {m.id for m in mc.history_rows()}


def test_gateway_answers_410_with_the_successor_for_a_retired_row():
    from app.domains.gateway import media_gateway as gw

    with pytest.raises(gw.GatewayError) as exc:
        gw._model_or_raise("openai/dall-e-3", mc.IMAGE)  # noqa: SLF001
    assert exc.value.status_code == 410 and SUCCESSOR in str(exc.value)
    assert gw._model_or_raise(SUCCESSOR, mc.IMAGE).id == SUCCESSOR  # noqa: SLF001


def test_seedream_label_matches_path():
    row = mc.get_row("bytedance-seed/seedream-4.5")
    assert row.model_ref == "fal-ai/bytedance/seedream/v4.5/text-to-image"
    assert row.price_micros == 40_000 and row.price_verified and row.price_date == "2026-09-30"


def test_hailuo_row_is_repriced():
    from app.domains.routing.providers import minimax_gen

    row = mc.get_row("minimax/hailuo-02")
    # $0.49 per 1080P 6 s video (the adapter asks for 1080P) = $0.0817/s, rounded up.
    assert row.price_micros == 81_700 and row.resolution == "1080p" and row.price_verified
    assert row.price_source == "https://platform.minimax.io/docs/guides/pricing-paygo"
    assert minimax_gen._PRICE_MICROS_PER_SECOND["hailuo-02"] == 81_700  # noqa: SLF001


# --------------------------------------------------------------------------- #
# 3. Drift check
# --------------------------------------------------------------------------- #
def test_drift_check_fails_on_sellable_rows_without_a_verified_price():
    legacy = mc.MediaModel("runwayml/x", mc.VIDEO, "runway", "gen4_turbo", 50_000, "second",
                           price_source="https://docs.dev.runwayml.com/guides/pricing/", price_date="2026-09-29")
    verified = mc.MediaModel("runwayml/y", mc.VIDEO, "runway", "gen4_turbo", 50_000, "second",
                             price_source="https://docs.dev.runwayml.com/guides/pricing/", price_date="2026-09-30",
                             price_verified=True)
    blocked = mc.MediaModel("black-forest-labs/flux-dev", mc.IMAGE, "fal-image", "fal-ai/flux/dev", 25_000,
                            "image", price_source="https://fal.ai/models/fal-ai/flux/dev", price_date="2026-09-29")
    res = {r.model_id: r for r in pd.check([legacy, verified, blocked], fal_fetch=lambda ids: {})}
    assert res["runwayml/x"].status == pd.UNVERIFIED
    assert res["runwayml/y"].status == pd.MANUAL
    assert res["black-forest-labs/flux-dev"].status != pd.UNVERIFIED  # not sellable, never charged
    summary = pd.summarize(res.values())
    assert "runwayml/x" in {f["model_id"] for f in summary["flagged"]}
    assert pd.alert_for(summary) is not None


def test_drift_check_skips_retired_rows_and_a_live_fal_match_counts_as_verified():
    rows = {m.id for m in mc.all_rows()}
    assert "openai/dall-e-3" not in rows
    legacy_fal = mc.get_row("kwaivgi/kling-v1.6")
    live = {pd.fal_endpoint(legacy_fal): pd.LivePrice("x", legacy_fal.price_micros / 1e6, "second")}
    assert pd.check([legacy_fal], fal_fetch=lambda ids: live)[0].status == pd.OK


# --------------------------------------------------------------------------- #
# 4. Previews
# --------------------------------------------------------------------------- #
def test_create_flow_app_previews_are_live_and_the_rest_have_render_jobs():
    """Create-flow apps are live now (a public loop exists); every other app has a render job."""
    tool = _tool("apps_previews")
    live = apps.previews()
    reuse = {j["app_id"]: j for j in tool.plan()["jobs"] if j["kind"] == "reuse_showcase"}
    assert set(reuse) == {"before-after", "click-to-ad", "meme"}
    for app_id, job in reuse.items():
        assert live[app_id] == job["source_key"] and job["source_key"].startswith("showcase/")
        assert not job["source_key"].endswith("-full.mp4")  # the public loop, not the unpublished full reel
    env = {"APPS_PREVIEWS_LIVE": "1", "FAL_KEY": "k"}
    assert {a.id for a in apps.all_apps() if apps.visible(a, env)} >= set(reuse)
    image_apps = [a for a in apps.all_apps() if a.id != "hook-score"]
    assert len(image_apps) == 10
    rendered = tool.render_jobs()
    assert {j["app_id"] for j in rendered} == {a.id for a in apps.all_apps()} - set(reuse)


def test_hook_score_tile_has_a_free_render_job():
    tool = _tool("apps_previews")
    job = next(j for j in tool.render_jobs() if j["app_id"] == "hook-score")
    assert job["lane"] == "mac or box 1 tier 3" and job["cost_usd"] == 0.0
    assert "hook-score" in {j["app_id"] for j in tool.render_jobs(free_only=True)}


def test_preview_record_dry_run_writes_nothing(tmp_path, monkeypatch):
    tool = _tool("apps_previews")
    target = tmp_path / "previews.json"
    target.write_text(json.dumps({"version": 1, "live": {}}), encoding="utf-8")
    monkeypatch.setattr(tool, "PREVIEWS", target)
    out = tool.record("transition", dry_run=True)
    assert out["live"]["transition"] == "presets/apps/transition.mp4"
    assert json.loads(target.read_text())["live"] == {}
    tool.record("transition")
    assert json.loads(target.read_text())["live"] == {"transition": "presets/apps/transition.mp4"}
    with pytest.raises(SystemExit):
        tool.record("not-an-app", dry_run=True)


def test_model_preset_preview_plan_fits_the_m1_budget():
    tool = _tool("model_preset_previews")
    plan = tool.plan(budget_usd=40.0)
    assert len([p for p in presets.all_presets() if p.kind == presets.KIND_MODEL]) == 12
    chosen = [j for j in plan["jobs"] if j["chosen"]]
    assert len(chosen) >= 6 and plan["chosen_cost_usd"] <= 40.0
    assert all(j["funded_by"] == "owner-promo-M1" for j in chosen)
    assert all(mc.get_model(j["model_id"]) is not None for j in plan["jobs"])
    small = tool.plan(budget_usd=0.5)
    assert small["chosen_cost_usd"] <= 0.5


def test_model_preset_record_marks_the_entry_funded_and_staged(tmp_path, monkeypatch):
    tool = _tool("model_preset_previews")
    manifest = tmp_path / "previews.json"
    manifest.write_text(json.dumps({"previews": {}}), encoding="utf-8")
    monkeypatch.setattr(tool, "MANIFEST", manifest)
    entry = tool.record("hero-orbit", spend_usd=0.35, dry_run=False, on="2026-10-01")
    assert entry == {"loop": "presets/hero-orbit.mp4", "poster": "presets/hero-orbit.jpg", "status": "staged",
                     "rendered_at": "2026-10-01", "spend_usd": 0.35, "funded_by": "owner-promo-M1",
                     "source": "our render from the preset's own prompt"}
    from app.domains.presets_hub import previews as pv

    assert not pv.visible(presets.get("hero-orbit"), entry)  # staged: visible only once uploaded and live
    with pytest.raises(SystemExit):
        tool.record("crash-zoom", spend_usd=0.1, dry_run=True)  # a filter preset is not a paid render


# --------------------------------------------------------------------------- #
# 5. Copy
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["Nano Banana", "gpt-image-2.5", "DALL-E", "Gemini", "Imagen 4", "Seedream"])
def test_denylist_catches_the_new_model_names(name):
    assert presets.vendor_hits(f"Made with {name}")


def test_tiles_show_no_vendor_or_model_names():
    for preset in presets.all_presets():
        assert not presets.vendor_hits(f"{preset.name} {preset.blurb}"), preset.id
    for app in apps.all_apps():
        assert not apps.copy_hits(app), app.id
