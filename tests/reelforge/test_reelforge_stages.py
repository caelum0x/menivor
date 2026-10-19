"""Unit tests for ReelForge stage transforms (app/services/reelforge.py).

These cover the three timing/telemetry invariants that were regressions:

  * stage_tts fails fast when the ElevenLabs alignment yields no timing data,
    instead of probing the file as a SECOND timing authority (§8).
  * stage_avatar records a ``JobEvent(stage='avatar', status='warning')`` AND
    fails the stage (retryable ``ReelForgeStageError``) when the render duration
    drifts beyond ±0.15s (§5 Stage-3 / §8); within tolerance it passes cleanly.
  * stage_avatar assigns ``avatar_key`` ONLY after a successful R2 upload, so a
    failed re-host leaves the key empty and keeps the local path (no ghost key).

All external services (voice.tts, the avatar provider, R2, telemetry) are
monkeypatched, so these tests never touch the network, ffmpeg or a database.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services import reelforge
from app.services.reelforge import ReelForgeParams, ReelForgeStageError


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _FakeSubMaker:
    def __init__(self) -> None:
        self.words: list[Any] = []


class _FakeR2:
    """Records upload_file calls; optionally raises to simulate R2 failure."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.uploads: list[tuple[str, str, str]] = []

    def upload_file(self, local_path: str, key: str, content_type: str) -> str:
        self.uploads.append((local_path, key, content_type))
        if self.fail:
            raise RuntimeError("simulated R2 outage")
        return f"https://cdn.example/{key}"


class _FakeProvider:
    def __init__(self, result: dict | None) -> None:
        self._result = result

    def is_enabled(self) -> bool:
        return True

    def list_avatars(self) -> list[dict]:
        return []

    def generate_avatar(self, audio_url, avatar_id, **kwargs):  # noqa: ANN001
        return self._result


def _params(**over: Any) -> ReelForgeParams:
    base: dict[str, Any] = {
        "video_subject": "demo",
        "voice_name": "elevenlabs:abc",
        "avatar_id": "av123",
    }
    base.update(over)
    return ReelForgeParams(**base)


# --------------------------------------------------------------------------- #
# Multi-language dubbing — stage_script translate path + script persistence
# --------------------------------------------------------------------------- #
def _patch_set_script(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Capture JobRepository.set_script(job_id, script) calls; no real DB.

    Both the session context manager and the repository are stubbed so
    stage_script's best-effort persistence records the call without touching a
    database. Returns the list of ``(job_id, script)`` tuples that were set.
    """
    import contextlib

    from app.models.db import base as db_base
    from app.models.db import repositories as repos

    recorded: list[tuple[str, str]] = []

    @contextlib.contextmanager
    def _fake_get_session():  # noqa: ANN202
        yield object()  # a dummy session; the repo below ignores it

    class _FakeJobRepo:
        def __init__(self, session: Any) -> None:  # noqa: ANN001
            self._session = session

        def set_script(self, job_id: str, script: str):  # noqa: ANN201
            recorded.append((job_id, script))
            return None

    monkeypatch.setattr(db_base, "get_session", _fake_get_session)
    monkeypatch.setattr(repos, "JobRepository", _FakeJobRepo)
    return recorded


def test_stage_script_translates_source_and_skips_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When translate_source_script is set, stage_script must TRANSLATE it into
    # params.language (via translate.translate_script) and never touch the
    # fresh-generation path. The resulting script is persisted to the Job.
    from app.services import translate as translate_mod

    translate_calls: list[tuple[str, str]] = []

    def _fake_translate(script, target_language, app_config=None):  # noqa: ANN001
        translate_calls.append((script, target_language))
        return "Merhaba dunya"

    monkeypatch.setattr(translate_mod, "translate_script", _fake_translate)

    # Generation must NOT run on the dubbing path.
    from app.services.script import ugc as ugc_mod

    def _boom_generate(**kwargs):  # noqa: ANN003
        raise AssertionError("generation must not run when translating a source")

    monkeypatch.setattr(ugc_mod, "generate_ugc_script", _boom_generate)

    recorded = _patch_set_script(monkeypatch)

    out = reelforge.stage_script(
        "jobDub",
        _params(
            video_subject="ignored on dub",
            translate_source_script="Hello world",
            language="tr",
        ),
        {},
    )

    assert out == {"script": "Merhaba dunya"}
    assert translate_calls == [("Hello world", "tr")]
    # The translated script is persisted to the Job (best-effort).
    assert recorded == [("jobDub", "Merhaba dunya")]


def test_stage_script_fails_cleanly_when_translation_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # translate_script returns None (empty/unsupported/failed) -> typed stage
    # error, and nothing is persisted.
    from app.services import translate as translate_mod

    monkeypatch.setattr(
        translate_mod, "translate_script", lambda *a, **k: None  # noqa: ANN002, ANN003
    )
    recorded = _patch_set_script(monkeypatch)

    with pytest.raises(ReelForgeStageError) as exc:
        reelforge.stage_script(
            "jobDubFail",
            _params(translate_source_script="Hello world", language="tr"),
            {},
        )

    assert exc.value.stage == "script"
    assert recorded == []


def test_stage_script_generation_path_persists_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No translate_source_script + no manual script -> generate, then persist.
    from app.services.script import ugc as ugc_mod

    monkeypatch.setattr(
        ugc_mod,
        "generate_ugc_script",
        lambda **kwargs: {"full_text": "  fresh script  "},  # noqa: ANN003
    )
    recorded = _patch_set_script(monkeypatch)

    out = reelforge.stage_script("jobGen", _params(), {})

    assert out == {"script": "fresh script"}
    assert recorded == [("jobGen", "fresh script")]


def test_stage_script_persistence_failure_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A persistence error must NEVER fail the script stage.
    from app.models.db import base as db_base
    from app.services.script import ugc as ugc_mod

    monkeypatch.setattr(
        ugc_mod,
        "generate_ugc_script",
        lambda **kwargs: {"full_text": "resilient script"},  # noqa: ANN003
    )

    def _boom_session():  # noqa: ANN202
        raise RuntimeError("no database configured")

    monkeypatch.setattr(db_base, "get_session", _boom_session)

    out = reelforge.stage_script("jobResilient", _params(), {})
    assert out == {"script": "resilient script"}


def test_reelforge_params_translate_source_script_default() -> None:
    p = _params()
    assert p.translate_source_script == ""

    p2 = _params(translate_source_script="Hello world")
    assert p2.translate_source_script == "Hello world"


# --------------------------------------------------------------------------- #
# LOW #1 — stage_tts fails fast on empty alignment (no second timing authority)
# --------------------------------------------------------------------------- #
def test_stage_tts_fails_fast_when_alignment_has_no_timings(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app.services import voice

    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))

    def _fake_tts(*, text, voice_name, voice_rate, voice_file):  # noqa: ANN001
        with open(voice_file, "wb") as fh:
            fh.write(b"ID3 fake audio")
        return _FakeSubMaker()

    probe_calls: list[Any] = []

    def _fake_get_audio_duration(target):  # noqa: ANN001
        probe_calls.append(target)
        # SubMaker carried no offsets -> 0.0; a file path would (wrongly) probe.
        return 0.0

    monkeypatch.setattr(voice, "tts", _fake_tts)
    monkeypatch.setattr(voice, "get_audio_duration", _fake_get_audio_duration)

    with pytest.raises(ReelForgeStageError) as exc:
        reelforge.stage_tts("job1", _params(), {"script": "hello world"})

    assert exc.value.stage == "tts"
    assert "no character timing data" in str(exc.value)
    # It must NOT fall back to probing the file (single timing authority §8):
    # get_audio_duration is called exactly once, and only with the SubMaker.
    assert len(probe_calls) == 1
    assert isinstance(probe_calls[0], _FakeSubMaker)


# --------------------------------------------------------------------------- #
# MEDIUM #2 — stage_avatar records a warning JobEvent on duration drift
# --------------------------------------------------------------------------- #
def _patch_avatar(
    monkeypatch: pytest.MonkeyPatch, result: dict | None, r2: _FakeR2
) -> list[dict]:
    """Wire stage_avatar's provider, R2 and telemetry; return recorded events."""
    from app.domains.reels import premium
    from app.services import avatar as avatar_pkg
    from app.telemetry import events as telemetry_events

    # These jobs hold reserved AI-video credits (the presenter guard passes).
    monkeypatch.setattr(premium, "ai_video_funded", lambda job_id, ctx=None: True)

    monkeypatch.setattr(
        avatar_pkg, "get_avatar_provider", lambda pid: _FakeProvider(result)
    )
    monkeypatch.setattr(reelforge, "_r2", lambda: r2)

    recorded: list[dict] = []

    def _fake_record_event(job_id, stage, status, message="", payload=None):  # noqa: ANN001
        recorded.append(
            {"job_id": job_id, "stage": stage, "status": status, "payload": payload}
        )
        return None

    monkeypatch.setattr(telemetry_events, "record_event", _fake_record_event)
    return recorded


def test_stage_avatar_fails_and_records_warning_on_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # CTO §5 Stage-3: drift beyond ±0.15s must FAIL the stage (retryable), and
    # still record the warning JobEvent for telemetry.
    avatar_file = tmp_path / "avatar.mp4"
    avatar_file.write_bytes(b"fake mp4")
    result = {
        "avatar_video": str(avatar_file),
        "duration": 31.0,  # expected 30.0 -> delta 1.0s > 0.15s
        "avatar_key": "avatars/prehosted.mp4",
    }
    r2 = _FakeR2()
    recorded = _patch_avatar(monkeypatch, result, r2)

    with pytest.raises(ReelForgeStageError) as exc:
        reelforge.stage_avatar(
            "jobX",
            _params(),
            {"audio_url": "https://a/audio.mp3", "audio_duration": 30.0},
        )

    assert exc.value.stage == "avatar"
    assert "drift" in str(exc.value)
    # Telemetry warning still recorded (before the raise).
    assert len(recorded) == 1
    ev = recorded[0]
    assert ev["job_id"] == "jobX"
    assert ev["stage"] == "avatar"
    assert ev["status"] == "warning"
    assert ev["payload"]["expected"] == 30.0
    assert ev["payload"]["actual"] == 31.0
    assert ev["payload"]["tolerance"] == reelforge._AVATAR_DRIFT_TOLERANCE_S
    # The stage fails before any re-host attempt.
    assert r2.uploads == []


def test_stage_avatar_at_drift_boundary_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Exactly at the tolerance passes; strictly beyond it fails. 0.16 > 0.15.
    avatar_file = tmp_path / "avatar.mp4"
    avatar_file.write_bytes(b"fake mp4")
    result = {
        "avatar_video": str(avatar_file),
        "duration": 30.16,  # delta 0.16s > 0.15s
    }
    _patch_avatar(monkeypatch, result, _FakeR2())

    with pytest.raises(ReelForgeStageError):
        reelforge.stage_avatar(
            "jobB",
            _params(),
            {"audio_url": "https://a/audio.mp3", "audio_duration": 30.0},
        )


def test_stage_avatar_exact_tolerance_boundary_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Spec §5 Stage-3 / §8: drift must be STRICTLY < 0.15s, so a delta of exactly
    # the tolerance (0.15s) FAILS the stage. Guards against the ``>`` vs ``>=``
    # boundary regression.
    # 0.30 vs 0.15 is an exactly-representable pair whose float delta equals the
    # 0.15 tolerance to the bit, so this pins the ``>=`` boundary deterministically
    # (a delta landing exactly on the literal fails with ``>=`` but not ``>``).
    expected = reelforge._AVATAR_DRIFT_TOLERANCE_S          # 0.15
    avatar_duration = 2 * reelforge._AVATAR_DRIFT_TOLERANCE_S  # 0.30
    assert abs(avatar_duration - expected) == reelforge._AVATAR_DRIFT_TOLERANCE_S

    avatar_file = tmp_path / "avatar.mp4"
    avatar_file.write_bytes(b"fake mp4")
    result = {
        "avatar_video": str(avatar_file),
        "duration": avatar_duration,  # delta == tolerance exactly
    }
    recorded = _patch_avatar(monkeypatch, result, _FakeR2())

    with pytest.raises(ReelForgeStageError) as exc:
        reelforge.stage_avatar(
            "jobBoundary",
            _params(),
            {"audio_url": "https://a/audio.mp3", "audio_duration": expected},
        )

    assert exc.value.stage == "avatar"
    assert len(recorded) == 1
    assert recorded[0]["payload"]["delta"] == pytest.approx(
        reelforge._AVATAR_DRIFT_TOLERANCE_S
    )


def test_stage_avatar_no_event_within_tolerance(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    avatar_file = tmp_path / "avatar.mp4"
    avatar_file.write_bytes(b"fake mp4")
    result = {
        "avatar_video": str(avatar_file),
        "duration": 30.1,  # delta 0.1s <= 0.15s -> within tolerance, passes
        "avatar_key": "avatars/prehosted.mp4",
    }
    recorded = _patch_avatar(monkeypatch, result, _FakeR2())

    out = reelforge.stage_avatar(
        "jobX", _params(), {"audio_url": "https://a/audio.mp3", "audio_duration": 30.0}
    )
    assert recorded == []
    assert out["avatar_key"] == "avatars/prehosted.mp4"
    assert out["avatar_duration"] == 30.1


# --------------------------------------------------------------------------- #
# LOW #3 — avatar_key set only after a successful upload (no ghost key)
# --------------------------------------------------------------------------- #
def test_stage_avatar_upload_failure_leaves_key_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    avatar_file = tmp_path / "avatar.mp4"
    avatar_file.write_bytes(b"fake mp4")
    result = {"avatar_video": str(avatar_file), "duration": 30.0}  # no avatar_key
    r2 = _FakeR2(fail=True)
    _patch_avatar(monkeypatch, result, r2)

    out = reelforge.stage_avatar(
        "jobY", _params(), {"audio_url": "https://a/audio.mp3", "audio_duration": 30.0}
    )

    # Upload was attempted but failed -> key stays empty, local path preserved.
    assert len(r2.uploads) == 1
    assert out["avatar_key"] == ""
    assert out["avatar_video"] == str(avatar_file)
    # And _ensure_local can still resolve the avatar from the local path alone.
    resolved = reelforge._ensure_local(
        out["avatar_video"], out["avatar_key"], str(tmp_path / "recover.mp4")
    )
    assert resolved == str(avatar_file)


def test_stage_avatar_upload_success_sets_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    avatar_file = tmp_path / "avatar.mp4"
    avatar_file.write_bytes(b"fake mp4")
    result = {"avatar_video": str(avatar_file), "duration": 30.0}  # no avatar_key
    r2 = _FakeR2(fail=False)
    _patch_avatar(monkeypatch, result, r2)

    out = reelforge.stage_avatar(
        "jobZ", _params(), {"audio_url": "https://a/audio.mp3", "audio_duration": 30.0}
    )

    assert out["avatar_key"] == "jobs/jobZ/avatar.mp4"
    assert r2.uploads[0][1] == "jobs/jobZ/avatar.mp4"


# --------------------------------------------------------------------------- #
# MEDIUM #4 — stage_captions withholds ass_key when the R2 upload fails, and
# stage_compose raises a TYPED error (not a raw provider exception) when the
# caption artifact cannot be re-materialized on another worker.
# --------------------------------------------------------------------------- #
def _caption_ctx() -> dict[str, Any]:
    return {"words": [["hi", 0.0, 0.5], ["there", 0.5, 1.0]]}


def test_stage_captions_upload_failure_leaves_key_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # On upload failure the returned ctx must NOT carry an ass_key pointing at a
    # nonexistent R2 object (mirrors the avatar stage's no-ghost-key discipline).
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    r2 = _FakeR2(fail=True)
    monkeypatch.setattr(reelforge, "_r2", lambda: r2)

    out = reelforge.stage_captions("jobCap", _params(), _caption_ctx())

    assert len(r2.uploads) == 1  # upload was attempted
    assert out["ass_key"] == ""  # ...but no ghost key on failure
    assert out["ass_path"] == str(tmp_path / "captions.ass")


def test_stage_captions_upload_success_sets_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    r2 = _FakeR2(fail=False)
    monkeypatch.setattr(reelforge, "_r2", lambda: r2)

    out = reelforge.stage_captions("jobCap", _params(), _caption_ctx())

    assert out["ass_key"] == "jobs/jobCap/captions.ass"
    assert r2.uploads[0][1] == "jobs/jobCap/captions.ass"


def test_stage_compose_missing_caption_artifact_raises_typed_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Simulate the distributed handoff: ctx carries a stale local ass_path (from
    # another worker) with an EMPTY ass_key (upload had failed). _ensure_local
    # can neither find the local file nor recover it from R2. stage_compose must
    # surface a typed ReelForgeStageError, never a raw FileNotFoundError/HTTPError.
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(work))

    # Downloads (screen recording + audio) succeed and produce local files.
    def _fake_download(key, dest_path, expires=900):  # noqa: ANN001
        import os as _os

        _os.makedirs(_os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(b"fake")
        return dest_path

    monkeypatch.setattr(reelforge, "_download_from_r2", _fake_download)

    # The avatar resolves from a local path (same-worker fast path).
    avatar_file = work / "avatar_src.mp4"
    avatar_file.write_bytes(b"fake mp4")

    def _boom_compose(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("compose must not run when captions cannot be built")

    from app.services.compose import compose_ffmpeg

    monkeypatch.setattr(compose_ffmpeg, "compose_avatar_over_screen", _boom_compose)

    ctx = {
        "audio_key": "jobs/jobD/audio.mp3",
        "avatar_video": str(avatar_file),
        "avatar_key": "",
        "ass_path": str(work / "does_not_exist.ass"),  # stale path, not present
        "ass_key": "",  # no R2 key to recover it
    }

    with pytest.raises(ReelForgeStageError) as exc:
        reelforge.stage_compose(
            "jobD", _params(screen_recording_key="jobs/jobD/screen.mp4"), ctx
        )

    assert exc.value.stage == "compose"
    assert "captions" in str(exc.value)


# --------------------------------------------------------------------------- #
# Brand Watermark — stage_compose resolves the effective logo and passes
# watermark_path/position/opacity to compose (best-effort; failures never fatal)
# --------------------------------------------------------------------------- #
def _run_compose_capturing_watermark(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    params: ReelForgeParams,
    *,
    watermark_download_fails: bool = False,
) -> dict[str, Any]:
    """Run stage_compose with all I/O stubbed, returning the compose kwargs.

    Screen/audio/watermark downloads and the avatar re-hydration are faked so no
    network/ffmpeg runs; ``compose_avatar_over_screen`` is replaced with a spy
    that records the kwargs it was called with (never actually encoding). The
    returned dict is that captured kwargs mapping.
    """
    import os as _os

    from app.services.compose import compose_ffmpeg

    work = tmp_path
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(work))

    downloaded_keys: list[str] = []

    def _fake_download(key, dest_path, expires=900):  # noqa: ANN001
        downloaded_keys.append(key)
        # Simulate a failing watermark logo download (best-effort path).
        if watermark_download_fails and dest_path.endswith("watermark.png"):
            raise RuntimeError("simulated watermark download outage")
        _os.makedirs(_os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(b"fake")
        return dest_path

    monkeypatch.setattr(reelforge, "_download_from_r2", _fake_download)
    # Avatar re-hydration returns a local path without touching R2.
    monkeypatch.setattr(
        reelforge, "_ensure_local", lambda path, key, dest: dest
    )
    # Final upload + studio previews are stubbed (out of scope for this test).
    monkeypatch.setattr(reelforge, "_r2", lambda: _FakeR2())
    monkeypatch.setattr(
        reelforge,
        "_generate_derivatives",
        lambda job_id, final_video, work: {"poster_key": "", "preview_key": ""},
    )

    captured: dict[str, Any] = {}

    def _spy_compose(*args, **kwargs):  # noqa: ANN002, ANN003
        captured.update(kwargs)
        captured["_args"] = args
        return args[3]  # output_file

    monkeypatch.setattr(compose_ffmpeg, "compose_avatar_over_screen", _spy_compose)

    ctx = {
        "audio_key": "jobs/jobW/audio.mp3",
        "avatar_video": str(work / "avatar_src.mp4"),
        "avatar_key": "",
    }
    reelforge.stage_compose("jobW", params, ctx)
    captured["_downloaded_keys"] = downloaded_keys
    return captured


def test_stage_compose_applies_brand_watermark(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """An enabled user brand logo is downloaded and passed to compose."""
    monkeypatch.setattr(
        reelforge,
        "_load_user_brand",
        lambda job_id: {
            "logo_key": "brands/logo.png",
            "position": "top_left",
            "opacity": 0.6,
            "enabled": True,
        },
    )

    captured = _run_compose_capturing_watermark(
        monkeypatch, tmp_path, _params(screen_recording_key="jobs/jobW/screen.mp4")
    )

    # The logo was downloaded and passed through as a local path + brand geometry.
    assert "brands/logo.png" in captured["_downloaded_keys"]
    assert captured["watermark_path"] == str(tmp_path / "watermark.png")
    assert captured["watermark_position"] == "top_left"
    assert captured["watermark_opacity"] == 0.6


def test_stage_compose_per_job_key_overrides_brand(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A per-job watermark_key uses that logo directly, never touching the brand."""

    def _brand_must_not_load(job_id):  # noqa: ANN001
        raise AssertionError("brand must not be consulted when watermark_key is set")

    monkeypatch.setattr(reelforge, "_load_user_brand", _brand_must_not_load)

    captured = _run_compose_capturing_watermark(
        monkeypatch,
        tmp_path,
        _params(
            screen_recording_key="jobs/jobW/screen.mp4",
            watermark_key="brands/job-specific.png",
            watermark_position="bottom_left",
            watermark_opacity=0.3,
        ),
    )

    assert "brands/job-specific.png" in captured["_downloaded_keys"]
    assert captured["watermark_path"] == str(tmp_path / "watermark.png")
    assert captured["watermark_position"] == "bottom_left"
    assert captured["watermark_opacity"] == 0.3


def test_stage_compose_watermark_disabled_by_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """watermark_enabled=False disables the overlay even with a brand present."""

    def _brand_must_not_load(job_id):  # noqa: ANN001
        raise AssertionError("brand must not be consulted when the job disables it")

    monkeypatch.setattr(reelforge, "_load_user_brand", _brand_must_not_load)

    captured = _run_compose_capturing_watermark(
        monkeypatch,
        tmp_path,
        _params(
            screen_recording_key="jobs/jobW/screen.mp4", watermark_enabled=False
        ),
    )

    assert captured["watermark_path"] is None
    # No watermark.png was ever downloaded.
    assert not any(k.endswith("watermark.png") for k in captured["_downloaded_keys"])


def test_stage_compose_no_watermark_when_no_brand(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """With no per-job key and no brand, compose runs without a watermark."""
    monkeypatch.setattr(reelforge, "_load_user_brand", lambda job_id: None)

    captured = _run_compose_capturing_watermark(
        monkeypatch, tmp_path, _params(screen_recording_key="jobs/jobW/screen.mp4")
    )

    assert captured["watermark_path"] is None


def test_stage_compose_watermark_download_failure_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A watermark download failure must NOT fail the job — compose without it."""
    monkeypatch.setattr(
        reelforge,
        "_load_user_brand",
        lambda job_id: {
            "logo_key": "brands/logo.png",
            "position": "bottom_right",
            "opacity": 0.85,
            "enabled": True,
        },
    )

    captured = _run_compose_capturing_watermark(
        monkeypatch,
        tmp_path,
        _params(screen_recording_key="jobs/jobW/screen.mp4"),
        watermark_download_fails=True,
    )

    # The download was attempted and failed, but compose still ran (job survives)
    # with no overlay path — the resolved geometry is still forwarded.
    assert "brands/logo.png" in captured["_downloaded_keys"]
    assert captured["watermark_path"] is None
    assert captured["watermark_position"] == "bottom_right"


def test_resolve_watermark_brand_disabled_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A brand with enabled=False yields no watermark (default off honored)."""
    monkeypatch.setattr(
        reelforge,
        "_load_user_brand",
        lambda job_id: {
            "logo_key": "brands/logo.png",
            "position": "top_right",
            "opacity": 0.5,
            "enabled": False,
        },
    )
    assert reelforge._resolve_watermark("jobW", _params()) is None


def test_resolve_watermark_job_reenables_disabled_brand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """watermark_enabled=True forces on a brand whose own flag is False."""
    monkeypatch.setattr(
        reelforge,
        "_load_user_brand",
        lambda job_id: {
            "logo_key": "brands/logo.png",
            "position": "top_right",
            "opacity": 0.5,
            "enabled": False,
        },
    )
    resolved = reelforge._resolve_watermark(
        "jobW", _params(watermark_enabled=True)
    )
    assert resolved == ("brands/logo.png", "top_right", 0.5)


# --------------------------------------------------------------------------- #
# §5 Stage-3 (4d-1) — HeyGen renders on a forced green-screen background
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_heygen_create_avatar_video_forces_green_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.avatar import heygen

    captured: dict[str, Any] = {}

    def _fake_post(url, headers=None, json=None, timeout=None):  # noqa: ANN001
        captured["json"] = json
        return _FakeResp({"data": {"video_id": "vid123"}})

    monkeypatch.setattr(heygen.requests, "post", _fake_post)

    client = heygen.HeyGenClient(api_key="k")
    video_id = client.create_avatar_video(
        character={"type": "avatar", "avatar_id": "av123"},
        voice={"type": "audio", "audio_url": "https://a/audio.mp3"},
    )

    assert video_id == "vid123"
    bg = captured["json"]["video_inputs"][0]["background"]
    assert bg == {"type": "color", "value": "#00FF00"}


def test_heygen_create_avatar_video_respects_explicit_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.avatar import heygen

    captured: dict[str, Any] = {}

    def _fake_post(url, headers=None, json=None, timeout=None):  # noqa: ANN001
        captured["json"] = json
        return _FakeResp({"data": {"video_id": "vid456"}})

    monkeypatch.setattr(heygen.requests, "post", _fake_post)

    override = {"type": "color", "value": "#0000FF"}
    client = heygen.HeyGenClient(api_key="k")
    client.create_avatar_video(
        character={"type": "avatar", "avatar_id": "av123"},
        voice={"type": "audio", "audio_url": "https://a/audio.mp3"},
        background=override,
    )

    assert captured["json"]["video_inputs"][0]["background"] == override


# --------------------------------------------------------------------------- #
# §5a — batch variants: schema validation (bounds) + params plumbing
# --------------------------------------------------------------------------- #
def test_job_create_request_variants_default_and_tos_flag() -> None:
    from app.models.schema import JobCreateRequest

    req = JobCreateRequest()
    assert req.variants == 1  # backward-compatible single-job default
    assert req.tos_disclosure is False


@pytest.mark.parametrize("variants", [1, 2, 3])
def test_job_create_request_accepts_variants_in_range(variants: int) -> None:
    from app.models.schema import JobCreateRequest

    req = JobCreateRequest(variants=variants, tos_disclosure=True)
    assert req.variants == variants
    assert req.tos_disclosure is True


@pytest.mark.parametrize("variants", [0, 4, 10, -1])
def test_job_create_request_rejects_out_of_range_variants(variants: int) -> None:
    import pydantic

    from app.models.schema import JobCreateRequest

    with pytest.raises(pydantic.ValidationError):
        JobCreateRequest(variants=variants)


def test_job_data_job_ids_optional_and_backward_compatible() -> None:
    from app.models.schema import JobData

    # variants == 1: single job_id, job_ids omitted entirely.
    single = JobData(job_id="job-1", state=4)
    assert single.job_ids is None
    assert single.job_id == "job-1"

    # variants > 1: every spawned id in job_ids, job_id keeps the first for
    # backward compatibility.
    batch = JobData(job_id="job-1", state=4, job_ids=["job-1", "job-2", "job-3"])
    assert batch.job_ids == ["job-1", "job-2", "job-3"]
    assert batch.job_id == "job-1"


def test_reelforge_params_variants_and_tos_defaults() -> None:
    p = _params()
    assert p.variants == 1
    assert p.tos_disclosure is False

    p2 = _params(variants=3, tos_disclosure=True)
    assert p2.variants == 3
    assert p2.tos_disclosure is True


# --------------------------------------------------------------------------- #
# §5d — ToS / AI-disclosure toggle in stage_upload
# --------------------------------------------------------------------------- #
def _patch_cross_post(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture the cross_post_video call args; return the capture dict."""
    from app.services import upload_post

    captured: dict[str, Any] = {}

    def _fake_cross_post(video_path, title, platforms=None, youtube_extra=None):  # noqa: ANN001
        captured["video_path"] = video_path
        captured["title"] = title
        captured["platforms"] = platforms
        captured["youtube_extra"] = youtube_extra
        return {"success": True, "request_id": "req-1", "results": [{"platform": "tiktok"}]}

    monkeypatch.setattr(upload_post, "cross_post_video", _fake_cross_post)
    return captured


def test_stage_upload_marks_synthetic_media_when_tos_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    final = tmp_path / "final.mp4"
    final.write_bytes(b"fake mp4")
    captured = _patch_cross_post(monkeypatch)

    out = reelforge.stage_upload(
        "jobT",
        _params(
            video_subject="green tea benefits",
            platforms=("youtube", "tiktok"),
            tos_disclosure=True,
        ),
        {"final_video": str(final), "final_key": ""},
    )

    assert out["request_id"] == "req-1"
    ye = captured["youtube_extra"]
    # YouTube synthetic-media flag asserted at this layer too.
    assert ye["containsSyntheticMedia"] == "true"
    # Human-readable disclosure note on the YouTube description...
    assert reelforge._AI_DISCLOSURE_NOTE in ye["youtube_description"]
    # ...and on the shared caption used by TikTok/Instagram.
    assert reelforge._AI_DISCLOSURE_NOTE in captured["title"]
    # The clean YouTube title is preserved (disclosure lives in the description).
    assert reelforge._AI_DISCLOSURE_NOTE not in ye["youtube_title"]


def test_stage_upload_leaves_metadata_unchanged_when_tos_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    final = tmp_path / "final.mp4"
    final.write_bytes(b"fake mp4")
    captured = _patch_cross_post(monkeypatch)

    reelforge.stage_upload(
        "jobU",
        _params(
            video_subject="green tea benefits",
            platforms=("youtube", "tiktok"),
            tos_disclosure=False,
        ),
        {"final_video": str(final), "final_key": ""},
    )

    ye = captured["youtube_extra"]
    # Toggle off -> no synthetic-media additions, caption untouched.
    assert "containsSyntheticMedia" not in ye
    assert "youtube_description" not in ye
    assert reelforge._AI_DISCLOSURE_NOTE not in captured["title"]
    assert captured["title"] == "green tea benefits"


# --------------------------------------------------------------------------- #
# §6 — new Creator-Studio params (music_id / webhook_url / webhook_secret) and
# caption_style default. Backward-compatible: defaults preserve behaviour.
# --------------------------------------------------------------------------- #
def test_reelforge_params_studio_field_defaults() -> None:
    p = _params()
    assert p.music_id == ""
    assert p.webhook_url == ""
    assert p.webhook_secret == ""
    # Default caption style resolves to the classic yellow karaoke preset.
    from app.services.captions.presets import DEFAULT_CAPTION_STYLE, get_caption_style

    assert p.caption_style == DEFAULT_CAPTION_STYLE == "karaoke_yellow"
    assert get_caption_style(p.caption_style) is get_caption_style("karaoke_yellow")

    p2 = _params(music_id="lofi", webhook_url="https://h/cb", webhook_secret="s3cr3t")
    assert p2.music_id == "lofi"
    assert p2.webhook_url == "https://h/cb"
    assert p2.webhook_secret == "s3cr3t"


# --------------------------------------------------------------------------- #
# §6 — stage_captions applies the requested caption-style preset
# --------------------------------------------------------------------------- #
def _patch_captions_capture(monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict[str, Any]:
    """Capture write_ass's style arg; stub R2. Returns the capture dict."""
    from app.services.captions import ass_karaoke

    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    monkeypatch.setattr(reelforge, "_r2", lambda: _FakeR2())

    captured: dict[str, Any] = {}

    def _fake_write_ass(path, lines, style=None, upper=False):  # noqa: ANN001
        captured["style"] = style
        captured["path"] = path
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[Script Info]\n")
        return path

    monkeypatch.setattr(ass_karaoke, "write_ass", _fake_write_ass)
    return captured


def test_stage_captions_uses_requested_preset(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app.services.captions.presets import get_caption_style

    captured = _patch_captions_capture(monkeypatch, tmp_path)

    reelforge.stage_captions(
        "jobCapStyle", _params(caption_style="bold_violet"), _caption_ctx()
    )

    assert captured["style"] == get_caption_style("bold_violet")


def test_stage_captions_unknown_style_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app.services.captions.presets import get_caption_style

    captured = _patch_captions_capture(monkeypatch, tmp_path)

    reelforge.stage_captions(
        "jobCapStyle2", _params(caption_style="does-not-exist"), _caption_ctx()
    )

    # Unknown ids resolve to the default preset (not a crash / bare default).
    assert captured["style"] == get_caption_style(None)


# --------------------------------------------------------------------------- #
# §6 — stage_compose: music mixing + best-effort poster/preview derivatives
# --------------------------------------------------------------------------- #
def _patch_compose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    music_path: str | None = None,
    poster_fail: bool = False,
    preview_fail: bool = False,
) -> dict[str, Any]:
    """Wire every collaborator stage_compose touches; return a capture dict."""
    from app.services import preview as preview_mod
    from app.services.compose import compose_ffmpeg

    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(work))

    r2 = _FakeR2()
    monkeypatch.setattr(reelforge, "_r2", lambda: r2)

    def _fake_download(key, dest_path, expires=900):  # noqa: ANN001
        import os as _os

        _os.makedirs(_os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(b"fake")
        return dest_path

    monkeypatch.setattr(reelforge, "_download_from_r2", _fake_download)

    # Avatar resolves from a same-worker local path.
    avatar_file = work / "avatar_src.mp4"
    avatar_file.write_bytes(b"fake mp4")

    capture: dict[str, Any] = {"r2": r2, "avatar_file": str(avatar_file)}

    def _fake_compose(screen, avatar, audio, out, **kwargs):  # noqa: ANN001
        capture["compose_kwargs"] = kwargs
        with open(out, "wb") as fh:
            fh.write(b"final mp4")
        return out

    monkeypatch.setattr(compose_ffmpeg, "compose_avatar_over_screen", _fake_compose)

    # music resolution
    def _fake_get_music_path(music_id):  # noqa: ANN001
        capture["music_id_arg"] = music_id
        return music_path

    from app.services import music as music_mod

    monkeypatch.setattr(music_mod, "get_music_path", _fake_get_music_path)

    def _fake_poster(video_path, out_jpg, at_s=1.0, width=720):  # noqa: ANN001
        if poster_fail:
            raise RuntimeError("poster boom")
        with open(out_jpg, "wb") as fh:
            fh.write(b"jpg")
        return out_jpg

    def _fake_preview(video_path, out_mp4, start_s=0.0, duration_s=5.0):  # noqa: ANN001
        if preview_fail:
            raise RuntimeError("preview boom")
        with open(out_mp4, "wb") as fh:
            fh.write(b"mp4")
        return out_mp4

    monkeypatch.setattr(preview_mod, "generate_poster", _fake_poster)
    monkeypatch.setattr(preview_mod, "generate_preview_clip", _fake_preview)
    return capture


def _compose_ctx() -> dict[str, Any]:
    return {
        "audio_key": "jobs/jobC/audio.mp3",
        "avatar_video": "",  # forces avatar re-use from the patched local file
        "avatar_key": "",
    }


def test_stage_compose_passes_music_path_when_music_id_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    cap = _patch_compose(monkeypatch, tmp_path, music_path="/songs/lofi.mp3")
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]

    out = reelforge.stage_compose(
        "jobC",
        _params(screen_recording_key="jobs/jobC/screen.mp4", music_id="lofi"),
        ctx,
    )

    assert cap["music_id_arg"] == "lofi"
    assert cap["compose_kwargs"]["music_path"] == "/songs/lofi.mp3"
    # Poster + preview generated and uploaded.
    assert out["poster_key"] == "jobs/jobC/poster.jpg"
    assert out["preview_key"] == "jobs/jobC/preview.mp4"
    assert out["final_key"] == "jobs/jobC/final.mp4"


def test_stage_compose_no_music_id_passes_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    cap = _patch_compose(monkeypatch, tmp_path, music_path="/songs/lofi.mp3")
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]

    reelforge.stage_compose(
        "jobC", _params(screen_recording_key="jobs/jobC/screen.mp4"), ctx
    )

    # get_music_path must not even be consulted when music_id is blank.
    assert "music_id_arg" not in cap
    assert cap["compose_kwargs"]["music_path"] is None


def test_stage_compose_preview_failure_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # A preview failure must NOT fail the job: final_key still returned, the
    # failing derivative's key is empty, the other still succeeds.
    cap = _patch_compose(monkeypatch, tmp_path, preview_fail=True)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]

    out = reelforge.stage_compose(
        "jobC", _params(screen_recording_key="jobs/jobC/screen.mp4"), ctx
    )

    assert out["final_key"] == "jobs/jobC/final.mp4"
    assert out["poster_key"] == "jobs/jobC/poster.jpg"  # poster still worked
    assert out["preview_key"] == ""  # preview failed -> no ghost key


def test_stage_compose_poster_failure_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    cap = _patch_compose(monkeypatch, tmp_path, poster_fail=True)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]

    out = reelforge.stage_compose(
        "jobC", _params(screen_recording_key="jobs/jobC/screen.mp4"), ctx
    )

    assert out["final_key"] == "jobs/jobC/final.mp4"
    assert out["poster_key"] == ""  # poster failed -> no ghost key
    assert out["preview_key"] == "jobs/jobC/preview.mp4"  # preview still worked


# --------------------------------------------------------------------------- #
# AI Background Music — generate a custom BGM from params.music_prompt via the
# reused MPT providers and hand it to compose as music_path (best-effort: a
# provider failure composes WITHOUT music and NEVER fails the job).
# --------------------------------------------------------------------------- #
def _patch_music_providers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    elevenlabs_enabled: bool = True,
    sonilo_enabled: bool = False,
    fail_domain: bool = False,
    fail_unexpected: bool = False,
    max_prompt_length: int | None = None,
) -> dict[str, Any]:
    """Monkeypatch the vendored elevenlabs_music/sonilo providers (no network).

    Returns a capture dict recording the ``generate_bgm`` call kwargs so tests can
    assert the exact video_path/duration/prompt that reached the provider.
    """
    from app.domains.reels import premium
    from app.services import elevenlabs_music, sonilo

    cap: dict[str, Any] = {"generate_calls": []}

    # These jobs hold a premium credit for ElevenLabs music (the guard passes).
    monkeypatch.setattr(premium, "premium_music_funded", lambda job_id, ctx=None: True)

    monkeypatch.setattr(elevenlabs_music, "is_enabled", lambda: elevenlabs_enabled)
    monkeypatch.setattr(sonilo, "is_enabled", lambda: sonilo_enabled)
    if max_prompt_length is not None:
        monkeypatch.setattr(elevenlabs_music, "MAX_PROMPT_LENGTH", max_prompt_length)

    def _fake_generate_bgm(*, video_path, output_path, video_duration, prompt):  # noqa: ANN001
        cap["generate_calls"].append(
            {
                "video_path": video_path,
                "output_path": output_path,
                "video_duration": video_duration,
                "prompt": prompt,
            }
        )
        if fail_domain:
            raise elevenlabs_music.ElevenLabsMusicError("simulated provider failure")
        if fail_unexpected:
            raise RuntimeError("simulated unexpected crash")
        with open(output_path, "wb") as fh:
            fh.write(b"fake generated mp3")
        return output_path

    monkeypatch.setattr(elevenlabs_music, "generate_bgm", _fake_generate_bgm)
    # Sonilo must never be invoked in these tests (elevenlabs leads the order).
    def _sonilo_boom(**kwargs):  # noqa: ANN003
        raise AssertionError("sonilo.generate_bgm must not run in this scenario")

    monkeypatch.setattr(sonilo, "generate_bgm", _sonilo_boom)
    return cap


def test_stage_compose_generates_ai_music_and_passes_to_compose(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # A job with music_prompt (and no music_id) must call the provider's
    # generate_bgm and hand the result to compose as music_path.
    cap = _patch_compose(monkeypatch, tmp_path)  # music_path arg unused here
    prov = _patch_music_providers(monkeypatch)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]
    ctx["audio_duration"] = 27.5

    out = reelforge.stage_compose(
        "jobC",
        _params(
            screen_recording_key="jobs/jobC/screen.mp4",
            music_prompt="warm lofi hip hop, mellow piano",
        ),
        ctx,
    )

    # The provider was invoked once with the screen recording + authoritative
    # audio duration + prompt.
    assert len(prov["generate_calls"]) == 1
    call = prov["generate_calls"][0]
    assert call["video_path"].endswith("screen.mp4")
    assert call["video_duration"] == 27.5
    assert call["prompt"] == "warm lofi hip hop, mellow piano"

    # The generated file was handed to compose as music_path...
    music_path = cap["compose_kwargs"]["music_path"]
    assert music_path == call["output_path"]
    assert music_path.endswith("ai-bgm-elevenlabs.mp3")
    # ...and uploaded to R2, whose key is recorded on the stage output.
    assert out["music_key"] == "jobs/jobC/ai-bgm.mp3"
    assert any(key == "jobs/jobC/ai-bgm.mp3" for _, key, _ in cap["r2"].uploads)


def test_stage_compose_music_id_takes_precedence_over_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # When an explicit music_id resolves, the AI provider must NOT be consulted.
    cap = _patch_compose(monkeypatch, tmp_path, music_path="/songs/lofi.mp3")
    prov = _patch_music_providers(monkeypatch)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]
    ctx["audio_duration"] = 20.0

    reelforge.stage_compose(
        "jobC",
        _params(
            screen_recording_key="jobs/jobC/screen.mp4",
            music_id="lofi",
            music_prompt="should be ignored",
        ),
        ctx,
    )

    assert prov["generate_calls"] == []  # AI provider never touched
    assert cap["compose_kwargs"]["music_path"] == "/songs/lofi.mp3"


def test_stage_compose_disabled_provider_composes_without_music(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # No enabled provider -> compose WITHOUT music and DO NOT raise.
    cap = _patch_compose(monkeypatch, tmp_path)
    prov = _patch_music_providers(
        monkeypatch, elevenlabs_enabled=False, sonilo_enabled=False
    )
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]
    ctx["audio_duration"] = 15.0

    out = reelforge.stage_compose(
        "jobC",
        _params(
            screen_recording_key="jobs/jobC/screen.mp4",
            music_prompt="ambient pads",
        ),
        ctx,
    )

    assert prov["generate_calls"] == []  # nothing enabled -> never generated
    assert cap["compose_kwargs"]["music_path"] is None
    assert out["music_key"] == ""
    assert out["final_key"] == "jobs/jobC/final.mp4"  # job still succeeds


def test_stage_compose_failing_provider_composes_without_music(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # The provider's domain error must be swallowed: compose without music, never
    # raising (an AI-music failure never fails the job).
    cap = _patch_compose(monkeypatch, tmp_path)
    prov = _patch_music_providers(monkeypatch, fail_domain=True)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]
    ctx["audio_duration"] = 18.0

    out = reelforge.stage_compose(
        "jobC",
        _params(
            screen_recording_key="jobs/jobC/screen.mp4",
            music_prompt="driving synthwave",
        ),
        ctx,
    )

    assert len(prov["generate_calls"]) == 1  # it was attempted...
    assert cap["compose_kwargs"]["music_path"] is None  # ...but yielded no track
    assert out["music_key"] == ""
    assert out["final_key"] == "jobs/jobC/final.mp4"


def test_stage_compose_unexpected_provider_error_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Even a non-domain exception from the provider must not fail the job.
    cap = _patch_compose(monkeypatch, tmp_path)
    _patch_music_providers(monkeypatch, fail_unexpected=True)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]
    ctx["audio_duration"] = 12.0

    out = reelforge.stage_compose(
        "jobC",
        _params(
            screen_recording_key="jobs/jobC/screen.mp4",
            music_prompt="epic orchestral",
        ),
        ctx,
    )

    assert cap["compose_kwargs"]["music_path"] is None
    assert out["final_key"] == "jobs/jobC/final.mp4"


def test_stage_compose_clamps_prompt_to_provider_max_length(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # A prompt longer than the provider's MAX_PROMPT_LENGTH is clamped before the
    # call (the providers RAISE on over-length prompts, so clamping keeps music).
    cap = _patch_compose(monkeypatch, tmp_path)
    prov = _patch_music_providers(monkeypatch, max_prompt_length=10)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]
    ctx["audio_duration"] = 22.0

    long_prompt = "x" * 250
    reelforge.stage_compose(
        "jobC",
        _params(
            screen_recording_key="jobs/jobC/screen.mp4",
            music_prompt=long_prompt,
        ),
        ctx,
    )

    assert len(prov["generate_calls"]) == 1
    assert prov["generate_calls"][0]["prompt"] == "x" * 10  # clamped to max_len


def test_stage_compose_no_prompt_skips_ai_music(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # With neither music_id nor music_prompt, behavior is unchanged: no provider
    # is consulted and compose receives music_path=None.
    cap = _patch_compose(monkeypatch, tmp_path)
    prov = _patch_music_providers(monkeypatch)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]

    out = reelforge.stage_compose(
        "jobC", _params(screen_recording_key="jobs/jobC/screen.mp4"), ctx
    )

    assert prov["generate_calls"] == []
    assert cap["compose_kwargs"]["music_path"] is None
    assert out["music_key"] == ""


def test_bgm_ai_resolve_provider_picks_first_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import bgm_ai

    _patch_music_providers(monkeypatch, elevenlabs_enabled=False, sonilo_enabled=True)
    provider = bgm_ai.resolve_provider("")
    assert provider is not None
    assert provider.name == "sonilo"


def test_bgm_ai_resolve_provider_explicit_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import bgm_ai

    _patch_music_providers(monkeypatch, elevenlabs_enabled=True, sonilo_enabled=True)
    provider = bgm_ai.resolve_provider("sonilo")
    assert provider is not None and provider.name == "sonilo"
    # An unknown name resolves to None (skip AI music), never raising.
    assert bgm_ai.resolve_provider("does-not-exist") is None
    # A disabled explicit provider resolves to None too.
    _patch_music_providers(monkeypatch, elevenlabs_enabled=False)
    assert bgm_ai.resolve_provider("elevenlabs") is None


def test_reelforge_params_ai_music_defaults() -> None:
    p = _params()
    assert p.music_prompt == ""
    assert p.bgm_provider == ""

    p2 = _params(music_prompt="lofi beats", bgm_provider="sonilo")
    assert p2.music_prompt == "lofi beats"
    assert p2.bgm_provider == "sonilo"


# --------------------------------------------------------------------------- #
# §6 — stage_upload fires the best-effort completion webhook
# --------------------------------------------------------------------------- #
def _patch_webhook(
    monkeypatch: pytest.MonkeyPatch, *, delivered: bool = True
) -> dict[str, Any]:
    """Capture deliver_webhook + telemetry calls; return the capture dict."""
    from app.services import webhooks
    from app.telemetry import events as telemetry_events

    cap: dict[str, Any] = {"calls": [], "events": []}

    def _fake_deliver(url, payload, secret=None, timeout_s=10.0):  # noqa: ANN001
        cap["calls"].append({"url": url, "payload": payload, "secret": secret})
        if delivered:
            return {"delivered": True, "status": 200}
        return {"delivered": False, "status": 500, "error": "boom"}

    def _fake_record_event(job_id, stage, status, message="", payload=None):  # noqa: ANN001
        cap["events"].append({"stage": stage, "status": status})
        return None

    monkeypatch.setattr(webhooks, "deliver_webhook", _fake_deliver)
    monkeypatch.setattr(telemetry_events, "record_event", _fake_record_event)
    return cap


def test_stage_upload_fires_webhook_with_completion_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    final = tmp_path / "final.mp4"
    final.write_bytes(b"fake mp4")
    _patch_cross_post(monkeypatch)
    cap = _patch_webhook(monkeypatch)

    reelforge.stage_upload(
        "jobW",
        _params(
            platforms=("tiktok",),
            webhook_url="https://hooks.example/cb",
            webhook_secret="sig-key",
        ),
        {
            "final_video": str(final),
            "final_key": "jobs/jobW/final.mp4",
            "poster_key": "jobs/jobW/poster.jpg",
            "preview_key": "jobs/jobW/preview.mp4",
        },
    )

    assert len(cap["calls"]) == 1
    call = cap["calls"][0]
    assert call["url"] == "https://hooks.example/cb"
    assert call["secret"] == "sig-key"
    payload = dict(call["payload"])
    # The WolfCut GeneratedClip descriptor rides along on the completion payload
    # (best-effort, with a presigned ``src`` for the final MP4).
    clip = payload.pop("generated_clip")
    assert isinstance(clip, dict) and "src" in clip
    assert payload == {
        "job_id": "jobW",
        "status": "complete",
        "result_key": "jobs/jobW/final.mp4",
        "poster_key": "jobs/jobW/poster.jpg",
        "preview_key": "jobs/jobW/preview.mp4",
    }
    # A JobEvent records the delivery outcome.
    assert {"stage": "webhook", "status": "complete"} in cap["events"]


def test_stage_upload_fires_webhook_even_without_platforms(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # No platforms => cross-post skipped, but the completion webhook still fires.
    cap = _patch_webhook(monkeypatch)

    out = reelforge.stage_upload(
        "jobW2",
        _params(webhook_url="https://hooks.example/cb"),
        {"final_key": "jobs/jobW2/final.mp4"},
    )

    assert out == {"upload_results": [], "request_id": ""}
    assert len(cap["calls"]) == 1
    assert cap["calls"][0]["payload"]["result_key"] == "jobs/jobW2/final.mp4"
    # No secret provided -> passed through as None.
    assert cap["calls"][0]["secret"] is None


def test_stage_upload_no_webhook_when_url_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    cap = _patch_webhook(monkeypatch)

    reelforge.stage_upload(
        "jobW3", _params(), {"final_key": "jobs/jobW3/final.mp4"}
    )

    assert cap["calls"] == []
    assert cap["events"] == []


def test_stage_upload_webhook_failure_records_warning_and_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # A non-delivered webhook must NOT fail the stage; it records a warning event.
    cap = _patch_webhook(monkeypatch, delivered=False)

    out = reelforge.stage_upload(
        "jobW4",
        _params(webhook_url="https://hooks.example/cb"),
        {"final_key": "jobs/jobW4/final.mp4"},
    )

    assert out == {"upload_results": [], "request_id": ""}
    assert len(cap["calls"]) == 1
    assert {"stage": "webhook", "status": "warning"} in cap["events"]


# --------------------------------------------------------------------------- #
# R2 IDOR / BOLA — user-supplied screen_recording_key / watermark_key must not
# reach into ANOTHER creator's per-job artifacts. The guard mirrors the brand
# controller's _verify_logo_ownership: a jobs/<ref>/ key is allowed only when
# <ref> is this job or another job owned by the SAME user; it fails closed.
# --------------------------------------------------------------------------- #
def _patch_job_owners(
    monkeypatch: pytest.MonkeyPatch, owners: dict[str, str]
) -> None:
    """Stub the DB layer so _assert_owned_r2_key resolves ``job_id -> user_id``.

    ``owners`` maps job ids to owning user ids; a job absent from the map
    resolves to ``None`` (unknown), exercising the fail-closed path.
    """
    import contextlib

    from app.models.db import base as db_base
    from app.models.db import repositories as repos

    class _Job:
        def __init__(self, user_id: str) -> None:
            self.user_id = user_id

    @contextlib.contextmanager
    def _fake_get_session():  # noqa: ANN202
        yield object()

    class _FakeJobRepo:
        def __init__(self, session: Any) -> None:  # noqa: ANN001
            self._session = session

        def get(self, job_id: str):  # noqa: ANN201
            uid = owners.get(job_id)
            return _Job(uid) if uid is not None else None

    monkeypatch.setattr(db_base, "get_session", _fake_get_session)
    monkeypatch.setattr(repos, "JobRepository", _FakeJobRepo)


def test_stage_compose_rejects_cross_tenant_screen_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A screen_recording_key pointing at ANOTHER user's job is rejected.

    The IDOR: attacker submits screen_recording_key='jobs/<victim>/final.mp4'.
    stage_compose must raise a typed ReelForgeStageError and NEVER presign or
    download the victim's object.
    """
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    _patch_job_owners(
        monkeypatch, {"attackerJob": "attacker", "victimJob": "victim"}
    )

    downloaded: list[str] = []

    def _spy_download(key, dest_path, expires=900):  # noqa: ANN001
        downloaded.append(key)
        raise AssertionError(f"must not download foreign key {key!r}")

    monkeypatch.setattr(reelforge, "_download_from_r2", _spy_download)

    with pytest.raises(ReelForgeStageError) as exc:
        reelforge.stage_compose(
            "attackerJob",
            _params(screen_recording_key="jobs/victimJob/final.mp4"),
            {"audio_key": "jobs/attackerJob/audio.mp3"},
        )

    assert exc.value.stage == "compose"
    assert "victimJob" in str(exc.value)
    assert downloaded == []  # the victim object was never fetched


def test_stage_compose_allows_same_user_cross_job_screen_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A jobs/<ref>/ key owned by the SAME user is permitted (no false positive)."""
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    _patch_job_owners(monkeypatch, {"jobNew": "creator", "jobOld": "creator"})

    downloaded: list[str] = []

    def _fake_download(key, dest_path, expires=900):  # noqa: ANN001
        import os as _os

        downloaded.append(key)
        _os.makedirs(_os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(b"fake")
        return dest_path

    monkeypatch.setattr(reelforge, "_download_from_r2", _fake_download)
    monkeypatch.setattr(reelforge, "_ensure_local", lambda path, key, dest: dest)
    monkeypatch.setattr(reelforge, "_r2", lambda: _FakeR2())
    monkeypatch.setattr(reelforge, "_load_user_brand", lambda job_id: None)
    monkeypatch.setattr(
        reelforge,
        "_generate_derivatives",
        lambda job_id, final_video, work: {"poster_key": "", "preview_key": ""},
    )

    from app.services.compose import compose_ffmpeg

    monkeypatch.setattr(
        compose_ffmpeg,
        "compose_avatar_over_screen",
        lambda *a, **k: a[3],  # noqa: ANN002, ANN003 - return output_file
    )

    out = reelforge.stage_compose(
        "jobNew",
        _params(screen_recording_key="jobs/jobOld/screen.mp4"),
        {
            "audio_key": "jobs/jobNew/audio.mp3",
            "avatar_video": str(tmp_path / "avatar.mp4"),
            "avatar_key": "",
        },
    )

    assert out["final_key"] == "jobs/jobNew/final.mp4"
    assert "jobs/jobOld/screen.mp4" in downloaded  # same-owner ref allowed


def test_stage_compose_skips_cross_tenant_watermark_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A cross-tenant watermark_key is skipped (best-effort), never leaked.

    The IDOR: attacker sets watermark_key='jobs/<victim>/poster.jpg'. The overlay
    is best-effort, so the guard must skip it (compose without a watermark) and
    the foreign object must NEVER be downloaded.
    """
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    _patch_job_owners(
        monkeypatch, {"attackerJob": "attacker", "victimJob": "victim"}
    )

    downloaded: list[str] = []

    def _fake_download(key, dest_path, expires=900):  # noqa: ANN001
        import os as _os

        downloaded.append(key)
        if _key_is_foreign_poster(key):
            raise AssertionError(f"must not download foreign watermark {key!r}")
        _os.makedirs(_os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(b"fake")
        return dest_path

    def _key_is_foreign_poster(key: str) -> bool:
        return key == "jobs/victimJob/poster.jpg"

    monkeypatch.setattr(reelforge, "_download_from_r2", _fake_download)
    monkeypatch.setattr(reelforge, "_ensure_local", lambda path, key, dest: dest)
    monkeypatch.setattr(reelforge, "_r2", lambda: _FakeR2())
    monkeypatch.setattr(
        reelforge,
        "_generate_derivatives",
        lambda job_id, final_video, work: {"poster_key": "", "preview_key": ""},
    )

    captured: dict[str, Any] = {}

    from app.services.compose import compose_ffmpeg

    def _spy_compose(*args, **kwargs):  # noqa: ANN002, ANN003
        captured.update(kwargs)
        return args[3]

    monkeypatch.setattr(compose_ffmpeg, "compose_avatar_over_screen", _spy_compose)

    out = reelforge.stage_compose(
        "attackerJob",
        _params(
            screen_recording_key="jobs/attackerJob/screen.mp4",
            watermark_key="jobs/victimJob/poster.jpg",
        ),
        {
            "audio_key": "jobs/attackerJob/audio.mp3",
            "avatar_video": str(tmp_path / "avatar.mp4"),
            "avatar_key": "",
        },
    )

    # The job still succeeds, but WITHOUT the foreign watermark, and the victim's
    # poster was never downloaded.
    assert out["final_key"] == "jobs/attackerJob/final.mp4"
    assert captured["watermark_path"] is None
    assert "jobs/victimJob/poster.jpg" not in downloaded


def test_assert_owned_r2_key_allows_upload_namespace() -> None:
    """Non-jobs/ prefixes (client uploads) are user-scoped and always allowed."""
    # Should not raise and must not touch the DB for an uploads/<uuid> key.
    reelforge._assert_owned_r2_key("anyJob", "uploads/deadbeef.mp4")
    reelforge._assert_owned_r2_key("anyJob", "jobs/anyJob/screen.mp4")


# --------------------------------------------------------------------------- #
# AI B-roll cutaways — stage_compose splices a muted intro/outro stock clip
# around the composed reel (best-effort). A client-supplied b-roll key is
# validated by the SAME ownership guard as screen_recording_key/watermark_key;
# a cross-tenant key is skipped, and a concat failure keeps the un-spliced reel
# and NEVER fails the job.
# --------------------------------------------------------------------------- #
def _patch_concat(
    monkeypatch: pytest.MonkeyPatch, *, fail: bool = False
) -> dict[str, Any]:
    """Spy on compose_ffmpeg.concat_with_broll; return recorded call args.

    Records each call's ``main_path``/``output_file``/``intro_path``/``outro_path``
    and (unless ``fail``) writes the output file and returns it — mirroring the
    real helper's ``[intro?][reel][outro?]`` contract without touching ffmpeg.
    """
    from app.services.compose import compose_ffmpeg

    cap: dict[str, Any] = {"calls": []}

    def _fake_concat(
        main_path, output_file, *, intro_path=None, outro_path=None, **kwargs  # noqa: ANN001, ANN003
    ):
        cap["calls"].append(
            {
                "main_path": main_path,
                "output_file": output_file,
                "intro_path": intro_path,
                "outro_path": outro_path,
                "kwargs": kwargs,
            }
        )
        if fail:
            raise RuntimeError("simulated b-roll concat failure")
        with open(output_file, "wb") as fh:
            fh.write(b"spliced mp4")
        return output_file

    monkeypatch.setattr(compose_ffmpeg, "concat_with_broll", _fake_concat)
    return cap


def test_reelforge_params_broll_key_defaults() -> None:
    p = _params()
    assert p.broll_intro_key == ""
    assert p.broll_outro_key == ""

    p2 = _params(
        broll_intro_key="jobs/j/broll/a.mp4", broll_outro_key="jobs/j/broll/b.mp4"
    )
    assert p2.broll_intro_key == "jobs/j/broll/a.mp4"
    assert p2.broll_outro_key == "jobs/j/broll/b.mp4"


def test_stage_compose_no_broll_keys_skips_concat(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Backward-compatible: with neither key set, concat_with_broll is never
    # consulted and the plain reel is uploaded.
    cap = _patch_compose(monkeypatch, tmp_path)
    concat = _patch_concat(monkeypatch)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]

    out = reelforge.stage_compose(
        "jobC", _params(screen_recording_key="jobs/jobC/screen.mp4"), ctx
    )

    assert concat["calls"] == []
    assert out["final_key"] == "jobs/jobC/final.mp4"
    assert cap["r2"].uploads[0][0].endswith("final.mp4")


def test_stage_compose_splices_owned_broll_intro_and_outro(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Owned (same-job) intro + outro keys are downloaded and spliced; the spliced
    # output becomes the final reel that is uploaded + used for derivatives.
    cap = _patch_compose(monkeypatch, tmp_path)
    concat = _patch_concat(monkeypatch)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]

    out = reelforge.stage_compose(
        "jobC",
        _params(
            screen_recording_key="jobs/jobC/screen.mp4",
            broll_intro_key="jobs/jobC/broll/intro.mp4",
            broll_outro_key="jobs/jobC/broll/outro.mp4",
        ),
        ctx,
    )

    assert len(concat["calls"]) == 1
    call = concat["calls"][0]
    assert call["intro_path"].endswith("broll_intro.mp4")
    assert call["outro_path"].endswith("broll_outro.mp4")
    assert call["output_file"].endswith("final_broll.mp4")
    # The spliced output (not the raw reel) is uploaded as the final video.
    assert out["final_key"] == "jobs/jobC/final.mp4"
    first_upload = cap["r2"].uploads[0]
    assert first_upload[1] == "jobs/jobC/final.mp4"
    assert first_upload[0].endswith("final_broll.mp4")


def test_stage_compose_splices_owned_broll_intro_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Only an intro key set -> concat runs with outro_path=None.
    cap = _patch_compose(monkeypatch, tmp_path)
    concat = _patch_concat(monkeypatch)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]

    reelforge.stage_compose(
        "jobC",
        _params(
            screen_recording_key="jobs/jobC/screen.mp4",
            broll_intro_key="jobs/jobC/broll/intro.mp4",
        ),
        ctx,
    )

    assert len(concat["calls"]) == 1
    call = concat["calls"][0]
    assert call["intro_path"].endswith("broll_intro.mp4")
    assert call["outro_path"] is None


def test_stage_compose_broll_concat_failure_keeps_reel(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # A concat failure must NOT fail the job: the un-spliced reel (final.mp4) is
    # uploaded and no exception escapes.
    cap = _patch_compose(monkeypatch, tmp_path)
    concat = _patch_concat(monkeypatch, fail=True)
    ctx = _compose_ctx()
    ctx["avatar_video"] = cap["avatar_file"]

    out = reelforge.stage_compose(
        "jobC",
        _params(
            screen_recording_key="jobs/jobC/screen.mp4",
            broll_intro_key="jobs/jobC/broll/intro.mp4",
        ),
        ctx,
    )

    assert len(concat["calls"]) == 1  # the splice was attempted...
    assert out["final_key"] == "jobs/jobC/final.mp4"  # ...but the job survives
    first_upload = cap["r2"].uploads[0]
    assert first_upload[0].endswith("final.mp4")  # the plain reel was uploaded
    assert not first_upload[0].endswith("final_broll.mp4")


def test_stage_compose_skips_cross_tenant_broll_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A cross-tenant b-roll key is skipped (best-effort), never leaked.

    The IDOR: attacker sets broll_intro_key='jobs/<victim>/final.mp4'. B-roll is
    best-effort, so the guard must skip it (compose without a cutaway) and the
    foreign object must NEVER be downloaded — mirroring the watermark guard.
    """
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    _patch_job_owners(
        monkeypatch, {"attackerJob": "attacker", "victimJob": "victim"}
    )

    downloaded: list[str] = []

    def _fake_download(key, dest_path, expires=900):  # noqa: ANN001
        import os as _os

        downloaded.append(key)
        if key == "jobs/victimJob/final.mp4":
            raise AssertionError(f"must not download foreign b-roll {key!r}")
        _os.makedirs(_os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(b"fake")
        return dest_path

    monkeypatch.setattr(reelforge, "_download_from_r2", _fake_download)
    monkeypatch.setattr(reelforge, "_ensure_local", lambda path, key, dest: dest)
    monkeypatch.setattr(reelforge, "_r2", lambda: _FakeR2())
    monkeypatch.setattr(reelforge, "_load_user_brand", lambda job_id: None)
    monkeypatch.setattr(
        reelforge,
        "_generate_derivatives",
        lambda job_id, final_video, work: {"poster_key": "", "preview_key": ""},
    )
    concat = _patch_concat(monkeypatch)

    from app.services.compose import compose_ffmpeg

    monkeypatch.setattr(
        compose_ffmpeg,
        "compose_avatar_over_screen",
        lambda *a, **k: a[3],  # noqa: ANN002, ANN003 - return output_file
    )

    out = reelforge.stage_compose(
        "attackerJob",
        _params(
            screen_recording_key="jobs/attackerJob/screen.mp4",
            broll_intro_key="jobs/victimJob/final.mp4",
        ),
        {
            "audio_key": "jobs/attackerJob/audio.mp3",
            "avatar_video": str(tmp_path / "avatar.mp4"),
            "avatar_key": "",
        },
    )

    # The job still succeeds, but WITHOUT the foreign cutaway; the victim's object
    # was never downloaded and (no clip resolved) concat was never invoked.
    assert out["final_key"] == "jobs/attackerJob/final.mp4"
    assert concat["calls"] == []
    assert "jobs/victimJob/final.mp4" not in downloaded


def test_stage_compose_mixed_broll_keys_splices_owned_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """One owned + one cross-tenant key: splice the owned clip, skip the foreign one."""
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    _patch_job_owners(
        monkeypatch, {"attackerJob": "attacker", "victimJob": "victim"}
    )

    downloaded: list[str] = []

    def _fake_download(key, dest_path, expires=900):  # noqa: ANN001
        import os as _os

        downloaded.append(key)
        if key == "jobs/victimJob/final.mp4":
            raise AssertionError(f"must not download foreign b-roll {key!r}")
        _os.makedirs(_os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(b"fake")
        return dest_path

    monkeypatch.setattr(reelforge, "_download_from_r2", _fake_download)
    monkeypatch.setattr(reelforge, "_ensure_local", lambda path, key, dest: dest)
    monkeypatch.setattr(reelforge, "_r2", lambda: _FakeR2())
    monkeypatch.setattr(reelforge, "_load_user_brand", lambda job_id: None)
    monkeypatch.setattr(
        reelforge,
        "_generate_derivatives",
        lambda job_id, final_video, work: {"poster_key": "", "preview_key": ""},
    )
    concat = _patch_concat(monkeypatch)

    from app.services.compose import compose_ffmpeg

    def _fake_compose(*a, **k):  # noqa: ANN002, ANN003
        with open(a[3], "wb") as fh:
            fh.write(b"reel")
        return a[3]

    monkeypatch.setattr(
        compose_ffmpeg, "compose_avatar_over_screen", _fake_compose
    )

    reelforge.stage_compose(
        "attackerJob",
        _params(
            screen_recording_key="jobs/attackerJob/screen.mp4",
            broll_intro_key="jobs/victimJob/final.mp4",   # foreign -> skipped
            broll_outro_key="jobs/attackerJob/broll/outro.mp4",  # owned -> spliced
        ),
        {
            "audio_key": "jobs/attackerJob/audio.mp3",
            "avatar_video": str(tmp_path / "avatar.mp4"),
            "avatar_key": "",
        },
    )

    assert "jobs/victimJob/final.mp4" not in downloaded
    assert len(concat["calls"]) == 1
    call = concat["calls"][0]
    assert call["intro_path"] is None  # foreign intro dropped
    assert call["outro_path"].endswith("broll_outro.mp4")  # owned outro spliced


# --------------------------------------------------------------------------- #
# Bring Your Own Voiceover (BYOV) — stage_tts uses the creator's uploaded
# narration instead of TTS. The uploaded audio is the §8 single timing
# authority: faster-whisper WORD timings drive the captions AND the same audio
# drives the avatar duration. The client-supplied voiceover_key is validated by
# the same BOLA/IDOR ownership guard used for screen_recording_key.
# --------------------------------------------------------------------------- #
def test_reelforge_params_voiceover_key_default() -> None:
    assert _params().voiceover_key == ""
    assert _params(voiceover_key="uploads/abc.mp3").voiceover_key == "uploads/abc.mp3"


def _no_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert voice.tts is NEVER called on the BYOV path (no ElevenLabs spend)."""
    from app.services import voice

    def _boom_tts(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("voice.tts must not run when voiceover_key is set")

    monkeypatch.setattr(voice, "tts", _boom_tts)


def _fake_r2_download(recorder: list[str]):  # noqa: ANN202
    """Return a _download_from_r2 stub that writes a file and records the key."""
    import os as _os

    def _dl(key, dest_path, expires=900):  # noqa: ANN001
        recorder.append(key)
        _os.makedirs(_os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(b"fake narration audio")
        return dest_path

    return _dl


def test_stage_tts_byov_uses_uploaded_audio_and_whisper_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # An OWNED voiceover_key skips TTS: the uploaded audio's duration + its
    # faster-whisper WORD timings become the §8 authority, and ctx carries
    # audio_url / words / audio_duration exactly like the TTS path.
    from app.services import transcribe, voice
    from app.services.captions.words import WordTiming

    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    _no_tts(monkeypatch)

    downloaded: list[str] = []
    monkeypatch.setattr(
        reelforge, "_download_from_r2", _fake_r2_download(downloaded)
    )
    r2 = _FakeR2()
    monkeypatch.setattr(reelforge, "_r2", lambda: r2)

    probe_targets: list[Any] = []

    def _fake_duration(target):  # noqa: ANN001
        probe_targets.append(target)
        return 12.5

    monkeypatch.setattr(voice, "get_audio_duration", _fake_duration)

    transcribe_calls: list[tuple[str, Any]] = []

    def _fake_words(audio_path, language=None):  # noqa: ANN001
        transcribe_calls.append((audio_path, language))
        return [WordTiming("hello", 0.0, 0.5), WordTiming("world", 0.5, 1.0)]

    monkeypatch.setattr(transcribe, "transcribe_to_words", _fake_words)

    out = reelforge.stage_tts(
        "job1",
        _params(voiceover_key="jobs/job1/voiceover.mp3", language="en"),
        {},
    )

    # ctx carries the uploaded audio's duration + whisper words + a public URL.
    assert out["audio_duration"] == 12.5
    assert out["words"] == [["hello", 0.0, 0.5], ["world", 0.5, 1.0]]
    assert out["audio_key"] == "jobs/job1/audio.mp3"
    assert out["audio_url"] == "https://cdn.example/jobs/job1/audio.mp3"

    # The voiceover was downloaded and the audio re-hosted for the avatar.
    assert downloaded == ["jobs/job1/voiceover.mp3"]
    assert any(key == "jobs/job1/audio.mp3" for _local, key, _ct in r2.uploads)

    # Duration was probed on the LOCAL audio path (str), not a SubMaker, and the
    # language hint was forwarded to whisper.
    assert probe_targets and isinstance(probe_targets[0], str)
    assert transcribe_calls and transcribe_calls[0][1] == "en"


def test_stage_tts_byov_rejects_cross_tenant_voiceover_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # A voiceover_key pointing at ANOTHER user's job is rejected with a typed
    # ReelForgeStageError BEFORE any download; the foreign object is never fetched
    # and TTS is not run either.
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    _no_tts(monkeypatch)
    _patch_job_owners(
        monkeypatch, {"attackerJob": "attacker", "victimJob": "victim"}
    )

    downloaded: list[str] = []

    def _spy_download(key, dest_path, expires=900):  # noqa: ANN001
        downloaded.append(key)
        raise AssertionError(f"must not download foreign key {key!r}")

    monkeypatch.setattr(reelforge, "_download_from_r2", _spy_download)

    with pytest.raises(ReelForgeStageError) as exc:
        reelforge.stage_tts(
            "attackerJob",
            _params(voiceover_key="jobs/victimJob/audio.mp3"),
            {},
        )

    assert exc.value.stage == "tts"
    assert "victimJob" in str(exc.value)
    assert downloaded == []  # the victim object was never fetched


def test_stage_tts_byov_transcription_failure_still_yields_duration(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Even when transcription (and the SRT fallback) fail, the BYOV stage still
    # produces a usable audio_duration + audio_url so the reel renders; captions
    # may simply be empty (words == []). A transcription problem never fails it.
    from app.services import transcribe, voice

    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    _no_tts(monkeypatch)

    downloaded: list[str] = []
    monkeypatch.setattr(
        reelforge, "_download_from_r2", _fake_r2_download(downloaded)
    )
    r2 = _FakeR2()
    monkeypatch.setattr(reelforge, "_r2", lambda: r2)
    monkeypatch.setattr(voice, "get_audio_duration", lambda target: 8.0)  # noqa: ANN001

    def _boom_words(audio_path, language=None):  # noqa: ANN001
        raise transcribe.TranscriptionError("whisper unavailable")

    def _boom_srt(audio_path, out_srt):  # noqa: ANN001
        raise transcribe.TranscriptionError("subtitle.create failed")

    monkeypatch.setattr(transcribe, "transcribe_to_words", _boom_words)
    monkeypatch.setattr(transcribe, "transcribe_to_srt", _boom_srt)

    out = reelforge.stage_tts(
        "job2",
        _params(voiceover_key="uploads/mine.wav"),
        {},
    )

    assert out["audio_duration"] == 8.0
    assert out["words"] == []  # captions empty, but the reel still renders
    assert out["audio_key"] == "jobs/job2/audio.wav"
    assert out["audio_url"] == "https://cdn.example/jobs/job2/audio.wav"
    assert downloaded == ["uploads/mine.wav"]


# --------------------------------------------------------------------------- #
# Custom Avatar from a Photo — stage_avatar derives the HeyGen character kind
# from the PERSISTED AvatarPreset (config.kind), never a client-supplied field.
# --------------------------------------------------------------------------- #
class _RecordingProvider:
    """Avatar provider that records the kwargs (incl. character_kind) it sees."""

    def __init__(self, result: dict | None) -> None:
        self._result = result
        self.calls: list[dict] = []

    def is_enabled(self) -> bool:
        return True

    def list_avatars(self) -> list[dict]:
        return []

    def generate_avatar(self, audio_url, avatar_id, **kwargs):  # noqa: ANN001
        self.calls.append(kwargs)
        return self._result


class _FakePreset:
    """Minimal stand-in for an ``AvatarPreset`` row (only ``config`` is read)."""

    def __init__(self, config: dict | None) -> None:
        self.config = config


class _FakePresetJob:
    def __init__(self, user_id: str = "user-1") -> None:
        self.user_id = user_id


class _FakePresetQuery:
    """Ignores the filter expressions and returns the pre-seeded preset."""

    def __init__(self, preset: Any) -> None:
        self._preset = preset

    def filter(self, *args: Any, **kwargs: Any) -> "_FakePresetQuery":
        return self

    def first(self) -> Any:
        return self._preset


class _FakePresetSession:
    def __init__(self, preset: Any) -> None:
        self._preset = preset

    def query(self, model: Any) -> _FakePresetQuery:  # noqa: ANN401
        return _FakePresetQuery(self._preset)


_PRESET_JOB_SENTINEL = object()


def _patch_preset_lookup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    preset: Any,
    job: Any = _PRESET_JOB_SENTINEL,
    boom: bool = False,
) -> None:
    """Stub the owner/global preset lookup used by _resolve_avatar_character_kind.

    Patches ``get_session`` + ``JobRepository`` so the real resolver runs against
    a fake session that yields ``preset`` (or ``None``). ``job`` defaults to a
    fake owned job; pass ``None`` to simulate a missing job, or ``boom=True`` to
    simulate a DB error (the resolver must then fall back to the default kind).
    """
    import contextlib

    from app.models.db import base as db_base
    from app.models.db import repositories as repos

    resolved_job = _FakePresetJob() if job is _PRESET_JOB_SENTINEL else job

    @contextlib.contextmanager
    def _fake_get_session():  # noqa: ANN202
        if boom:
            raise RuntimeError("simulated DB outage")
        yield _FakePresetSession(preset)

    class _FakeJobRepo:
        def __init__(self, session: Any) -> None:  # noqa: ANN001
            self._session = session

        def get(self, job_id: str) -> Any:  # noqa: ANN401
            return resolved_job

    monkeypatch.setattr(db_base, "get_session", _fake_get_session)
    monkeypatch.setattr(repos, "JobRepository", _FakeJobRepo)


def _patch_recording_avatar(
    monkeypatch: pytest.MonkeyPatch, provider: _RecordingProvider, r2: _FakeR2
) -> None:
    from app.domains.reels import premium
    from app.services import avatar as avatar_pkg

    monkeypatch.setattr(premium, "ai_video_funded", lambda job_id, ctx=None: True)
    monkeypatch.setattr(avatar_pkg, "get_avatar_provider", lambda pid: provider)
    monkeypatch.setattr(reelforge, "_r2", lambda: r2)


def _avatar_result(tmp_path) -> dict:  # noqa: ANN001
    avatar_file = tmp_path / "avatar.mp4"
    avatar_file.write_bytes(b"fake mp4")
    # duration == audio_duration below (30.0) so the §8 drift gate passes.
    return {"avatar_video": str(avatar_file), "duration": 30.0}


def test_stage_avatar_talking_photo_preset_uses_talking_photo_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # A preset persisted with config.kind == 'talking_photo' (a creator's photo
    # turned into a HeyGen talking photo) must drive a talking_photo character.
    provider = _RecordingProvider(_avatar_result(tmp_path))
    _patch_recording_avatar(monkeypatch, provider, _FakeR2())
    _patch_preset_lookup(
        monkeypatch, preset=_FakePreset({"kind": "talking_photo"})
    )

    out = reelforge.stage_avatar(
        "jobTP",
        _params(),
        {"audio_url": "https://a/audio.mp3", "audio_duration": 30.0},
    )

    assert len(provider.calls) == 1
    assert provider.calls[0]["character_kind"] == "talking_photo"
    assert out["avatar_duration"] == 30.0


def test_stage_avatar_stock_preset_uses_default_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # A stock catalog preset (no talking_photo kind) must use the default avatar
    # character — existing behaviour is preserved for stock avatars.
    provider = _RecordingProvider(_avatar_result(tmp_path))
    _patch_recording_avatar(monkeypatch, provider, _FakeR2())
    _patch_preset_lookup(
        monkeypatch, preset=_FakePreset({"image_key": "uploads/x.png"})
    )

    reelforge.stage_avatar(
        "jobStock",
        _params(),
        {"audio_url": "https://a/audio.mp3", "audio_duration": 30.0},
    )

    assert provider.calls[0]["character_kind"] == "avatar"


def test_stage_avatar_missing_preset_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # No matching preset (owner/global scoped query returns None) must fall back
    # safely to the default avatar kind rather than failing the stage.
    provider = _RecordingProvider(_avatar_result(tmp_path))
    _patch_recording_avatar(monkeypatch, provider, _FakeR2())
    _patch_preset_lookup(monkeypatch, preset=None)

    reelforge.stage_avatar(
        "jobMissing",
        _params(),
        {"audio_url": "https://a/audio.mp3", "audio_duration": 30.0},
    )

    assert provider.calls[0]["character_kind"] == "avatar"


def test_stage_avatar_missing_job_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # A job row that cannot be loaded (e.g. not yet committed) must not fail the
    # stage; the kind defaults to 'avatar'.
    provider = _RecordingProvider(_avatar_result(tmp_path))
    _patch_recording_avatar(monkeypatch, provider, _FakeR2())
    _patch_preset_lookup(
        monkeypatch, preset=_FakePreset({"kind": "talking_photo"}), job=None
    )

    reelforge.stage_avatar(
        "jobNoRow",
        _params(),
        {"audio_url": "https://a/audio.mp3", "audio_duration": 30.0},
    )

    assert provider.calls[0]["character_kind"] == "avatar"


def test_stage_avatar_preset_db_error_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # A DB error while resolving the preset kind must be swallowed (best-effort)
    # and default to the stock avatar kind — a kind lookup never fails the stage.
    provider = _RecordingProvider(_avatar_result(tmp_path))
    _patch_recording_avatar(monkeypatch, provider, _FakeR2())
    _patch_preset_lookup(monkeypatch, preset=None, boom=True)

    reelforge.stage_avatar(
        "jobBoom",
        _params(),
        {"audio_url": "https://a/audio.mp3", "audio_duration": 30.0},
    )

    assert provider.calls[0]["character_kind"] == "avatar"


def test_resolve_avatar_character_kind_blank_avatar_id_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A blank avatar_id short-circuits to the default without touching the DB.
    def _boom_session():  # noqa: ANN202
        raise AssertionError("DB must not be consulted for a blank avatar_id")

    from app.models.db import base as db_base

    monkeypatch.setattr(db_base, "get_session", _boom_session)

    kind = reelforge._resolve_avatar_character_kind("jobBlank", _params(avatar_id=""))
    assert kind == "avatar"
