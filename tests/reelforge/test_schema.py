"""DTO-boundary validation for the Phase-6 Creator-Studio request models.

Covers the ``caption_style`` / ``music_id`` allowlists on ``JobCreateRequest``
and ``RerunOverrides`` (INTEGRATION_CONTRACT §6). These guard against the
silent-fallback defects where an unknown ``caption_style`` renders in the
default preset and an unknown/malformed ``music_id`` silently drops the
background track — both after a credit has already been debited.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.schema import CoverRequest, JobCreateRequest, RerunOverrides
from app.services.captions.presets import CAPTION_STYLE_PRESETS
from app.services.cover import _MAX_HEADLINE_CHARS


# --------------------------------------------------------------------------- #
# caption_style — static preset allowlist
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("style_id", sorted(CAPTION_STYLE_PRESETS.keys()))
def test_job_create_accepts_known_caption_style(style_id: str) -> None:
    req = JobCreateRequest(params={"video_subject": "x"}, caption_style=style_id)
    assert req.caption_style == style_id


def test_job_create_caption_style_none_and_blank_pass_through() -> None:
    assert JobCreateRequest().caption_style is None
    assert JobCreateRequest(caption_style="").caption_style == ""


@pytest.mark.parametrize("bad", ["bold-violet", "karaokeyellow", "does-not-exist", "KARAOKE_YELLOW"])
def test_job_create_rejects_unknown_caption_style(bad: str) -> None:
    with pytest.raises(ValidationError) as exc:
        JobCreateRequest(caption_style=bad)
    assert "caption_style" in str(exc.value)


def test_rerun_overrides_rejects_unknown_caption_style() -> None:
    # A valid override still constructs cleanly.
    ok = RerunOverrides(caption_style="karaoke_green")
    assert ok.caption_style == "karaoke_green"
    with pytest.raises(ValidationError):
        RerunOverrides(caption_style="bold-violet")


# --------------------------------------------------------------------------- #
# music_id — slug-shape validation (catalog-mintable form)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("music_id", ["upbeat", "lofi", "output000", "track-2", "a1"])
def test_job_create_accepts_well_formed_music_id(music_id: str) -> None:
    req = JobCreateRequest(music_id=music_id)
    assert req.music_id == music_id


def test_job_create_music_id_none_and_blank_pass_through() -> None:
    assert JobCreateRequest().music_id is None
    assert JobCreateRequest(music_id="").music_id == ""


@pytest.mark.parametrize(
    "bad",
    [
        "../../etc/passwd",   # path traversal
        "Upbeat",             # uppercase (slugs are lowercased)
        "up beat",            # whitespace
        "up_beat",            # underscore (never minted by the slugger)
        "track/2",            # path separator
        "-lead",              # leading separator
        "trail-",             # trailing separator
        "double--dash",       # empty slug segment
    ],
)
def test_job_create_rejects_malformed_music_id(bad: str) -> None:
    with pytest.raises(ValidationError) as exc:
        JobCreateRequest(music_id=bad)
    assert "music_id" in str(exc.value)


def test_rerun_overrides_rejects_malformed_music_id() -> None:
    ok = RerunOverrides(music_id="upbeat")
    assert ok.music_id == "upbeat"
    with pytest.raises(ValidationError):
        RerunOverrides(music_id="../secret")


# --------------------------------------------------------------------------- #
# CoverRequest.headline — max_length must match the renderer's hard cap so an
# over-long headline is rejected at the boundary instead of silently truncated.
# --------------------------------------------------------------------------- #
def test_cover_request_headline_max_length_matches_render_cap() -> None:
    schema_max = CoverRequest.model_fields["headline"].metadata
    # Pydantic v2 stores the constraint as a MaxLen marker in field metadata.
    max_lens = [getattr(m, "max_length", None) for m in schema_max]
    assert _MAX_HEADLINE_CHARS in max_lens


def test_cover_request_accepts_headline_at_cap() -> None:
    req = CoverRequest(headline="x" * _MAX_HEADLINE_CHARS)
    assert req.headline is not None
    assert len(req.headline) == _MAX_HEADLINE_CHARS


def test_cover_request_rejects_headline_over_cap() -> None:
    with pytest.raises(ValidationError) as exc:
        CoverRequest(headline="x" * (_MAX_HEADLINE_CHARS + 1))
    assert "headline" in str(exc.value)


def test_cover_request_headline_and_style_optional() -> None:
    req = CoverRequest()
    assert req.headline is None
    assert req.style is None
