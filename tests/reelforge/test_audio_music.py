"""Music planning — section timing + prompt assembly."""

from __future__ import annotations

import pytest

from app.services.audio.music import plan_music, total_section_coverage


def test_structured_plan_has_build_body_outro():
    plan = plan_music(45.0, hook_end_s=3.0, mood="lofi")
    names = [s.name for s in plan.sections]
    assert names == ["build", "body", "outro"]
    # Sections tile the whole duration.
    assert total_section_coverage(plan) == pytest.approx(45.0, abs=0.05)
    assert "lofi" in plan.prompt


def test_short_reel_collapses_to_single_body():
    # build(0.8) + outro(0.5) = 1.3 >= 1.0 total -> collapse to a single body.
    plan = plan_music(1.0, hook_end_s=0.5)
    assert len(plan.sections) == 1 and plan.sections[0].name == "body"
    assert plan.warnings


def test_build_covers_hook_clamped():
    plan = plan_music(30.0, hook_end_s=10.0)  # hook longer than max build
    build = next(s for s in plan.sections if s.name == "build")
    assert build.duration <= 3.0  # clamped to _MAX_BUILD_S


def test_invalid_duration_rejected():
    with pytest.raises(ValueError):
        plan_music(0.0)
