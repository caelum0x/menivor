"""Golden-acceptance harness tests.

Two layers:

1. **Helper unit tests** — every assertion in ``tests/golden/acceptance.py`` is
   exercised with a passing case and a failing case (the failing case must raise
   ``AcceptanceError``). These are pure and always run.

2. **Synthetic end-to-end** — a real ``lavfi``-synthesised screen/avatar/audio
   trio is composed through ``compose_avatar_over_screen`` (reusing the approach
   from ``test_compose_integration.py``), probed with ffprobe, and driven through
   the mechanical acceptance checks (resolution / h264 / faststart / duration /
   caption drift). Auto-skipped when ffmpeg/ffprobe (with the required filters)
   is not available.

The manifest (``tests/golden/manifest.yaml``) is also structurally validated so
a malformed golden spec fails fast rather than at real-render time.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Import the acceptance module by file path (tests/golden is not a package).
# --------------------------------------------------------------------------- #
_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
_ACCEPTANCE_PATH = _GOLDEN_DIR / "acceptance.py"
_MANIFEST_PATH = _GOLDEN_DIR / "manifest.yaml"

_spec = importlib.util.spec_from_file_location("reelforge_golden_acceptance", _ACCEPTANCE_PATH)
assert _spec and _spec.loader, "cannot locate tests/golden/acceptance.py"
acceptance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(acceptance)

AcceptanceError = acceptance.AcceptanceError


# --------------------------------------------------------------------------- #
# Synthetic ffprobe JSON fixtures (no ffmpeg needed — pure dicts).
# --------------------------------------------------------------------------- #
def _probe(
    *,
    width: int = 1080,
    height: int = 1920,
    codec: str = "h264",
    duration: str = "30.0",
    bit_rate: str = "8500000",
) -> dict:
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": codec,
                "width": width,
                "height": height,
                "bit_rate": bit_rate,
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": duration, "bit_rate": bit_rate},
    }


def _words(*triples: tuple[str, float, float]):
    """Build a word-timing list as ``(text, start, end)`` tuples."""
    return list(triples)


# --------------------------------------------------------------------------- #
# assert_resolution
# --------------------------------------------------------------------------- #
def test_assert_resolution_pass():
    acceptance.assert_resolution(_probe(), 1080, 1920)


def test_assert_resolution_fail_wrong_size():
    with pytest.raises(AcceptanceError):
        acceptance.assert_resolution(_probe(width=720, height=1280), 1080, 1920)


def test_assert_resolution_fail_no_video_stream():
    with pytest.raises(AcceptanceError):
        acceptance.assert_resolution({"streams": [], "format": {}})


# --------------------------------------------------------------------------- #
# assert_h264_faststart
# --------------------------------------------------------------------------- #
def test_assert_h264_pass_codec_only():
    acceptance.assert_h264_faststart(_probe())


def test_assert_h264_pass_with_faststart_true():
    acceptance.assert_h264_faststart(_probe(), faststart=True)


def test_assert_h264_fail_wrong_codec():
    with pytest.raises(AcceptanceError):
        acceptance.assert_h264_faststart(_probe(codec="hevc"))


def test_assert_h264_fail_not_faststart():
    with pytest.raises(AcceptanceError):
        acceptance.assert_h264_faststart(_probe(), faststart=False)


# --------------------------------------------------------------------------- #
# assert_min_bitrate
# --------------------------------------------------------------------------- #
def test_assert_min_bitrate_pass():
    acceptance.assert_min_bitrate(_probe(bit_rate="8500000"), min_bps=8_000_000)


def test_assert_min_bitrate_pass_low_threshold_for_synthetic():
    # Synthetic clips are tiny; the harness passes a low threshold for them.
    acceptance.assert_min_bitrate(_probe(bit_rate="120000"), min_bps=50_000)


def test_assert_min_bitrate_fail_below_threshold():
    with pytest.raises(AcceptanceError):
        acceptance.assert_min_bitrate(_probe(bit_rate="120000"), min_bps=8_000_000)


def test_assert_min_bitrate_fail_missing():
    probe = _probe()
    probe["format"].pop("bit_rate")
    probe["streams"][0].pop("bit_rate")
    with pytest.raises(AcceptanceError):
        acceptance.assert_min_bitrate(probe, min_bps=1)


# --------------------------------------------------------------------------- #
# assert_duration_window
# --------------------------------------------------------------------------- #
def test_assert_duration_window_pass():
    acceptance.assert_duration_window(_probe(duration="30.0"), 24.0, 36.0)


def test_assert_duration_window_fail_too_long():
    with pytest.raises(AcceptanceError):
        acceptance.assert_duration_window(_probe(duration="90.0"), 24.0, 36.0)


def test_assert_duration_window_fail_invalid_window():
    with pytest.raises(AcceptanceError):
        acceptance.assert_duration_window(_probe(), 36.0, 24.0)


# --------------------------------------------------------------------------- #
# assert_caption_drift
# --------------------------------------------------------------------------- #
def test_assert_caption_drift_pass():
    words = _words(("hello", 0.0, 0.5), ("world", 0.5, 1.0), ("now", 1.0, 1.48))
    acceptance.assert_caption_drift(words, audio_duration=1.5, max_ms=50)


def test_assert_caption_drift_pass_dict_and_object_shapes():
    dict_words = [
        {"text": "a", "start": 0.0, "end": 0.4},
        {"text": "b", "start": 0.4, "end": 0.8},
    ]
    acceptance.assert_caption_drift(dict_words, audio_duration=0.8, max_ms=50)


def test_assert_caption_drift_fail_end_drift():
    words = _words(("hello", 0.0, 0.5), ("world", 0.5, 1.0))
    # Caption ends at 1.0s but audio is 1.5s -> 500 ms drift.
    with pytest.raises(AcceptanceError):
        acceptance.assert_caption_drift(words, audio_duration=1.5, max_ms=50)


def test_assert_caption_drift_fail_non_monotonic():
    words = _words(("hello", 0.5, 1.0), ("world", 0.2, 0.6))
    with pytest.raises(AcceptanceError):
        acceptance.assert_caption_drift(words, audio_duration=1.0, max_ms=50)


def test_assert_caption_drift_fail_overlap():
    words = _words(("hello", 0.0, 0.8), ("world", 0.5, 1.0))
    with pytest.raises(AcceptanceError):
        acceptance.assert_caption_drift(words, audio_duration=1.0, max_ms=50)


def test_assert_caption_drift_fail_end_before_start():
    words = _words(("bad", 1.0, 0.5))
    with pytest.raises(AcceptanceError):
        acceptance.assert_caption_drift(words, audio_duration=0.5, max_ms=50)


def test_assert_caption_drift_fail_empty():
    with pytest.raises(AcceptanceError):
        acceptance.assert_caption_drift([], audio_duration=1.0)


# --------------------------------------------------------------------------- #
# assert_hook_within
# --------------------------------------------------------------------------- #
def test_assert_hook_within_pass():
    hook = _words(("I", 0.0, 0.3), ("wasn't", 0.3, 0.9), ("gonna", 0.9, 2.3))
    acceptance.assert_hook_within(hook, max_s=2.5)


def test_assert_hook_within_fail_too_late():
    hook = _words(("this", 0.0, 1.5), ("takes", 1.5, 3.0))
    with pytest.raises(AcceptanceError):
        acceptance.assert_hook_within(hook, max_s=2.5)


# --------------------------------------------------------------------------- #
# assert_avatar_audio_delta
# --------------------------------------------------------------------------- #
def test_assert_avatar_audio_delta_pass():
    acceptance.assert_avatar_audio_delta(30.05, 30.0, max_s=0.15)


def test_assert_avatar_audio_delta_fail():
    with pytest.raises(AcceptanceError):
        acceptance.assert_avatar_audio_delta(30.5, 30.0, max_s=0.15)


def test_assert_avatar_audio_delta_fail_non_numeric():
    with pytest.raises(AcceptanceError):
        acceptance.assert_avatar_audio_delta("nan-ish", 30.0)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# moov_precedes_mdat (faststart byte scan)
# --------------------------------------------------------------------------- #
def _write_mp4(path: Path, first: bytes, second: bytes) -> None:
    """Write a minimal two-box MP4 with 32-bit box sizes for the scan test."""
    import struct

    def box(box_type: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", 8 + len(payload)) + box_type + payload

    path.write_bytes(box(first, b"\x00" * 16) + box(second, b"\x00" * 64))


def test_moov_precedes_mdat_true(tmp_path):
    p = tmp_path / "faststart.mp4"
    _write_mp4(p, b"moov", b"mdat")
    assert acceptance.moov_precedes_mdat(str(p)) is True


def test_moov_precedes_mdat_false(tmp_path):
    p = tmp_path / "slowstart.mp4"
    _write_mp4(p, b"mdat", b"moov")
    assert acceptance.moov_precedes_mdat(str(p)) is False


def test_moov_precedes_mdat_not_mp4(tmp_path):
    p = tmp_path / "garbage.bin"
    p.write_bytes(b"not an mp4 at all, no atoms here")
    with pytest.raises(AcceptanceError):
        acceptance.moov_precedes_mdat(str(p))


# --------------------------------------------------------------------------- #
# Manifest structural validation
# --------------------------------------------------------------------------- #
def test_manifest_has_ten_jobs_five_each_language():
    yaml = pytest.importorskip("yaml")
    with open(_MANIFEST_PATH, "r", encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh)

    jobs = manifest["jobs"]
    assert len(jobs) == 10, "golden manifest must define exactly 10 jobs"

    languages = [j["language"] for j in jobs]
    assert languages.count("tr") == 5, "expected 5 Turkish golden jobs"
    assert languages.count("en") == 5, "expected 5 English golden jobs"

    ids = [j["id"] for j in jobs]
    assert len(set(ids)) == 10, "golden job ids must be unique"

    allowed_layouts = {"pip", "hook_intro", "split"}
    for job in jobs:
        for key in (
            "id",
            "language",
            "layout",
            "app_context",
            "prompt",
            "target_duration_s",
            "resolution",
            "codec",
            "min_bitrate_bps",
            "caption_drift_ms",
            "hook_max_s",
            "avatar_audio_delta_s",
        ):
            assert key in job, f"job {job.get('id')!r} missing required key {key!r}"
        assert job["layout"] in allowed_layouts, f"bad layout in {job['id']}"
        assert job["resolution"] == {"width": 1080, "height": 1920}
        assert job["codec"] == "h264"
        assert job["caption_drift_ms"] <= 50
        assert job["hook_max_s"] <= 2.5
        assert job["avatar_audio_delta_s"] <= 0.15


# --------------------------------------------------------------------------- #
# Synthetic end-to-end (real ffmpeg) — mechanical acceptance checks
# --------------------------------------------------------------------------- #
from app.services.compose.compose_ffmpeg import (  # noqa: E402
    compose_avatar_over_screen,
    ffmpeg_has_filter,
)
from app.utils import utils  # noqa: E402

_FFMPEG = shutil.which("ffmpeg") or utils.get_ffmpeg_binary()
_FFPROBE = shutil.which("ffprobe")
_REQUIRED_FILTERS = ("chromakey", "geq", "overlay", "scale", "crop", "vstack")


def _have_media_stack() -> bool:
    if not _FFMPEG or not _FFPROBE:
        return False
    return all(ffmpeg_has_filter(f, _FFMPEG) for f in _REQUIRED_FILTERS)


_SKIP_MEDIA = pytest.mark.skipif(
    not _have_media_stack(),
    reason="ffmpeg/ffprobe with required filters not available",
)


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "ffmpeg failed")


def _make_screen(path: str, seconds: float) -> None:
    _run([
        _FFMPEG, "-y", "-f", "lavfi",
        "-i", f"testsrc2=size=1280x720:rate=30:duration={seconds}",
        "-pix_fmt", "yuv420p", path,
    ])


def _make_avatar(path: str, seconds: float) -> None:
    try:
        _run([
            _FFMPEG, "-y", "-f", "lavfi",
            "-i", f"color=c=0x00FF00:size=512x512:rate=30:duration={seconds}",
            "-vf", "drawbox=x=156:y=156:w=200:h=200:color=red@1.0:t=fill",
            "-pix_fmt", "yuv420p", path,
        ])
    except RuntimeError:
        _run([
            _FFMPEG, "-y", "-f", "lavfi",
            "-i", f"color=c=0x00FF00:size=512x512:rate=30:duration={seconds}",
            "-pix_fmt", "yuv420p", path,
        ])


def _make_audio(path: str, seconds: float) -> None:
    _run([
        _FFMPEG, "-y", "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={seconds}",
        "-c:a", "aac", "-b:a", "128k", path,
    ])


def _ffprobe_json(path: str) -> dict:
    result = subprocess.run(
        [_FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def synthetic_inputs(tmp_path_factory) -> dict:
    d = tmp_path_factory.mktemp("golden_inputs")
    screen = str(d / "screen.mp4")
    avatar = str(d / "avatar.mp4")
    audio = str(d / "audio.m4a")
    _make_screen(screen, 2.0)
    _make_avatar(avatar, 2.0)
    _make_audio(audio, 2.0)
    return {"screen": screen, "avatar": avatar, "audio": audio}


@_SKIP_MEDIA
@pytest.mark.integration
def test_synthetic_video_passes_mechanical_acceptance(synthetic_inputs, tmp_path):
    """Compose a synthetic clip and drive it through the acceptance helpers.

    Bitrate uses a low synthetic threshold (a flat-colour + sine clip cannot hit
    the 8 Mbps DoD target); everything else uses the contractual checks.
    """
    out = str(tmp_path / "golden_synthetic.mp4")
    returned = compose_avatar_over_screen(
        synthetic_inputs["screen"],
        synthetic_inputs["avatar"],
        synthetic_inputs["audio"],
        out,
        layout="pip",
        ass_path=None,
        fps=30,
        threads=2,
    )
    assert returned == out
    assert os.path.exists(out) and os.path.getsize(out) > 0

    probe = _ffprobe_json(out)

    # Mechanical acceptance checks over the real ffprobe JSON.
    acceptance.assert_resolution(probe, 1080, 1920)
    acceptance.assert_h264_faststart(
        probe, faststart=acceptance.moov_precedes_mdat(out)
    )
    acceptance.assert_duration_window(probe, 1.4, 3.2)
    # Synthetic clip: assert only that a bitrate exists and clears a low floor.
    acceptance.assert_min_bitrate(probe, min_bps=1_000)

    # Caption-drift check against a word array whose end matches audio duration.
    audio_duration = float(probe["format"]["duration"])
    words = _words(
        ("merhaba", 0.0, audio_duration * 0.5),
        ("dunya", audio_duration * 0.5, audio_duration),
    )
    acceptance.assert_caption_drift(words, audio_duration=audio_duration, max_ms=50)


@_SKIP_MEDIA
@pytest.mark.integration
def test_synthetic_video_with_burned_captions_when_libass(synthetic_inputs, tmp_path):
    """When libass is present, a burned-caption render still meets resolution."""
    if not ffmpeg_has_filter("ass", _FFMPEG):
        pytest.skip("libass (ass filter) not available in this ffmpeg build")

    from app.services.captions.ass_karaoke import write_ass
    from app.services.tts.elevenlabs_timestamps import WordTiming

    ass = str(tmp_path / "cap.ass")
    line = [WordTiming("merhaba", 0.0, 0.6), WordTiming("dunya", 0.6, 1.2)]
    write_ass(ass, [line])

    out = str(tmp_path / "golden_captioned.mp4")
    compose_avatar_over_screen(
        synthetic_inputs["screen"],
        synthetic_inputs["avatar"],
        synthetic_inputs["audio"],
        out,
        layout="hook_intro",
        ass_path=ass,
    )
    probe = _ffprobe_json(out)
    acceptance.assert_resolution(probe, 1080, 1920)
    acceptance.assert_h264_faststart(probe, faststart=acceptance.moov_precedes_mdat(out))
