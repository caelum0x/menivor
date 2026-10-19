"""M2.1: landing showcase rules, public media bucket and publishing gate."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from typing import Any

import pytest

SHOWCASE = os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api", "tools", "ops", "showcase")
sys.path.insert(0, os.path.abspath(SHOWCASE))

import checks  # noqa: E402
import plan  # noqa: E402
import publish  # noqa: E402
import sources  # noqa: E402

from app.platform.storage import r2 as r2mod  # noqa: E402


# --------------------------------------------------------------------------- #
# Plan rules
# --------------------------------------------------------------------------- #
def test_plan_passes_every_rule() -> None:
    assert [str(v) for v in checks.plan_violations(plan.REELS)] == []


def test_sources_json_is_current_with_the_plan() -> None:
    with open(os.path.join(SHOWCASE, "sources.json"), encoding="utf-8") as handle:
        on_disk = json.load(handle)
    rebuilt = sources.build(plan.REELS, on_disk["generated"], plan.RENDER_LANE)
    assert on_disk == rebuilt, "run apps/api/tools/ops/showcase/sources.py"


def test_no_two_reels_share_a_loop_or_voice_in_sources_json() -> None:
    with open(os.path.join(SHOWCASE, "sources.json"), encoding="utf-8") as handle:
        reels = json.load(handle)["reels"]
    voices = [checks.voice_persona(r["voice"]["name"]) for r in reels]
    assert len(set(voices)) == len(voices)
    loops = [json.dumps(r["loop"], sort_keys=True) for r in reels
             if r["loop"] and r["loop"]["source"] != "footage montage"]
    assert len(set(loops)) == len(loops)
    niches = [r["niche"].lower() for r in reels]
    assert len(set(niches)) == len(niches)


def _reel(key: str, **extra: Any) -> dict:
    base = dict(key=key, niche=f"niche {key}", style="", footage=[f"f-{key}"], loop="",
                voice=f"en-US-{key.title()}Neural", script=" ".join(["word"] * 60))
    return {**base, **extra}


def test_shared_voice_loop_niche_and_footage_are_caught() -> None:
    reels = [
        _reel("a", voice="en-US-EmmaNeural", loop="marble-run.mp4", niche="Travel", footage=["1"]),
        _reel("b", voice="en-US-EmmaMultilingualNeural", loop="marble-run.mp4", niche="travel", footage=["1"]),
    ]
    rules = {v.rule for v in checks.repeat_violations(reels)}
    assert rules == {"repeat-voice", "repeat-loop", "repeat-niche", "repeat-footage"}


def test_footage_loops_count_as_distinct_per_reel() -> None:
    reels = [_reel("a", loop="@footage"), _reel("b", loop="@footage")]
    assert checks.repeat_violations(reels) == []


def test_self_ads_are_capped_at_two_in_different_styles() -> None:
    own = [_reel(k, page=f"https://{k}.example", style="pov_text") for k in ("a", "b", "c")]
    rules = [v.rule for v in checks.self_ad_violations(own)]
    assert "self-ads" in rules and "self-ads-style" in rules
    assert checks.self_ad_violations([_reel("a", page="https://a.example", style="pov_text"),
                                      _reel("b", page="https://b.example", style="meme_hook")]) == []


def test_script_length_targets_twenty_to_forty_seconds() -> None:
    short = _reel("a", script="too short")
    long = _reel("b", script=" ".join(["word"] * 200))
    assert {v.keys[0] for v in checks.length_violations([short, long])} == {"a", "b"}
    for reel in plan.REELS:
        assert 20 <= checks.estimated_seconds(reel["script"]) <= 40, reel["key"]


def test_fact_check() -> None:
    # Example business on stock footage: digit figures have no source to back them.
    assert checks.fact_check("Save 40% today, three drops a day.", None) == ["40%"]
    assert checks.fact_check("Three drops in the morning.", None) == []
    # Own product: every number must be on its page.
    page = "Paste a link. Pick a style. Get three reels. Plans from 9 dollars."
    assert checks.fact_check("You got three reels back for 9 dollars.", page) == []
    assert checks.fact_check("You got five reels back in 30 seconds.", page) == ["30", "five"]


def test_fact_violations_use_fetched_page_text() -> None:
    reel = _reel("own", page="https://own.example", script="Get three reels in 10 minutes.")
    assert checks.fact_violations([reel]) == []  # pages not fetched: deferred to --pages
    found = checks.fact_violations([reel], {"https://own.example": "Get three reels."})
    assert [v.rule for v in found] == ["fact-check"] and "10" in found[0].detail


def test_plan_renders_in_the_bulk_lane_off_peak() -> None:
    from app.domains.reels.policy import LANE_BULK, LANES

    assert plan.RENDER_LANE == LANE_BULK == LANES[-1]
    import runner

    window = runner.offpeak_hours("1-7")
    assert runner.in_offpeak(dt.datetime(2026, 9, 28, 3, 0), window)
    assert not runner.in_offpeak(dt.datetime(2026, 9, 28, 14, 0), window)
    assert runner.in_offpeak(dt.datetime(2026, 9, 28, 23, 30), runner.offpeak_hours("22-6"))
    assert not runner.in_offpeak(dt.datetime(2026, 9, 28, 12, 0), runner.offpeak_hours("22-6"))


# --------------------------------------------------------------------------- #
# Media checks (real ffmpeg)
# --------------------------------------------------------------------------- #
_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def _synth(path: str, video: str, seconds: float, audio: bool = True) -> None:
    sep = ":" if "=" in video else "="
    argv = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{video}{sep}size=108x192:rate=15:duration={seconds}"]
    if audio:
        argv += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    argv += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", path]
    subprocess.run(argv, check=True, timeout=120)


@pytest.mark.integration
@pytest.mark.skipif(not _FFMPEG, reason="needs ffmpeg and ffprobe")
def test_media_verdict_passes_a_moving_reel_with_sound(tmp_path) -> None:
    path = str(tmp_path / "moving.mp4")
    _synth(path, "testsrc2", 21)
    verdict = checks.media_verdict(path)
    assert verdict["ok"], verdict
    assert verdict["audio_streams"] == 1 and 20 <= verdict["duration_s"] <= 40


@pytest.mark.integration
@pytest.mark.skipif(not _FFMPEG, reason="needs ffmpeg and ffprobe")
def test_media_verdict_fails_a_still_a_silent_or_a_short_reel(tmp_path) -> None:
    still = str(tmp_path / "still.mp4")
    _synth(still, "color=c=gray", 22)
    assert any("near-static" in e for e in checks.media_verdict(still)["errors"])
    silent = str(tmp_path / "silent.mp4")
    _synth(silent, "testsrc2", 22, audio=False)
    assert "no audio stream" in checks.media_verdict(silent)["errors"]
    short = str(tmp_path / "short.mp4")
    _synth(short, "testsrc2", 8)
    assert any(e.startswith("duration") for e in checks.media_verdict(short)["errors"])
    assert checks.media_verdict(str(tmp_path / "nope.mp4"))["errors"] == ["missing"]


# --------------------------------------------------------------------------- #
# Publishing: public bucket, only passing replacements, clean-network check
# --------------------------------------------------------------------------- #
def test_only_passing_reels_replace_live_files() -> None:
    qa = {"plan_ok": True, "media": {"a": {"ok": True}, "b": {"ok": False}}}
    assert publish.passing_keys(qa, ["a", "b", "c"]) == ["a"]
    assert publish.passing_keys({**qa, "plan_ok": False}, ["a"]) == []


def test_publish_puts_to_the_public_bucket_with_stable_keys(tmp_path) -> None:
    for sub in ("web", "full"):
        (tmp_path / sub).mkdir()
    (tmp_path / "web" / "a.mp4").write_bytes(b"loop")
    (tmp_path / "web" / "a-poster.jpg").write_bytes(b"jpg")
    (tmp_path / "full" / "a-full.mp4").write_bytes(b"full")
    puts: list[dict] = []

    class _S3:
        def put_object(self, **kw: Any) -> None:
            puts.append({k: v for k, v in kw.items() if k != "Body"})

    class _Client:
        _bucket = "menivor-public"
        _s3 = _S3()

    uploads = publish.staged_uploads("a", str(tmp_path))
    assert all(line.startswith("dry-run") for line in publish.publish(uploads, apply=False))
    assert puts == []
    publish.publish(uploads, apply=True, client_factory=_Client)
    assert [p["Key"] for p in puts] == ["showcase/a.mp4", "showcase/a-poster.jpg", "showcase/a-full.mp4"]
    assert {p["Bucket"] for p in puts} == {"menivor-public"}


def test_verify_rejects_r2_dev_and_non_200() -> None:
    class _Resp:
        def __init__(self, status: int) -> None:
            self.status = status

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def opener(req, timeout: int = 0) -> _Resp:  # noqa: ANN001
        return _Resp(200 if req.full_url.endswith(".mp4") else 404)

    urls = publish.public_urls("https://media.menivor.com", ["a"])
    assert urls == ["https://media.menivor.com/showcase/a.mp4", "https://media.menivor.com/showcase/a-poster.jpg",
                    "https://media.menivor.com/showcase/a-full.mp4"]
    failures = publish.verify([*urls, "https://pub-x.r2.dev/showcase/a.mp4"], opener=opener)
    assert len(failures) == 2
    assert any("a-poster.jpg: HTTP 404" in f for f in failures)
    assert any("r2.dev" in f for f in failures)


def test_public_media_target_defaults_and_refuses_r2_dev(monkeypatch) -> None:
    monkeypatch.delenv("R2_PUBLIC_MEDIA_BUCKET", raising=False)
    monkeypatch.delenv("R2_PUBLIC_MEDIA_BASE_URL", raising=False)
    assert r2mod.public_media_target() == ("menivor-public", "https://media.menivor.com")
    monkeypatch.setenv("R2_PUBLIC_MEDIA_BASE_URL", "https://pub-123.r2.dev")
    with pytest.raises(RuntimeError, match="not r2.dev"):
        r2mod.public_media_target()
    monkeypatch.setenv("R2_PUBLIC_MEDIA_BASE_URL", "http://media.menivor.com")
    with pytest.raises(RuntimeError, match="https"):
        r2mod.public_media_target()


def test_public_media_client_uses_its_own_bucket_and_domain(monkeypatch) -> None:
    class _FakeBoto3:
        @staticmethod
        def client(service_name: str, **kwargs: Any) -> object:
            return object()

    monkeypatch.setattr(r2mod, "boto3", _FakeBoto3)
    monkeypatch.setattr(r2mod, "_BotoConfig", lambda **kw: kw)
    monkeypatch.setattr(r2mod, "_r2_config", lambda: {
        "account_id": "acct", "access_key_id": "k", "secret_access_key": "s",
        "bucket": "menivor-private", "public_base_url": "https://pub-old.r2.dev"})
    monkeypatch.setattr(r2mod, "_public_media_singleton", None)
    monkeypatch.delenv("R2_PUBLIC_MEDIA_BUCKET", raising=False)
    monkeypatch.delenv("R2_PUBLIC_MEDIA_BASE_URL", raising=False)
    client = r2mod.get_public_media_client()
    assert client._bucket == "menivor-public"
    assert client.public_url("showcase/a.mp4") == "https://media.menivor.com/showcase/a.mp4"
    # The default client is untouched.
    assert r2mod.R2Client()._bucket == "menivor-private"
