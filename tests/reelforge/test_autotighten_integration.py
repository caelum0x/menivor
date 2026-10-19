"""Integration tests for the opt-in ``auto_tighten`` compose PRE-step.

These verify the wiring landed by the Integrate layer — NOT the silence_cut
algorithm itself (that is covered by ``test_silence_cut.py``):

  * ``auto_tighten=True`` routes the downloaded SCREEN RECORDING through
    :func:`app.services.editing.tighten` (asserted via the mockable seam) BEFORE
    the compose smart-handling, records a ``JobEvent`` telemetry row, and the
    stage still completes — handing the *tightened* file to compose.
  * ``auto_tighten=False`` (the default) leaves the compose path unchanged:
    ``tighten`` is NEVER called and the ORIGINAL screen recording reaches
    compose byte-for-byte.
  * A golden-style invariant: tightening the background NEVER touches the
    voiceover/caption timeline. The audio (voiceover) and the ``.ass`` caption
    artifact handed to compose are identical whether or not auto_tighten ran, so
    the caption-drift gate is unaffected (the timeline is the single source of
    truth and is independent of the tightened background).

All I/O (R2 download/upload, ffmpeg compose, the tighten pass, telemetry) is
monkeypatched, so these tests never touch the network, ffmpeg or a database.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.services import editing, reelforge
from app.services.compose import compose_ffmpeg
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
        "screen_recording_key": "jobs/jobT/screen.mp4",
    }
    base.update(over)
    return ReelForgeParams(**base)


def _run_stage_compose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    params: ReelForgeParams,
    *,
    tighten_spy,
) -> dict[str, Any]:
    """Run ``stage_compose`` with every side effect stubbed.

    Returns a dict capturing what compose was called with (``screen``/``audio``/
    ``ass_path``), the ordered list of ``tighten`` invocations, and the telemetry
    events recorded — so a caller can assert on the auto_tighten wiring.
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
    # Captions re-hydration + avatar re-hydration return a local path (no R2).
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

    # The auto_tighten seam: patch the module-level ``tighten`` that
    # ``_apply_auto_tighten`` resolves via ``from app.services.editing import
    # tighten`` at call time.
    monkeypatch.setattr(editing, "tighten", tighten_spy)

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
        "audio_key": "jobs/jobT/audio.mp3",
        "avatar_video": str(work / "avatar_src.mp4"),
        "avatar_key": "",
        "ass_path": str(work / "captions.ass"),
        "ass_key": "",
    }
    out = reelforge.stage_compose("jobT", params, ctx)
    captured["_result"] = out
    captured["_downloaded"] = downloaded
    captured["_events"] = events
    return captured


# --------------------------------------------------------------------------- #
# auto_tighten=True — routes the screen recording through tighten
# --------------------------------------------------------------------------- #
def test_auto_tighten_true_routes_screen_through_tighten(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When enabled, tighten runs on the screen recording and its output composes."""
    calls: list[dict[str, Any]] = []

    def _tighten_spy(input_path, output_path, *, mode="auto", **kw):  # noqa: ANN001
        calls.append({"input": input_path, "output": output_path, "mode": mode})
        # A real tighten always writes the output; simulate a cut being applied.
        with open(output_path, "wb") as fh:
            fh.write(b"tightened")
        return {
            "original_s": 10.0,
            "tightened_s": 7.0,
            "removed_s": 3.0,
            "segments": [(0.0, 4.0), (6.0, 9.0)],
            "applied": True,
        }

    captured = _run_stage_compose(
        monkeypatch, tmp_path, _params(auto_tighten=True), tighten_spy=_tighten_spy
    )

    # tighten was invoked exactly once on the downloaded screen recording.
    assert len(calls) == 1
    assert calls[0]["input"] == str(tmp_path / "screen.mp4")
    assert calls[0]["output"] == str(tmp_path / "screen_tight.mp4")
    assert calls[0]["mode"] == "auto"

    # Compose received the TIGHTENED file (not the raw screen recording).
    assert captured["screen"] == str(tmp_path / "screen_tight.mp4")

    # The stage completed and produced the usual final artifact.
    assert captured["_result"]["final_key"] == "jobs/jobT/final.mp4"

    # A telemetry JobEvent recorded the removed_s / applied result.
    tighten_events = [e for e in captured["_events"] if e["status"] == "tighten"]
    assert len(tighten_events) == 1
    assert tighten_events[0]["stage"] == "compose"
    assert tighten_events[0]["payload"]["removed_s"] == 3.0
    assert tighten_events[0]["payload"]["applied"] is True


def test_auto_tighten_applied_false_keeps_original_screen(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A no-op tighten (applied=False) still runs but composes the ORIGINAL file."""
    calls: list[str] = []

    def _tighten_noop(input_path, output_path, *, mode="auto", **kw):  # noqa: ANN001
        calls.append(input_path)
        # Degrade-safe contract: the output is written (byte copy) but applied
        # is False because nothing removable was found.
        with open(output_path, "wb") as fh:
            fh.write(b"copy")
        return {
            "original_s": 10.0,
            "tightened_s": 10.0,
            "removed_s": 0.0,
            "segments": [(0.0, 10.0)],
            "applied": False,
        }

    captured = _run_stage_compose(
        monkeypatch, tmp_path, _params(auto_tighten=True), tighten_spy=_tighten_noop
    )

    # tighten was consulted, but with nothing removed compose uses the ORIGINAL.
    assert len(calls) == 1
    assert captured["screen"] == str(tmp_path / "screen.mp4")

    # Telemetry still recorded the (applied=False) outcome.
    tighten_events = [e for e in captured["_events"] if e["status"] == "tighten"]
    assert len(tighten_events) == 1
    assert tighten_events[0]["payload"]["applied"] is False


# --------------------------------------------------------------------------- #
# auto_tighten=False (default) — the compose path is unchanged
# --------------------------------------------------------------------------- #
def test_auto_tighten_default_off_never_calls_tighten(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """With the flag off (default) tighten is NEVER called; compose uses the raw file."""

    def _tighten_must_not_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("tighten must not run when auto_tighten is off")

    captured = _run_stage_compose(
        monkeypatch, tmp_path, _params(), tighten_spy=_tighten_must_not_run
    )

    # The raw screen recording reached compose unchanged.
    assert captured["screen"] == str(tmp_path / "screen.mp4")
    # No auto_tighten telemetry was recorded.
    assert not any(e["status"] == "tighten" for e in captured["_events"])
    # Default params expose the flag as False.
    assert _params().auto_tighten is False


# --------------------------------------------------------------------------- #
# Golden-style invariant: the voiceover/caption timeline is independent of the
# tightened background (caption-drift gate is unaffected).
# --------------------------------------------------------------------------- #
def test_auto_tighten_leaves_voiceover_and_captions_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Tightening the background does not alter the audio / caption inputs.

    The final reel duration is governed downstream by the script/TTS speed-ramp,
    and the caption ``.ass`` + voiceover audio are the single source of truth —
    so the exact same audio + caption artifacts must reach compose whether or not
    auto_tighten ran. This is the wiring-level guarantee behind the golden
    caption-drift (<=50ms) gate staying green with auto_tighten on.
    """

    def _tighten_spy(input_path, output_path, *, mode="auto", **kw):  # noqa: ANN001
        with open(output_path, "wb") as fh:
            fh.write(b"tightened")
        return {
            "original_s": 10.0,
            "tightened_s": 6.0,
            "removed_s": 4.0,
            "segments": [(0.0, 6.0)],
            "applied": True,
        }

    def _tighten_off(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("tighten must not run when auto_tighten is off")

    on = _run_stage_compose(
        monkeypatch,
        tmp_path / "on",
        _params(auto_tighten=True),
        tighten_spy=_tighten_spy,
    )
    off = _run_stage_compose(
        monkeypatch,
        tmp_path / "off",
        _params(auto_tighten=False),
        tighten_spy=_tighten_off,
    )

    # The background screen input differs (tightened vs raw)...
    assert os.path.basename(on["screen"]) == "screen_tight.mp4"
    assert os.path.basename(off["screen"]) == "screen.mp4"

    # ...but the voiceover audio and caption artifacts are IDENTICAL relative to
    # their work dir: auto_tighten only swaps the screen input, never the
    # audio/caption timeline.
    assert os.path.basename(on["audio"]) == os.path.basename(off["audio"]) == "audio.mp3"
    assert (
        os.path.basename(on["ass_path"])
        == os.path.basename(off["ass_path"])
        == "captions.ass"
    )
    # The voiceover audio was downloaded from the same key in both runs.
    assert "jobs/jobT/audio.mp3" in on["_downloaded"]
    assert "jobs/jobT/audio.mp3" in off["_downloaded"]
