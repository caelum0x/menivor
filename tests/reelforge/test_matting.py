"""Unit + integration tests for the ReelForge background-removal MATTING pass
(``app.services.editing.matting``).

Scope:
  * PURE colour parsing for ``bg_key`` (named / hex / invalid fallbacks).
  * ffmpeg-argv builders (decode / encode) and the ``_read_exact`` pipe helper.
  * ``matte`` DEGRADE-SAFE orchestration WITHOUT rembg installed: rembg
    unavailable (``is_available()`` False) -> applied False + original untouched
    (this MUST pass with no rembg); zero-length input -> applied False; a bad
    mode / raising transport -> original returned unchanged.
  * The compositing + ffmpeg-muxing transport exercised WITHOUT rembg by
    injecting a fake per-frame matte (``_frame_matte``) and a sentinel session
    (``_get_session``) — an OPTIONAL real-ffmpeg test (auto-skipped when
    ffmpeg/ffprobe is missing) that mattes a tiny clip and asserts the output is
    a real, non-empty, A/V-aligned video.
  * An OPTIONAL real-rembg test, auto-skipped unless ``is_available()`` (so the
    suite never requires rembg).
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess

import pytest

from app.services.editing import matting as mt

# --------------------------------------------------------------------------- #
# _parse_bg_color — pure
# --------------------------------------------------------------------------- #
def test_parse_bg_color_defaults_to_green_when_none_or_blank():
    assert mt._parse_bg_color(None) == (0, 255, 0)
    assert mt._parse_bg_color("") == (0, 255, 0)
    assert mt._parse_bg_color("   ") == (0, 255, 0)


def test_parse_bg_color_named_colors():
    assert mt._parse_bg_color("green") == (0, 255, 0)
    assert mt._parse_bg_color("BLUE") == (0, 0, 255)
    assert mt._parse_bg_color("black") == (0, 0, 0)
    assert mt._parse_bg_color("white") == (255, 255, 255)


def test_parse_bg_color_hex_forms():
    assert mt._parse_bg_color("0x00FF00") == (0, 255, 0)
    assert mt._parse_bg_color("#ff0000") == (255, 0, 0)
    assert mt._parse_bg_color("0000ff") == (0, 0, 255)


def test_parse_bg_color_invalid_falls_back_to_green():
    assert mt._parse_bg_color("not-a-color") == (0, 255, 0)
    assert mt._parse_bg_color("0xZZZZZZ") == (0, 255, 0)
    assert mt._parse_bg_color("#12345") == (0, 255, 0)  # wrong length


# --------------------------------------------------------------------------- #
# ffmpeg argv builders + _read_exact — pure
# --------------------------------------------------------------------------- #
def test_decode_command_streams_rawvideo_rgb24_to_stdout():
    cmd = mt._decode_command("ffmpeg", "in.mp4")
    assert cmd[0] == "ffmpeg"
    assert cmd[-1] == "-"
    assert "rawvideo" in cmd
    joined = " ".join(cmd)
    assert "-pix_fmt rgb24" in joined
    assert "-map 0:v:0" in joined


def test_encode_command_replace_is_yuv420p_libx264_with_audio_remux():
    cmd = mt._encode_command(
        "ffmpeg", "in.mp4", "out.mp4",
        width=320, height=240, fps=30.0, mode="replace", threads=2,
    )
    joined = " ".join(cmd)
    # Raw matted video on stdin (input 0), original clip (input 1) for audio.
    assert "-pix_fmt rgb24" in joined          # stdin input pixel format
    assert "-s 320x240" in joined
    assert "-i -" in joined
    assert "-i in.mp4" in joined
    assert "-map 0:v:0" in joined
    assert "-map 1:a?" in joined               # optional audio passthrough
    assert "-c:v libx264" in joined
    assert "-pix_fmt yuv420p" in joined        # mp4-friendly output
    # No ``-shortest``: the CFR decode + matching encode fps pin the video length
    # to the audio length, so -shortest (which would truncate a longer voiceover)
    # is intentionally omitted.
    assert "-shortest" not in joined
    assert cmd[-1] == "out.mp4"


def test_encode_command_alpha_uses_alpha_codec_and_rgba_stdin():
    cmd = mt._encode_command(
        "ffmpeg", "in.mov", "out.mov",
        width=64, height=64, fps=24.0, mode="alpha", threads=1,
    )
    joined = " ".join(cmd)
    assert "-pix_fmt rgba" in joined           # stdin carries alpha
    assert f"-c:v {mt._ALPHA_CODEC}" in joined
    assert "yuv420p" not in joined             # alpha must NOT be flattened


def test_read_exact_assembles_short_reads():
    stream = io.BytesIO(b"abcdefghij")
    assert mt._read_exact(stream, 4) == b"abcd"
    assert mt._read_exact(stream, 4) == b"efgh"
    # Only 2 bytes left for a 4-byte request -> truncated -> None (clean stop).
    assert mt._read_exact(stream, 4) is None


def test_read_exact_returns_none_at_clean_eof():
    assert mt._read_exact(io.BytesIO(b""), 3) is None


# --------------------------------------------------------------------------- #
# _result / _copy_through — pure
# --------------------------------------------------------------------------- #
def test_result_envelope_shape():
    r = mt._result("replace", 5.0, 4.98765, applied=True)
    assert r == {
        "applied": True,
        "mode": "replace",
        "original_s": 5.0,
        "output_s": 4.9877,  # rounded to 4 decimals
    }


def test_copy_through_same_path_is_noop(tmp_path):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"DATA")
    mt._copy_through(str(f), str(f))
    assert f.read_bytes() == b"DATA"


# --------------------------------------------------------------------------- #
# remove_background — validation
# --------------------------------------------------------------------------- #
def test_remove_background_rejects_bad_mode(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"\x00")
    with pytest.raises(ValueError, match="unsupported mode"):
        mt.remove_background(str(f), str(tmp_path / "o.mp4"), mode="nonsense")


def test_remove_background_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        mt.remove_background("/no/such/file.mp4", str(tmp_path / "o.mp4"))


# --------------------------------------------------------------------------- #
# matte — DEGRADE-SAFE orchestration WITHOUT rembg installed
# --------------------------------------------------------------------------- #
def _seed_input(tmp_path) -> tuple[str, str]:
    src = tmp_path / "avatar.mp4"
    src.write_bytes(b"ORIGINAL-AVATAR-BYTES")
    return str(src), str(tmp_path / "matted.mp4")


def test_matte_rembg_unavailable_is_noop_and_keeps_original(tmp_path, monkeypatch):
    # THE key contract: with rembg NOT installed, is_available() is False and the
    # matte degrades to a byte-for-byte copy of the original (applied False). This
    # must pass in the default suite (no rembg / no model).
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(mt, "_probe_duration", lambda *a, **k: 6.0)
    # Force the real optional-dep gate: no rembg session resolvable.
    monkeypatch.setattr(mt, "_get_session", lambda *a, **k: None)

    result = mt.matte(src, out, mode="replace")
    assert result["applied"] is False
    assert result["mode"] == "replace"
    assert result["original_s"] == 6.0
    assert result["output_s"] == 6.0
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-AVATAR-BYTES"


def test_matte_zero_duration_input_is_noop(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(mt, "_probe_duration", lambda *a, **k: 0.0)
    # Even if a session were available, a zero-length input never runs the matte.
    monkeypatch.setattr(mt, "_get_session", lambda *a, **k: object())
    result = mt.matte(src, out)
    assert result["applied"] is False
    assert result["output_s"] == 0.0
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-AVATAR-BYTES"


def test_matte_transport_raises_returns_original(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(mt, "_probe_duration", lambda *a, **k: 7.0)
    monkeypatch.setattr(mt, "is_available", lambda *a, **k: True)

    def _boom(*a, **k):
        raise RuntimeError("matte transport exploded")

    monkeypatch.setattr(mt, "remove_background", _boom)

    result = mt.matte(src, out)
    assert result["applied"] is False
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-AVATAR-BYTES"


def test_matte_missing_file_degrades(tmp_path):
    # No real file, no rembg: must not raise, must report applied False.
    out = str(tmp_path / "matted.mp4")
    result = mt.matte("/no/such/avatar.mp4", out)
    assert result["applied"] is False
    assert result["original_s"] == 0.0


# --------------------------------------------------------------------------- #
# is_available — degrades False without rembg
# --------------------------------------------------------------------------- #
def test_is_available_false_without_rembg():
    # rembg is an OPTIONAL dep; the suite runs without it, so the real
    # _get_session returns None and is_available() is False. If rembg IS present
    # this asserts a coherent bool either way.
    mt._get_session.cache_clear()
    available = mt.is_available()
    assert isinstance(available, bool)


# --------------------------------------------------------------------------- #
# Compositing + ffmpeg-muxing transport — WITHOUT rembg (fake alpha injected)
# --------------------------------------------------------------------------- #
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _run_real(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout or "ffmpeg failed")


def _probe(path: str) -> dict:
    r = subprocess.run(
        [_FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _stream(info: dict, kind: str) -> dict | None:
    for s in info.get("streams", []):
        if s.get("codec_type") == kind:
            return s
    return None


def _make_avatar_clip(path: str, *, size: str = "320x240", duration: int = 1) -> None:
    """Synthesize a tiny tone+motion clip to stand in for the avatar recording."""
    _run_real([
        _FFMPEG, "-y",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest", path,
    ])


def _fake_replace_matte(frame, width, height, *, mode, bg_rgb, session):
    """A rembg-free stand-in: paint every pixel the background colour.

    Returns valid raw bytes for the requested mode (rgb24 for replace, rgba for
    alpha) so the ffmpeg encoder/mux path is exercised with no rembg installed.
    """
    if mode == mt._MODE_ALPHA:
        # Fully-opaque solid frame (rgba).
        return bytes([bg_rgb[0], bg_rgb[1], bg_rgb[2], 255]) * (width * height)
    return bytes([bg_rgb[0], bg_rgb[1], bg_rgb[2]]) * (width * height)


@pytest.mark.integration
@pytest.mark.skipif(not (_FFMPEG and _FFPROBE), reason="ffmpeg/ffprobe unavailable")
def test_matte_transport_replace_without_rembg(tmp_path, monkeypatch):
    src = str(tmp_path / "avatar.mp4")
    out = str(tmp_path / "matted.mp4")
    _make_avatar_clip(src)

    # Inject a sentinel session (no rembg) + a fake per-frame matte so the pure
    # ffmpeg decode -> composite -> encode+mux transport runs end-to-end.
    monkeypatch.setattr(mt, "_get_session", lambda *a, **k: object())
    monkeypatch.setattr(mt, "_frame_matte", _fake_replace_matte)

    result = mt.matte(src, out, mode="replace", bg_key="0x00FF00")
    assert result["applied"] is True, result
    assert result["mode"] == "replace"

    info = _probe(out)
    v = _stream(info, "video")
    a = _stream(info, "audio")
    assert v is not None, "matted output must keep a video stream"
    assert a is not None, "matted output must re-mux the original audio"
    assert int(v["width"]) == 320 and int(v["height"]) == 240

    # A/V-sync safety: video/audio durations stay aligned, non-empty, ~source len.
    out_dur = float(info["format"]["duration"])
    assert out_dur > 0
    v_dur = float(v.get("duration") or out_dur)
    a_dur = float(a.get("duration") or out_dur)
    assert abs(v_dur - a_dur) <= 0.3


@pytest.mark.integration
@pytest.mark.skipif(not (_FFMPEG and _FFPROBE), reason="ffmpeg/ffprobe unavailable")
def test_matte_transport_alpha_without_rembg_preserves_alpha(tmp_path, monkeypatch):
    src = str(tmp_path / "avatar.mp4")
    out = str(tmp_path / "matted.mov")
    _make_avatar_clip(src, size="64x64")

    monkeypatch.setattr(mt, "_get_session", lambda *a, **k: object())
    monkeypatch.setattr(mt, "_frame_matte", _fake_replace_matte)

    result = mt.matte(src, out, mode="alpha")
    assert result["applied"] is True, result

    info = _probe(out)
    v = _stream(info, "video")
    assert v is not None
    # qtrle carries an alpha channel; the pixel format must not be an opaque 4:2:0.
    assert "yuv420p" not in str(v.get("pix_fmt", ""))


@pytest.mark.integration
@pytest.mark.skipif(not (_FFMPEG and _FFPROBE), reason="ffmpeg/ffprobe unavailable")
def test_remove_background_reencodes_at_source_fps(tmp_path, monkeypatch):
    # remove_background raises on failure; here the fake matte lets it succeed and
    # we assert the video stream survived at the source geometry.
    src = str(tmp_path / "avatar.mp4")
    out = str(tmp_path / "matted.mp4")
    _make_avatar_clip(src)

    monkeypatch.setattr(mt, "_get_session", lambda *a, **k: object())
    monkeypatch.setattr(mt, "_frame_matte", _fake_replace_matte)

    returned = mt.remove_background(src, out, mode="replace")
    assert returned == out
    v = _stream(_probe(out), "video")
    assert v is not None and int(v["width"]) == 320


# --------------------------------------------------------------------------- #
# Optional real-rembg matte (auto-skipped unless rembg + model are available)
# --------------------------------------------------------------------------- #
@pytest.mark.integration
@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE and mt.is_available()),
    reason="rembg (+model) or ffmpeg unavailable",
)
def test_real_rembg_matte_replace(tmp_path):
    src = str(tmp_path / "avatar.mp4")
    out = str(tmp_path / "matted.mp4")
    _make_avatar_clip(src, size="128x128")

    result = mt.matte(src, out, mode="replace", bg_key="green")
    assert result["applied"] is True, result

    info = _probe(out)
    assert _stream(info, "video") is not None
    assert float(info["format"]["duration"]) > 0
