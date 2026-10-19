"""Unit: stories.contract — template-bound draft + ReelForgeParams fold."""

from __future__ import annotations

import pytest

from app.domains.stories.contract import (
    DEFAULT_MAX_WORDS,
    MINECRAFT_SLUG,
    build_story_reel_draft,
    story_params,
)
from app.domains.templates.validation import TemplateError
from app.services.reelforge import ReelForgeParams

_SCRIPT = "Something wild happened. Then it got worse. Comment if you want Part 2."


def test_constants():
    assert MINECRAFT_SLUG == "minecraft-reddit-split"
    assert DEFAULT_MAX_WORDS == 130


def test_build_story_reel_draft_shape():
    draft = build_story_reel_draft(_SCRIPT, subject="AITA roommate")
    assert draft["layout"] == "split"
    assert draft["caption_style"] == "karaoke_yellow"
    # The flagship minecraft loop is pinned (not the compiler's stock fallback).
    assert draft["background_id"] == "voxel-parkour"
    assert draft["video_script"] == _SCRIPT
    assert draft["video_subject"] == "AITA roommate"
    # No gameplay clip supplied — the split preset auto-fills the background.
    assert "screen_recording_key" not in draft


def test_build_story_reel_draft_folds_voice_and_aspect():
    draft = build_story_reel_draft(_SCRIPT, subject="x", voice_id="rachel", aspect="9:16")
    assert draft["voice_name"] == "elevenlabs:rachel"
    assert draft["aspect"] == "9:16"


def test_invalid_story_raises_template_error():
    with pytest.raises(TemplateError):
        build_story_reel_draft("", subject="x")


def test_story_params_defaults_skip_upload():
    params = story_params(_SCRIPT, subject="AITA")
    assert isinstance(params, ReelForgeParams)
    assert params.platforms == ()  # empty => render chain skips stage_upload
    assert params.layout == "split"
    assert params.caption_style == "karaoke_yellow"
    assert params.background_id == "voxel-parkour"
    assert params.video_script == _SCRIPT
    assert params.voice_name == ""


def test_story_params_voice_mapping():
    params = story_params(_SCRIPT, subject="AITA", voice_id="adam")
    assert params.voice_name == "elevenlabs:adam"


def test_story_params_is_immutable():
    params = story_params(_SCRIPT, subject="AITA")
    with pytest.raises(Exception):
        params.video_script = "mutated"  # type: ignore[misc]


def test_story_params_passthrough_platforms():
    params = story_params(_SCRIPT, subject="AITA", platforms=("tiktok",))
    assert params.platforms == ("tiktok",)
