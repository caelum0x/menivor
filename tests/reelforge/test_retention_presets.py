"""Retention export preset builder — loop-back + keyword overlay + safe-zone."""

from __future__ import annotations

from app.services.loops.retention_presets import build_retention_preset, preset_to_dict


def test_asmr_gets_tight_loop_seam():
    p = build_retention_preset(genre="asmr", loopable=True, surface="tiktok")
    assert p.loop_back is True
    # ASMR uses half the default seam threshold (frame-perfect requirement).
    non_asmr = build_retention_preset(genre="edit", loopable=True)
    assert p.max_discontinuity < non_asmr.max_discontinuity


def test_non_loopable_has_no_loopback():
    p = build_retention_preset(genre="recap", loopable=False)
    assert p.loop_back is False


def test_keywords_become_overlay_capped_at_two():
    p = build_retention_preset(
        genre="brainrot-split", loopable=True, keywords=["minecraft", "reddit", "story", "aita"]
    )
    assert p.keyword_overlay is not None
    # Only the top 2 keywords, uppercased.
    assert p.keyword_overlay.text == "MINECRAFT REDDIT"
    assert p.keyword_overlay.position == "top_left"


def test_no_keywords_no_overlay():
    p = build_retention_preset(genre="recap", loopable=False, keywords=[])
    assert p.keyword_overlay is None


def test_safezone_flows_from_surface():
    tiktok = build_retention_preset(genre="x", loopable=False, surface="tiktok")
    shorts = build_retention_preset(genre="x", loopable=False, surface="shorts")
    # Shorts caption band is smaller than TikTok's.
    assert shorts.caption_height_frac < tiktok.caption_height_frac


def test_preset_to_dict_is_json_safe():
    d = preset_to_dict(build_retention_preset(genre="asmr", loopable=True, keywords=["soap"]))
    assert d["loop_back"] is True
    assert d["keyword_overlay"]["text"] == "SOAP"
    assert isinstance(d["notes"], list)
