"""Ad Clone ingest: link resolution (mocked), shot segmentation on a generated fixture video,
caption / speech / onset analysis and the heuristic clone brief."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app.domains.adclone import analyze, linkresolve, media, service
from app.domains.adclone.analyze import CaptionObs, Observations, ShotObs, SpeechObs
from app.domains.adclone.schemas import CloneBrief

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
CANON = "https://www.tiktok.com/@someone/video/7681123000393010464?_r=1&_t=ZS-9AKIXGE6pxC"


# --------------------------------------------------------------------------- link resolution
def test_short_link_resolves_to_canonical_post_without_tracking_params():
    calls = []

    def head(url):
        calls.append(url)
        return 301, CANON

    link = linkresolve.resolve("https://vt.tiktok.com/ZSbXtdskk/", head=head)
    assert link.url == "https://www.tiktok.com/@someone/video/7681123000393010464"
    assert link.platform == "tiktok" and link.video_id == "7681123000393010464"
    assert link.source_ref.startswith("platform:tiktok:") and link.hops == 1
    assert calls == ["https://vt.tiktok.com/ZSbXtdskk/"]


def test_bare_short_link_without_scheme_is_accepted():
    link = linkresolve.resolve("vt.tiktok.com/ZSbXtdskk/", head=lambda u: (302, CANON))
    assert link.platform == "tiktok"


def test_canonical_link_needs_no_network():
    def head(url):
        raise AssertionError("no hop expected")

    link = linkresolve.resolve("https://www.tiktok.com/@a/video/123", head=head)
    assert link.hops == 0 and link.video_id == "123"


def test_short_link_redirecting_off_platform_is_refused():
    with pytest.raises(linkresolve.LinkError) as exc:
        linkresolve.resolve("https://vt.tiktok.com/x/", head=lambda u: (301, "http://169.254.169.254/latest"))
    assert exc.value.status_code == 422


def test_redirect_loop_is_bounded():
    with pytest.raises(linkresolve.LinkError) as exc:
        linkresolve.resolve("https://vt.tiktok.com/x/", head=lambda u: (301, "https://vm.tiktok.com/y/"))
    assert exc.value.status_code == 502


@pytest.mark.parametrize("url,status", [("", 400), ("https://example.com/video.mp4", 422),
                                        ("ftp://tiktok.com/x", 422)])
def test_unsupported_links(url, status):
    with pytest.raises(linkresolve.LinkError) as exc:
        linkresolve.resolve(url, head=lambda u: (404, ""))
    assert exc.value.status_code == status


def test_dead_short_link_is_a_clean_error():
    with pytest.raises(linkresolve.LinkError) as exc:
        linkresolve.resolve("https://vt.tiktok.com/dead/", head=lambda u: (404, ""))
    assert exc.value.status_code == 422


# --------------------------------------------------------------------------- shots
def test_cut_parsing_and_short_shot_merge():
    log = "[Parsed_showinfo_1] n:0 pts:60 pts_time:2 \n[Parsed_showinfo_1] n:1 pts_time:7.5 \n pts_time:7.6"
    assert media.parse_cut_times(log) == [2.0, 7.5, 7.6]
    shots = media.shots_from_cuts([2.0, 7.5, 7.6], 19.0)
    assert [(s.start_s, s.end_s) for s in shots] == [(0.0, 2.0), (2.0, 7.5), (7.5, 19.0)]
    assert shots[1].duration_s == 5.5 and shots[1].mid_s == 4.75


@pytest.fixture(scope="module")
def fixture_video(tmp_path_factory):
    if not FFMPEG:
        pytest.skip("ffmpeg not installed")
    out = tmp_path_factory.mktemp("adclone") / "fixture.mp4"
    parts = [("red", 1.0), ("blue", 1.5), ("white", 1.0)]
    args = ["ffmpeg", "-v", "error", "-y"]
    for colour, d in parts:
        args += ["-f", "lavfi", "-t", str(d), "-i", f"color=c={colour}:s=160x284:r=30"]
    args += ["-f", "lavfi", "-t", "3.5", "-i", "sine=frequency=440:sample_rate=8000",
             "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-map", "3:a",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)]
    subprocess.run(args, check=True)
    return str(out)


def test_probe_and_scene_detection_on_fixture(fixture_video):
    pr = media.probe(fixture_video)
    assert pr.width == 160 and pr.height == 284 and pr.has_audio
    assert pr.duration_s == pytest.approx(3.5, abs=0.1)
    shots = media.detect_shots(fixture_video, pr.duration_s)
    assert len(shots) == 3
    assert [round(s.duration_s, 1) for s in shots] == pytest.approx([1.0, 1.5, 1.0], abs=0.1)


def test_keyframe_and_audio_envelope_on_fixture(fixture_video, tmp_path):
    frame = media.extract_frame(fixture_video, 1.7, str(tmp_path / "k.jpg"), width=80)
    assert (tmp_path / "k.jpg").stat().st_size > 0 and frame.endswith("k.jpg")
    env = media.audio_envelope(fixture_video)
    assert len(env) >= 60 and max(env) > 0.05  # lavfi sine is -18 dBFS


def test_onsets_and_bpm():
    env = [0.0] * 200
    for i in range(0, 200, 12):  # a hit every 0.6 s -> 100 BPM
        env[i] = 1.0
    onsets = media.onsets_from_envelope(env, 0.05)
    assert len(onsets) >= 10
    assert media.bpm_from_onsets(onsets) == pytest.approx(100.0, abs=1.0)
    assert media.bpm_from_onsets([0.1, 0.5]) is None


# --------------------------------------------------------------------------- captions + brief
def _cap(t, text, y=0.85):
    return CaptionObs(at_s=t, text=text, y_center=y)


def test_subtitle_band_ignores_text_printed_on_clothing_and_ocr_jitter():
    caps = (_cap(0.25, "eggs are $12"), _cap(0.75, "eggs are $12"), _cap(1.25, "eggs are $12 Mia!"),
            _cap(1.75, "rent's up again"), _cap(1.75, "you met me at a very", 0.45),
            _cap(2.25, "rent's up again"), _cap(2.75, ""))
    runs = analyze.caption_runs(caps, 0.5, 3.0)
    assert [(r[0], r[1], r[2]) for r in runs] == [(0.0, 1.5, "eggs are $12"), (1.5, 2.5, "rent's up again"),
                                                  (2.5, 3.0, "")]
    assert analyze.same_caption("hope you're doing well;-)", "hope you're doing well;)")
    assert not analyze.same_caption("god damn bro", "maybe it's time")


@pytest.mark.parametrize("text,pattern", [("eggs are $12", "price_shock"), ("rent is up 6%", "price_shock"),
                                          ("why is tea free here?", "question"), ("POV: you moved", "pov"),
                                          ("nobody tells you this", "bold_claim"), ("hello there", "statement")])
def test_hook_patterns(text, pattern):
    assert analyze.hook_pattern(text) == pattern


def _observations(**kw):
    shots = (ShotObs(0.0, 2.0, 0.15, 1.0, 0.0), ShotObs(2.0, 7.5, None, 1.0, 0.0),
             ShotObs(7.5, 12.0, 0.25, 1.08, 0.0), ShotObs(12.0, 15.0, 0.12, 0.95, 0.0))
    caps = tuple(_cap(t + 0.25, txt) for t, txt in
                 [(0, "eggs are $12"), (0.5, "eggs are $12"), (1, "eggs are $12"), (1.5, "eggs are $12"),
                  (2, "rent went up"), (2.5, "rent went up"), (3, "rent went up"), (3.5, "landlord texted"),
                  (4, "landlord texted"), (4.5, "landlord texted"), (5, "landlord texted"), (5.5, "landlord texted"),
                  (6, "landlord texted"), (6.5, "landlord texted"), (7, "landlord texted"), (7.5, "ugh bro"),
                  (8, "ugh bro"), (8.5, "maybe it's time"), (9, "maybe it's time"), (9.5, "maybe it's time"),
                  (10, "maybe it's time"), (10.5, "maybe it's time"), (11, "maybe it's time"), (11.5, "maybe it's time"),
                  (12, "you met me at a very odd time in my life"), (12.5, "you met me at a very odd time in my life"),
                  (13, "shop.example.com Brandname"), (13.5, "shop.example.com Brandname"),
                  (14, "shop.example.com Brandname"), (14.5, "shop.example.com Brandname")])
    base = dict(url=CANON, platform="tiktok", source_ref="platform:tiktok:abc", duration_s=15.0, width=1080,
                height=1920, shots=shots, captions=caps,
                speech=(SpeechObs(0.0, 7.5, "eggs are twelve dollars rent went up landlord texted"),
                        SpeechObs(7.5, 12.0, "ugh bro maybe it's time")),
                onsets_s=tuple(i * 0.6 for i in range(20)), avoid_terms=("examplebrand",))
    return Observations(**{**base, **kw})


def test_heuristic_brief_from_observations():
    brief = analyze.heuristic_brief(_observations())
    assert isinstance(brief, CloneBrief)
    assert brief.hook.pattern == "price_shock" and 1.0 <= brief.hook.end_s <= 3.0
    roles = [b.role for b in brief.beats]
    assert roles[0] == "hook" and "cta" in roles and "payoff" in roles
    assert brief.beats[-1].shot_type == "product_card"
    framings = {b.on_screen_text: b.framing for b in brief.beats}
    assert framings["eggs are $12"] == "medium" and framings["rent went up"] == "wide"
    assert framings["ugh bro"] == "close"
    assert any(b.camera_move == "push_in" for b in brief.beats)
    assert brief.pacing.shot_count == 4 and brief.pacing.music_bpm == pytest.approx(100.0, abs=1)
    assert brief.caption_style.present and brief.caption_style.position == "bottom"
    assert brief.caption_style.case == "lower"
    assert "examplebrand" in brief.source.avoid_terms
    assert brief.beats[0].line.startswith("eggs are")


def test_short_uncaptioned_beats_fold_into_neighbours():
    s1, s2 = ShotObs(0, 2), ShotObs(2, 4)
    rows = [(0.0, 1.5, s1, "a", "", False), (1.5, 2.0, s1, "", "and", False), (2.0, 2.4, s2, "", "x", False),
            (2.4, 4.0, s2, "b", "y", False)]
    merged = analyze.merge_short(rows)
    assert [(r[0], r[1], r[3], r[4]) for r in merged] == [(0.0, 2.0, "a", "and"), (2.0, 4.0, "b", "x y")]
    assert rows[1][1] == 2.0  # input untouched


def test_llm_refinement_validates_and_ignores_junk():
    brief = analyze.heuristic_brief(_observations())
    reply = json.dumps({"hook_pattern": "question", "hook_summary": "price complaint", "setting": "balcony, day",
                        "beats": [{"i": 1, "role": "turn", "type": "reaction"}, {"i": 99, "role": "hook"},
                                  {"i": 2, "role": "villain", "type": "bogus"}]})
    out = analyze.refine_with_llm(brief, lambda prompt: "Sure! " + reply)
    assert out.analysis == "llm" and out.hook.pattern == "question" and out.setting == "balcony, day"
    assert out.beats[1].role == "turn" and out.beats[1].shot_type == "reaction"
    assert out.beats[2].role == brief.beats[2].role
    bad = analyze.refine_with_llm(brief, lambda prompt: "no json here")
    assert bad.analysis == "heuristic" and any("llm refinement skipped" in n for n in bad.notes)


def test_llm_prompt_never_asks_for_appearance():
    prompt = analyze.llm_prompt(analyze.heuristic_brief(_observations()))
    assert "Do not describe the people's appearance" in prompt


def test_analyze_link_deletes_the_source_workdir(tmp_path):
    seen = {}

    def downloader(url, stem):
        seen["url"] = url
        path = stem + ".mp4"
        (tmp_path / "w").mkdir(exist_ok=True)
        open(path, "wb").write(b"x")
        return path

    def observer(path, workdir, **kw):
        seen["path"] = path
        return _observations(url=kw["url"], source_ref=kw["source_ref"])

    workdir = tmp_path / "w"
    brief = service.analyze_link("https://vt.tiktok.com/ZS/", head=lambda u: (301, CANON), downloader=downloader,
                                 observer=observer, workdir=str(workdir))
    assert seen["url"].startswith("https://www.tiktok.com/@someone/video/")
    assert brief.source.platform == "tiktok"
    assert not workdir.exists()


def test_analyze_link_download_failure_is_typed():
    class Boom(Exception):
        status_code = 403
        message = "platform link ingestion is not enabled"

    def downloader(url, stem):
        raise Boom()

    with pytest.raises(service.AdCloneError) as exc:
        service.analyze_link("https://www.tiktok.com/@a/video/1", downloader=downloader)
    assert exc.value.status_code == 403
