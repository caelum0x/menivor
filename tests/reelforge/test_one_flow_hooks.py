"""One-flow create: faceless TTS preset, hook styles, and run experiments.

Covers:
  * the faceless story preset (captions_only + voice, no uploaded audio/footage)
    generates a script and narrates it with TTS instead of requiring a recording;
  * hook styles: validation, distinct rotation, shape checks, and the styled
    generator's retry + template fallback;
  * a multi-variant run registered as a 1-body/N-hooks experiment (batch link,
    idempotency, ownership) and synced from the winner-loop measurements.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.experiments import hook_styles as hs
from app.domains.experiments import registration as reg
from app.models.db import experiments, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.services import reelforge
from app.services.reelforge import ReelForgeParams, ReelForgeStageError


# --------------------------------------------------------------------------- #
# Hook styles
# --------------------------------------------------------------------------- #
def test_normalize_hook_style_accepts_known_and_blank() -> None:
    assert hs.normalize_hook_style("") == ""
    assert hs.normalize_hook_style(" POV ") == "pov"
    assert hs.normalize_hook_style("nobody-tells-you") == "nobody_tells_you"
    with pytest.raises(hs.HookStyleError):
        hs.normalize_hook_style("clickbait")


def test_rotate_hook_styles_is_distinct_and_leads_with_request() -> None:
    assert hs.rotate_hook_styles(3) == ["pov", "question", "nobody_tells_you"]
    assert hs.rotate_hook_styles(3, "stat") == ["stat", "pov", "question"]
    assert len(set(hs.rotate_hook_styles(99))) == len(hs.HOOK_STYLES)
    assert hs.rotate_hook_styles(0) == []


@pytest.mark.parametrize(
    ("hook", "style", "expected"),
    [
        ("POV: you just quit sugar.", "pov", True),
        ("You just quit sugar.", "pov", False),
        ("Is quitting sugar worth it?", "question", True),
        ("Quitting sugar is worth it.", "question", False),
        ("Here is what nobody tells you about sugar.", "nobody_tells_you", True),
        ("Şeker hakkında kimsenin söylemediği şey.", "nobody_tells_you", True),
        ("21 days without sugar changed my sleep.", "stat", True),
        ("A week without sugar changed my sleep.", "stat", False),
        ("Last year I tried to quit sugar and failed.", "story", True),
        ("Did I quit sugar?", "story", False),
    ],
)
def test_hook_matches_style(hook: str, style: str, expected: bool) -> None:
    assert hs.hook_matches_style(hook, style) is expected


def test_template_hooks_are_distinct_and_match_their_style_where_checkable() -> None:
    subject = "Why most people quit the gym in week three"
    hooks = {style: hs.template_hook(style, subject, "en") for style in hs.HOOK_STYLES}
    assert len(set(hooks.values())) == len(hs.HOOK_STYLES)
    for style in ("pov", "question", "nobody_tells_you", "story"):
        assert hs.hook_matches_style(hooks[style], style), hooks[style]
    assert "why most people quit the gym" in hooks["pov"]
    assert hs.template_hook("pov", "spor salonunu bırakmak neden bu kadar kolay", "auto").startswith("POV: sonunda")


def _ugc_json(hook: str) -> str:
    return json.dumps({"hook": hook, "segments": ["Beat one.", "Beat two."], "cta": "Follow for more.", "est_duration_s": 20})


def test_styled_script_keeps_a_conforming_model_hook() -> None:
    prompts: list[str] = []

    def _gen(prompt: str) -> str:
        prompts.append(prompt)
        return _ugc_json("Is meal prep actually worth it?")

    out = hs.generate_styled_script(
        video_subject="meal prep", language="en", target_duration_s=20,
        hook_style="question", generate=_gen, attempts=3,
    )
    assert out is not None
    assert out["hook"] == "Is meal prep actually worth it?"
    assert out["hook_source"] == "model"
    assert len(prompts) == 1
    assert "Opening hook angle (REQUIRED)" in prompts[0]
    assert 'ends with "?"' in prompts[0]


def test_styled_script_retries_then_falls_back_to_template_hook() -> None:
    calls: list[int] = []

    def _gen(prompt: str) -> str:
        calls.append(1)
        return _ugc_json("Meal prep saves time.")  # never a POV hook

    out = hs.generate_styled_script(
        video_subject="meal prep", language="en", target_duration_s=20,
        hook_style="pov", generate=_gen, attempts=2,
    )
    assert len(calls) == 2
    assert out is not None
    assert out["hook_source"] == "template"
    assert out["hook"].startswith("POV:")
    # Only the hook changed: the body and CTA are the model's.
    assert out["full_text"].split("\n\n") == [out["hook"], "Beat one.", "Beat two.", "Follow for more."]


def test_styled_script_returns_none_when_nothing_parses() -> None:
    out = hs.generate_styled_script(
        video_subject="meal prep", language="en", target_duration_s=20,
        hook_style="stat", generate=lambda p: "Error: provider down", attempts=2,
    )
    assert out is None


# --------------------------------------------------------------------------- #
# Faceless story preset (reelforge stages)
# --------------------------------------------------------------------------- #
def _faceless(**over: Any) -> ReelForgeParams:
    base: dict[str, Any] = {
        "video_subject": "the night I missed my flight",
        "voice_name": "elevenlabs:abc",
        "layout": "captions_only",
        "background_id": "minecraft-parkour",
    }
    base.update(over)
    return ReelForgeParams(**base)


def test_is_faceless_tts_only_without_uploads_and_with_voice() -> None:
    assert reelforge._is_faceless_tts(_faceless())
    assert not reelforge._is_faceless_tts(_faceless(voice_name=""))
    assert not reelforge._is_faceless_tts(_faceless(screen_recording_key="jobs/x/screen.mp4"))
    assert not reelforge._is_faceless_tts(_faceless(voiceover_key="jobs/x/vo.mp3"))
    assert not reelforge._is_faceless_tts(_faceless(layout="split"))


def _no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reelforge, "_persist_script", lambda job_id, script: None)


def test_faceless_stage_script_generates_instead_of_skipping(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.script import ugc

    _no_db(monkeypatch)
    monkeypatch.setattr(ugc, "generate_ugc_script", lambda **kw: {"full_text": "A generated story."})
    out = reelforge.stage_script("jf1", _faceless(), {})
    assert out == {"script": "A generated story."}


def test_captions_only_with_recording_still_skips_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_db(monkeypatch)
    out = reelforge.stage_script("jf2", _faceless(screen_recording_key="jobs/jf2/s.mp4"), {})
    assert out == {"script": ""}


def test_stage_script_threads_hook_style_into_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _styled(**kwargs: Any) -> dict:
        captured.update(kwargs)
        return {"full_text": "POV: you missed it.\n\nBody.", "hook_source": "model"}

    _no_db(monkeypatch)
    monkeypatch.setattr(hs, "generate_styled_script", _styled)
    out = reelforge.stage_script("jf3", _faceless(hook_style="pov"), {})
    assert out["script"].startswith("POV:")
    assert captured["hook_style"] == "pov"
    assert captured["video_subject"] == "the night I missed my flight"


def test_faceless_stage_tts_uses_tts_not_a_recording(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.services import voice

    class _Word:
        def __init__(self, text: str, start: float, end: float) -> None:
            self.text, self.start, self.end = text, start, end

    class _Sub:
        words = [_Word("A", 0.0, 0.4), _Word("story.", 0.4, 0.9)]

    class _R2:
        def upload_file(self, local: str, key: str, content_type: str) -> str:
            return f"https://cdn.example/{key}"

    def _tts(*, text, voice_name, voice_rate, voice_file):  # noqa: ANN001
        with open(voice_file, "wb") as fh:
            fh.write(b"ID3")
        return _Sub()

    def _no_captions_only(*args: Any, **kwargs: Any) -> dict:
        raise AssertionError("faceless reels must not take the recording path")

    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    monkeypatch.setattr(reelforge, "_r2", lambda: _R2())
    monkeypatch.setattr(reelforge, "_stage_tts_captions_only", _no_captions_only)
    monkeypatch.setattr(voice, "tts", _tts)
    monkeypatch.setattr(voice, "get_audio_duration", lambda target: 0.9)

    out = reelforge.stage_tts("jf4", _faceless(), {"script": "A story."})
    assert out["audio_key"] == "jobs/jf4/audio.mp3"
    assert out["audio_duration"] == 0.9
    assert out["words"] == [["A", 0.0, 0.4], ["story.", 0.4, 0.9]]


def test_captions_only_without_voice_still_requires_a_recording() -> None:
    with pytest.raises(ReelForgeStageError, match="requires an uploaded screen recording"):
        reelforge.stage_tts("jf5", _faceless(voice_name=""), {"script": "x"})


def test_faceless_avatar_stage_is_skipped() -> None:
    out = reelforge.stage_avatar("jf6", _faceless(), {"audio_url": "https://x"})
    assert out == {"avatar_key": "", "avatar_video": "", "avatar_duration": 0.0}


# --------------------------------------------------------------------------- #
# Run registration (sqlite)
# --------------------------------------------------------------------------- #
@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add_all([User(id="u1", email="u1@x.com"), User(id="u2", email="u2@x.com")])
    s.flush()
    yield s
    s.close()


def _job(session, job_id: str, user_id: str = "u1", batch_id: str | None = None) -> Job:
    job = Job(id=job_id, user_id=user_id, kind="avatar_reel", params={}, stages={}, batch_id=batch_id)
    session.add(job)
    session.flush()
    return job


def _variants(*pairs: tuple[str, str]) -> list[reg.RunVariant]:
    return [reg.RunVariant(job_id=j, hook_style=s) for j, s in pairs]


def test_register_link_run_assigns_one_batch_and_is_idempotent(session) -> None:
    for jid in ("jobaaa1", "jobbbb2", "jobccc3"):
        _job(session, jid)
    run = _variants(("jobaaa1", "pov"), ("jobbbb2", "question"), ("jobccc3", "nobody_tells_you"))
    first = reg.register_run(session, user_id="u1", variants=run)
    assert first.created
    batches = {session.get(Job, j).batch_id for j in ("jobaaa1", "jobbbb2", "jobccc3")}
    assert batches == {first.batch_id}
    assert first.experiment_key == f"run:{first.batch_id}"

    from app.domains.publishing.experiment_repo import ExperimentRepository

    refs = sorted(v.hook_ref for v in ExperimentRepository(session).variants(first.experiment_id))
    assert refs == ["nobody_tells_you:jobccc3", "pov:jobaaa1", "question:jobbbb2"]

    again = reg.register_run(session, user_id="u1", variants=run)
    assert not again.created
    assert again.experiment_id == first.experiment_id


def test_register_topic_run_reuses_existing_batch(session) -> None:
    for jid in ("jobtop1", "jobtop2"):
        _job(session, jid, batch_id="batchtopic01")
    out = reg.register_run(session, user_id="u1", variants=_variants(("jobtop1", "pov"), ("jobtop2", "stat")))
    assert out.batch_id == "batchtopic01"


def test_register_rejects_foreign_partial_and_invalid_runs(session) -> None:
    _job(session, "jobmine1")
    _job(session, "jobtheir", user_id="u2")
    with pytest.raises(reg.RunRegistrationError) as foreign:
        reg.register_run(session, user_id="u1", variants=_variants(("jobmine1", "pov"), ("jobtheir", "stat")))
    assert foreign.value.status_code == 404

    for jid in ("jobb1xx", "jobb2xx", "jobb3xx"):
        _job(session, jid, batch_id="batchthree01")
    with pytest.raises(reg.RunRegistrationError) as partial:
        reg.register_run(session, user_id="u1", variants=_variants(("jobb1xx", "pov"), ("jobb2xx", "stat")))
    assert partial.value.status_code == 409

    with pytest.raises(reg.RunRegistrationError):
        reg.register_run(session, user_id="u1", variants=_variants(("jobmine1", "pov")))
    with pytest.raises(reg.RunRegistrationError):
        reg.register_run(session, user_id="u1", variants=_variants(("jobmine1", "pov"), ("jobmine1", "stat")))
    with pytest.raises(reg.RunRegistrationError):
        reg.register_run(session, user_id="u1", variants=_variants(("jobmine1", "bogus"), ("jobb1xx", "stat")))


def test_sync_run_copies_loop_measurements_and_evaluates(session) -> None:
    from app.domains.insights.winner_loop_state import LOOP_KEY

    anchor = _job(session, "jobsyn1", batch_id="batchsync01")
    _job(session, "jobsyn2", batch_id="batchsync01")
    reg.register_run(session, user_id="u1", variants=_variants(("jobsyn1", "pov"), ("jobsyn2", "question")))
    anchor.stages = {LOOP_KEY: {"status": "measuring", "mode": "manual", "variants": [
        {"job_id": "jobsyn1", "views": 900, "avg_watch_frac": 0.8, "engagement_rate": 0.1},
        {"job_id": "jobsyn2", "views": 700, "avg_watch_frac": 0.2, "engagement_rate": 0.02},
    ]}}
    session.flush()

    experiment, variants, state = reg.sync_run(session, user_id="u1", batch_id="batchsync01")
    by_job = {reg.job_id_of_hook_ref(v.hook_ref): v for v in variants}
    assert by_job["jobsyn1"].views == 900
    assert by_job["jobsyn1"].avg_watch_frac == pytest.approx(0.8)
    assert experiment.status == "conclusive"
    assert experiment.winner_hook_ref == "pov:jobsyn1"
    assert state["status"] == "measuring"

    with pytest.raises(reg.RunRegistrationError):
        reg.sync_run(session, user_id="u2", batch_id="batchsync01")


# --------------------------------------------------------------------------- #
# create_job fan-out helpers
# --------------------------------------------------------------------------- #
def test_variant_hook_styles_only_for_generated_batches() -> None:
    from app.domains.reels import router as reels_router_pkg  # noqa: F401 - import side effects
    import importlib

    module = importlib.import_module("app.domains.reels.router")
    topic = ReelForgeParams(video_subject="x")
    assert module._variant_hook_styles(topic, 3) == ["pov", "question", "nobody_tells_you"]
    assert module._variant_hook_styles(topic, 1) == []
    assert module._variant_hook_styles(ReelForgeParams(video_subject="x", video_script="Hi."), 3) == []
    assert module._variant_hook_styles(ReelForgeParams(video_subject="x", hook_style="story"), 2) == ["story", "pov"]


def test_validate_hook_style_rejects_unknown() -> None:
    import importlib

    from app.models.exception import HttpException

    module = importlib.import_module("app.domains.reels.router")
    assert module._validate_hook_style(ReelForgeParams(video_subject="x", hook_style="POV"), "r1").hook_style == "pov"
    with pytest.raises(HttpException):
        module._validate_hook_style(ReelForgeParams(video_subject="x", hook_style="clickbait"), "r1")
