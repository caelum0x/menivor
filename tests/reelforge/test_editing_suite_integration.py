"""Integration tests for the opt-in editing-polish suite compose PRE-steps.

These verify the wiring landed by the Integrate layer — NOT the individual
editing algorithms (those are covered by ``test_auto_zoom.py`` /
``test_motion.py`` / ``test_matting.py`` / ``test_silence_cut.py``):

  * ``auto_zoom=True`` routes the downloaded SCREEN RECORDING through
    :func:`app.services.editing.auto_zoom` (asserted via the mockable seam);
    ``camera_motion=<preset>`` routes it through
    :func:`app.services.editing.motion`; ``remove_bg=True`` routes the AVATAR
    clip through :func:`app.services.editing.matte`. Each records a ``JobEvent``
    telemetry row and hands the transformed file to compose.
  * All-off (the default) leaves the compose path byte-for-byte unchanged: NONE
    of the passes are called and the ORIGINAL screen recording + avatar reach
    compose.
  * Ordering: the screen passes run tighten -> auto_zoom -> motion, so with all
    screen flags on compose receives the LAST screen transform's output.
  * A golden-style invariant: the polish passes NEVER touch the voiceover/caption
    timeline. The audio (voiceover) and the ``.ass`` caption artifact handed to
    compose are identical whether or not any flag is on, so the caption-drift
    gate is unaffected (the timeline is the single source of truth, independent
    of the polished background/avatar).

All I/O (R2 download/upload, ffmpeg compose, the editing passes, telemetry) is
monkeypatched, so these tests never touch the network, ffmpeg or a database.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.services import editing, reelforge
from app.services.compose import compose_ffmpeg
from app.services.editing import auto_zoom as auto_zoom_module
from app.services.reelforge import ReelForgeParams


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _FakeR2:
    """Records upload_file calls without touching the network / disk."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str]] = []

    def upload_file(self, local_path: str, key: str, content_type: str) -> str:
        self.uploads.append((local_path, key, content_type))
        return f"https://cdn.example/{key}"


def _params(**over: Any) -> ReelForgeParams:
    base: dict[str, Any] = {
        "video_subject": "demo",
        "voice_name": "elevenlabs:abc",
        "avatar_id": "av123",
        "screen_recording_key": "jobs/jobE/screen.mp4",
    }
    base.update(over)
    return ReelForgeParams(**base)


def _writing_spy(calls: list[dict[str, Any]], result: dict[str, Any]):
    """Build a pass spy that records its call, writes its output, returns result."""

    def _spy(input_path, output_path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(
            {
                "input": input_path,
                "output": output_path,
                "args": args,
                "kwargs": kwargs,
            }
        )
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as fh:
            fh.write(b"transformed")
        return dict(result)

    return _spy


def _boom(name: str):
    """Build a spy that fails the test if the pass runs (used for default-off)."""

    def _spy(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError(f"{name} must not run when its flag is off")

    return _spy


def _run_stage_compose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    params: ReelForgeParams,
    *,
    tighten_spy=None,
    auto_zoom_spy=None,
    motion_spy=None,
    matte_spy=None,
) -> dict[str, Any]:
    """Run ``stage_compose`` with every side effect stubbed.

    Any pass spy left ``None`` is replaced with a ``_boom`` guard so an
    unexpected invocation fails loudly. Returns a dict capturing what compose was
    called with (``screen``/``avatar``/``audio``/``ass_path``) and the telemetry
    events recorded.
    """
    work = tmp_path
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(work))

    downloaded: list[str] = []

    def _fake_download(key, dest_path, expires=900):  # noqa: ANN001
        downloaded.append(key)
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(b"fake-media")
        return dest_path

    monkeypatch.setattr(reelforge, "_download_from_r2", _fake_download)
    # Avatar/caption re-hydration returns a deterministic local path (no R2).
    monkeypatch.setattr(reelforge, "_ensure_local", lambda path, key, dest: dest)
    # Watermark + b-roll + previews are out of scope: stub to no-ops.
    monkeypatch.setattr(
        reelforge, "_prepare_watermark", lambda job_id, params, work: (None, "", None)
    )
    monkeypatch.setattr(
        reelforge,
        "_apply_broll",
        lambda job_id, params, final_video, aspect, work: final_video,
    )
    monkeypatch.setattr(
        reelforge,
        "_generate_derivatives",
        lambda job_id, final_video, work: {"poster_key": "", "preview_key": ""},
    )
    monkeypatch.setattr(reelforge, "_r2", lambda: _FakeR2())

    # The editing-pass seams. ``tighten`` / ``motion`` / ``matte`` are re-exported
    # FUNCTIONS on the ``editing`` package that the ``_apply_*`` helpers resolve via
    # ``from app.services.editing import <name>`` at call time, so patch them there.
    # ``auto_zoom`` is the exception: the helper imports it via the full submodule
    # path (``from app.services.editing.auto_zoom import auto_zoom``), so its seam is
    # the ``auto_zoom`` attribute ON the submodule.
    monkeypatch.setattr(editing, "tighten", tighten_spy or _boom("tighten"))
    monkeypatch.setattr(
        auto_zoom_module, "auto_zoom", auto_zoom_spy or _boom("auto_zoom")
    )
    monkeypatch.setattr(editing, "motion", motion_spy or _boom("motion"))
    monkeypatch.setattr(editing, "matte", matte_spy or _boom("matte"))

    # Telemetry seam: capture events instead of writing a JobEvent row.
    from app.telemetry import events as telemetry_events

    events: list[dict[str, Any]] = []

    def _fake_record_event(job_id, stage, status, message="", payload=None, **kw):  # noqa: ANN001
        events.append(
            {"stage": stage, "status": status, "message": message, "payload": payload}
        )

    monkeypatch.setattr(telemetry_events, "record_event", _fake_record_event)

    captured: dict[str, Any] = {}

    def _spy_compose(*args, **kwargs):  # noqa: ANN002, ANN003
        captured["screen"] = args[0]
        captured["avatar"] = args[1]
        captured["audio"] = args[2]
        captured["output"] = args[3]
        captured["ass_path"] = kwargs.get("ass_path")
        return args[3]

    monkeypatch.setattr(compose_ffmpeg, "compose_avatar_over_screen", _spy_compose)

    ctx = {
        "audio_key": "jobs/jobE/audio.mp3",
        "audio_duration": 8.0,
        "avatar_video": str(work / "avatar_src.mp4"),
        "avatar_key": "",
        "ass_path": str(work / "captions.ass"),
        "ass_key": "",
    }
    out = reelforge.stage_compose("jobE", params, ctx)
    captured["_result"] = out
    captured["_downloaded"] = downloaded
    captured["_events"] = events
    return captured


# Result envelopes that mirror each pass's real contract (applied=True).
def _zoom_result(**over: Any) -> dict[str, Any]:
    base = {
        "original_s": 10.0,
        "output_s": 10.0,  # duration-preserving
        "zoom_count": 2,
        "moments": [(1.0, 1.2, 1.25), (5.0, 1.2, 1.25)],
        "applied": True,
    }
    base.update(over)
    return base


def _motion_result(**over: Any) -> dict[str, Any]:
    base = {
        "applied": True,
        "preset": "ken_burns",
        "original_s": 10.0,
        "output_s": 10.0,  # duration-preserving
    }
    base.update(over)
    return base


def _matte_result(**over: Any) -> dict[str, Any]:
    base = {
        "applied": True,
        "mode": "replace",
        "original_s": 8.0,
        "output_s": 8.0,
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# auto_zoom — routes the screen recording through the zoom pass
# --------------------------------------------------------------------------- #
def test_auto_zoom_true_routes_screen_through_auto_zoom(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When enabled, auto_zoom runs on the screen recording and its output composes."""
    calls: list[dict[str, Any]] = []
    captured = _run_stage_compose(
        monkeypatch,
        tmp_path,
        _params(auto_zoom=True),
        auto_zoom_spy=_writing_spy(calls, _zoom_result()),
    )

    assert len(calls) == 1
    assert calls[0]["input"] == str(tmp_path / "screen.mp4")
    assert calls[0]["output"] == str(tmp_path / "screen_zoom.mp4")
    # Compose received the ZOOMED file, not the raw screen recording.
    assert captured["screen"] == str(tmp_path / "screen_zoom.mp4")

    zoom_events = [e for e in captured["_events"] if e["status"] == "auto_zoom"]
    assert len(zoom_events) == 1
    assert zoom_events[0]["stage"] == "compose"
    assert zoom_events[0]["payload"]["zoom_count"] == 2
    assert zoom_events[0]["payload"]["applied"] is True


def test_auto_zoom_applied_false_keeps_original_screen(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A no-op auto_zoom (applied=False) still runs but composes the ORIGINAL file."""
    calls: list[dict[str, Any]] = []
    captured = _run_stage_compose(
        monkeypatch,
        tmp_path,
        _params(auto_zoom=True),
        auto_zoom_spy=_writing_spy(
            calls, _zoom_result(applied=False, zoom_count=0, moments=[])
        ),
    )

    assert len(calls) == 1
    assert captured["screen"] == str(tmp_path / "screen.mp4")
    zoom_events = [e for e in captured["_events"] if e["status"] == "auto_zoom"]
    assert len(zoom_events) == 1
    assert zoom_events[0]["payload"]["applied"] is False


# --------------------------------------------------------------------------- #
# camera_motion — routes the screen recording through the motion pass
# --------------------------------------------------------------------------- #
def test_camera_motion_routes_screen_through_motion(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A named preset runs motion on the screen recording and composes its output."""
    calls: list[dict[str, Any]] = []
    captured = _run_stage_compose(
        monkeypatch,
        tmp_path,
        _params(camera_motion="push_in"),
        motion_spy=_writing_spy(calls, _motion_result(preset="push_in")),
    )

    assert len(calls) == 1
    assert calls[0]["input"] == str(tmp_path / "screen.mp4")
    assert calls[0]["output"] == str(tmp_path / "screen_motion.mp4")
    # The preset is forwarded positionally as the third arg.
    assert calls[0]["args"][0] == "push_in"
    # ``aspect`` is forwarded for API symmetry/logging.
    assert calls[0]["kwargs"].get("aspect") == _params().aspect
    assert captured["screen"] == str(tmp_path / "screen_motion.mp4")

    motion_events = [e for e in captured["_events"] if e["status"] == "motion"]
    assert len(motion_events) == 1
    assert motion_events[0]["payload"]["preset"] == "push_in"
    assert motion_events[0]["payload"]["applied"] is True


def test_camera_motion_none_never_calls_motion(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``camera_motion='none'`` (the default) is a no-op: motion is never called."""
    captured = _run_stage_compose(
        monkeypatch, tmp_path, _params(camera_motion="none")
    )
    assert captured["screen"] == str(tmp_path / "screen.mp4")
    assert not any(e["status"] == "motion" for e in captured["_events"])
    assert _params().camera_motion == "none"


# --------------------------------------------------------------------------- #
# remove_bg — routes the AVATAR clip through the matting pass
# --------------------------------------------------------------------------- #
def test_remove_bg_routes_avatar_through_matte(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When enabled, matte runs on the AVATAR clip and its output composes."""
    calls: list[dict[str, Any]] = []
    captured = _run_stage_compose(
        monkeypatch,
        tmp_path,
        _params(remove_bg=True),
        matte_spy=_writing_spy(calls, _matte_result()),
    )

    assert len(calls) == 1
    # Matting operates on the AVATAR, not the screen recording.
    assert calls[0]["input"] == str(tmp_path / "avatar.mp4")
    assert calls[0]["output"] == str(tmp_path / "avatar_matte.mp4")
    # 'replace' mode + chroma green so the existing compose chromakey keys it.
    assert calls[0]["kwargs"].get("mode") == "replace"
    assert calls[0]["kwargs"].get("bg_key") == "0x00FF00"
    # Compose received the MATTED avatar; the screen is untouched.
    assert captured["avatar"] == str(tmp_path / "avatar_matte.mp4")
    assert captured["screen"] == str(tmp_path / "screen.mp4")

    matte_events = [e for e in captured["_events"] if e["status"] == "matte"]
    assert len(matte_events) == 1
    assert matte_events[0]["payload"]["mode"] == "replace"
    assert matte_events[0]["payload"]["applied"] is True


def test_remove_bg_applied_false_keeps_original_avatar(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A degraded matte (applied=False, e.g. rembg absent) composes the RAW avatar."""
    calls: list[dict[str, Any]] = []
    captured = _run_stage_compose(
        monkeypatch,
        tmp_path,
        _params(remove_bg=True),
        matte_spy=_writing_spy(calls, _matte_result(applied=False)),
    )

    assert len(calls) == 1
    # applied=False => compose falls back to the existing chromakey path (raw avatar).
    assert captured["avatar"] == str(tmp_path / "avatar.mp4")
    matte_events = [e for e in captured["_events"] if e["status"] == "matte"]
    assert matte_events[0]["payload"]["applied"] is False


# --------------------------------------------------------------------------- #
# Ordering — screen passes chain tighten -> auto_zoom -> motion
# --------------------------------------------------------------------------- #
def test_screen_passes_chain_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """With all screen flags on, each pass feeds the next and compose gets the last."""
    tighten_calls: list[dict[str, Any]] = []
    zoom_calls: list[dict[str, Any]] = []
    motion_calls: list[dict[str, Any]] = []

    tighten_result = {
        "original_s": 10.0,
        "tightened_s": 9.0,
        "removed_s": 1.0,
        "segments": [(0.0, 9.0)],
        "applied": True,
    }

    captured = _run_stage_compose(
        monkeypatch,
        tmp_path,
        # ``ken_burns`` is a legacy pre-compose motion preset (owned by the editing
        # pass); catalog moves like ``whip_pan`` now render at the compose stage
        # instead, so a legacy preset is what exercises this pre-compose chain.
        _params(auto_tighten=True, auto_zoom=True, camera_motion="ken_burns"),
        tighten_spy=_writing_spy(tighten_calls, tighten_result),
        auto_zoom_spy=_writing_spy(zoom_calls, _zoom_result()),
        motion_spy=_writing_spy(motion_calls, _motion_result(preset="ken_burns")),
    )

    # tighten consumed the raw screen; zoom consumed tighten's output; motion
    # consumed zoom's output; compose received motion's output.
    assert tighten_calls[0]["input"] == str(tmp_path / "screen.mp4")
    assert tighten_calls[0]["output"] == str(tmp_path / "screen_tight.mp4")
    assert zoom_calls[0]["input"] == str(tmp_path / "screen_tight.mp4")
    assert zoom_calls[0]["output"] == str(tmp_path / "screen_zoom.mp4")
    assert motion_calls[0]["input"] == str(tmp_path / "screen_zoom.mp4")
    assert motion_calls[0]["output"] == str(tmp_path / "screen_motion.mp4")
    assert captured["screen"] == str(tmp_path / "screen_motion.mp4")


# --------------------------------------------------------------------------- #
# Default-off — the compose path is byte-for-byte unchanged
# --------------------------------------------------------------------------- #
def test_all_flags_default_off_calls_no_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """With every flag at its default, NO editing pass runs; compose uses raw inputs."""
    # All spies default to the ``_boom`` guard, so any invocation fails the test.
    captured = _run_stage_compose(monkeypatch, tmp_path, _params())

    assert captured["screen"] == str(tmp_path / "screen.mp4")
    assert captured["avatar"] == str(tmp_path / "avatar.mp4")
    # No editing telemetry was recorded.
    statuses = {e["status"] for e in captured["_events"]}
    assert not statuses & {"tighten", "auto_zoom", "motion", "matte"}
    # Defaults expose the flags as off/none.
    p = _params()
    assert p.auto_zoom is False
    assert p.camera_motion == "none"
    assert p.remove_bg is False


# --------------------------------------------------------------------------- #
# Golden-style invariant: the voiceover/caption timeline is independent of every
# polish pass (caption-drift gate is unaffected with all flags on).
# --------------------------------------------------------------------------- #
def test_polish_passes_leave_voiceover_and_captions_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """All polish flags on vs off yields IDENTICAL audio + caption inputs to compose.

    The polish passes only swap the background screen / avatar inputs; the
    voiceover audio and caption ``.ass`` (the single-authority ElevenLabs/whisper
    timeline) are never touched — the wiring-level guarantee behind the golden
    caption-drift (<=50ms) gate staying green with every flag on.
    """
    on = _run_stage_compose(
        monkeypatch,
        tmp_path / "on",
        _params(auto_zoom=True, camera_motion="ken_burns", remove_bg=True),
        auto_zoom_spy=_writing_spy([], _zoom_result()),
        motion_spy=_writing_spy([], _motion_result()),
        matte_spy=_writing_spy([], _matte_result()),
    )
    off = _run_stage_compose(monkeypatch, tmp_path / "off", _params())

    # Background/avatar inputs differ (polished vs raw)...
    assert os.path.basename(on["screen"]) == "screen_motion.mp4"
    assert os.path.basename(on["avatar"]) == "avatar_matte.mp4"
    assert os.path.basename(off["screen"]) == "screen.mp4"
    assert os.path.basename(off["avatar"]) == "avatar.mp4"

    # ...but the voiceover audio + caption artifacts are IDENTICAL relative to
    # their work dir: the polish passes never swap the audio/caption timeline.
    assert os.path.basename(on["audio"]) == os.path.basename(off["audio"]) == "audio.mp3"
    assert (
        os.path.basename(on["ass_path"])
        == os.path.basename(off["ass_path"])
        == "captions.ass"
    )
    # The voiceover audio was downloaded from the same key in both runs.
    assert "jobs/jobE/audio.mp3" in on["_downloaded"]
    assert "jobs/jobE/audio.mp3" in off["_downloaded"]
