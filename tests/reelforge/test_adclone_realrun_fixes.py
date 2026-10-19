"""Ad Clone fixes from running it on three real TikToks (2026-10-06).

1. The template writer gave every link the same story, the same balcony set and repeated lines.
2. Whisper picked a cached English-only model, so Turkish speech came out as English nonsense.
3. The brand filter only caught domains: the source brand "Velvele" reached our script.
4. OCR read the print on the source's shirt as captions.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from app.domains.adclone import analyze, brandterms, ingest, ipguard, presets, rewrite, scriptbank, vision
from app.domains.adclone.analyze import CaptionObs, Observations, ShotObs, SpeechObs
from app.domains.adclone.rewrite import CloneOptions
from app.domains.adclone.schemas import CloneBrief

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "adclone" / "brief-tiktok-price-shock.json"
OXHAN = presets.load("oxhan")
CTA = OXHAN["cta"]["text"]


def _base() -> dict:
    return json.loads(FIXTURE.read_text())


def _brief(*, ref: str, pattern: str, hook: str, transcript: str, setting: str = "", beats: int | None = None,
           language: str = "en") -> CloneBrief:
    data = _base()
    data["source"] = {**data["source"], "source_ref": f"platform:tiktok:{ref}", "language": language,
                      "url": f"https://www.tiktok.com/@{ref}/video/1"}
    data["hook"] = {**data["hook"], "pattern": pattern, "summary": f"close shot, caption '{hook}'"}
    data["transcript"] = transcript
    data["setting"] = setting
    words = transcript.split()
    rows = data["beats"]
    if beats:
        rows = [{**rows[1], "index": i, "start_s": i * 1.0, "end_s": i * 1.0 + 1.0,
                 "role": "hook" if i == 0 else "setup"} for i in range(beats)]
        rows[-1] = {**rows[-1], "shot_type": "product_card", "role": "cta"}
        data["source"]["duration_s"] = float(beats)
    for i, b in enumerate(rows):
        chunk = " ".join(words[i * 3:i * 3 + 3]) or "mm"
        b["line"] = chunk
        b["on_screen_text"] = hook if i == 0 else chunk
    data["beats"] = rows
    data["pacing"]["beat_count"] = len(rows)
    return CloneBrief.model_validate(data)


RENT = _brief(ref="rentguy", pattern="price_shock", hook="rent is 40000 lira now",
              transcript="my rent went up again and the landlord wants dollars now the price of everything is insane")
GRANNY = _brief(ref="nenegram", pattern="question", hook="why does my grandmother know everything?",
                transcript="my grandmother called my mother who called my aunt the whole family knows before me",
                setting="apartment living room")
TRAFFIC = _brief(ref="dolmusking", pattern="pov", hook="POV: the dolmus driver is your therapist",
                 transcript="pov you take the dolmus in traffic and the driver asks about your breakup on the bus")


# --------------------------------------------------------------------------- 1. template writer
def _lines(plan: dict) -> list[str]:
    return [ln["text"] for ln in plan["lines"] if ln["id"] != "cta"]


def test_three_different_links_get_three_different_plans():
    plans = [rewrite.build_plan(b, OXHAN, variation="a", options=CloneOptions()) for b in (RENT, GRANNY, TRAFFIC)]
    premises = {p["clone"]["premise"] for p in plans}
    sets = {p["set"] for p in plans}
    hooks = {_lines(p)[0] for p in plans}
    assert len(premises) == 3 and len(hooks) == 3
    assert len(sets) >= 2  # the set follows each link's topic/setting, not always the balcony
    assert [p["clone"]["topic"] for p in plans] == ["money", "family", "transport"]
    for a in range(3):
        for b in range(a + 1, 3):
            assert not set(_lines(plans[a])) & set(_lines(plans[b])), "two links share a written line"
    assert plans[2]["set"] == OXHAN["sets"]["street"]["text"]  # a dolmus story is not on a balcony
    assert plans[1]["set"] == OXHAN["sets"]["balcony"]["text"]  # a family story at home
    for p in plans:
        assert ipguard.check_plan(p, banned_terms=OXHAN["banned_design"], source_texts=[],
                                  allow_lines=[CTA]) == []
        stills = " ".join(s["prompt"] for s in p["stills"])
        if p["set"] != OXHAN["sets"]["balcony"]["text"]:
            assert "balcony" not in stills.lower() and "railing" not in stills.lower()


def test_hook_type_shapes_the_opening_line():
    plans = {b.hook.pattern: rewrite.build_plan(b, OXHAN, variation="a", options=CloneOptions())
             for b in (RENT, GRANNY, TRAFFIC)}
    assert _lines(plans["question"])[0].endswith("?")
    assert _lines(plans["pov"])[0].lower().startswith("pov")
    assert any(ch.isdigit() for ch in _lines(plans["price_shock"])[0])


@pytest.mark.parametrize("brief", [RENT, GRANNY, TRAFFIC])
def test_no_line_repeats_within_a_plan_even_with_many_beats(brief):
    long = _brief(ref=brief.source.source_ref.split(":")[-1] + "x", pattern=brief.hook.pattern,
                  hook=brief.beats[0].on_screen_text, transcript=brief.transcript, beats=24)
    for v in ("a", "b", "c"):
        lines = _lines(rewrite.build_plan(long, OXHAN, variation=v, options=CloneOptions()))
        assert len(lines) >= 20
        assert len(lines) == len({ln.lower() for ln in lines}), lines


def test_variations_of_one_link_differ_and_stay_on_topic():
    plans = rewrite.build_plans(GRANNY, OXHAN, CloneOptions(variations=3))
    assert len({_lines(p)[0] for p in plans}) == 3
    assert {p["clone"]["topic"] for p in plans} == {"family"}


def test_template_lines_never_use_the_sources_brand_terms():
    ctx = scriptbank.BriefContext(topic="fashion", pattern="statement", seed=3, avoid_terms=("hoodie", "drop"))
    slots = [scriptbank.Slot(i, "hook" if i == 0 else "setup", "close", 2.0) for i in range(12)]
    lines = scriptbank.fallback_lines(slots, "statement", "a", context=ctx)
    assert not [ln.text for ln in lines if "hoodie" in ln.text.lower() or " drop" in ln.text.lower()]


# --------------------------------------------------------------------------- 2. whisper language
class _FakeWhisper:
    cached = {"small.en", "base.en", "small"}
    made: list[tuple[str, dict]] = []

    def __init__(self, name, **kw):
        if kw.get("local_files_only") and name not in self.cached:
            raise RuntimeError("not cached")
        _FakeWhisper.made.append((name, kw))
        self.name = name

    def transcribe(self, path, language=None, **kw):
        self.language_arg = language
        _FakeWhisper.last = (self.name, language)
        seg = types.SimpleNamespace(start=0.0, end=1.5, text=" Kira yine artti abi ")
        return iter([seg]), types.SimpleNamespace(language=language or "tr")


@pytest.fixture()
def fake_whisper(monkeypatch):
    _FakeWhisper.made = []
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=_FakeWhisper))
    monkeypatch.delenv("ADCLONE_WHISPER_MODEL", raising=False)
    return _FakeWhisper


def test_whisper_never_uses_an_english_only_model_and_auto_detects(fake_whisper):
    segs, lang = vision.transcribe("clip.mp4")
    assert fake_whisper.last == ("small", None)  # multilingual model, language left to auto-detect
    assert not any(name.endswith(".en") for name, _ in fake_whisper.made)
    assert lang == "tr" and segs[0].text == "Kira yine artti abi"


def test_whisper_only_english_models_cached_downloads_multilingual(fake_whisper, monkeypatch):
    fake_whisper.cached = {"small.en", "base.en"}
    try:
        vision.transcribe("clip.mp4")
        assert fake_whisper.last[0] == "small"
        monkeypatch.setenv("ADCLONE_WHISPER_DOWNLOAD", "0")
        assert vision.transcribe("clip.mp4") is None  # never fall back to an English-only model
    finally:
        fake_whisper.cached = {"small.en", "base.en", "small"}


def test_whisper_uses_a_given_language_and_ignores_original(fake_whisper):
    vision.transcribe("clip.mp4", language="tr")
    assert fake_whisper.last == ("small", "tr")
    vision.transcribe("clip.mp4", language="original")
    assert fake_whisper.last == ("small", None)
    monkeypatch_model = "ADCLONE_WHISPER_MODEL"
    assert vision.whisper_model_name({monkeypatch_model: "medium.en"}) == "medium"


def test_observe_passes_the_language_to_the_transcriber(monkeypatch, tmp_path):
    seen = {}

    def transcriber(path, language=None):
        seen["language"] = language
        return [vision.Segment(0.0, 1.0, "merhaba")], "tr"

    monkeypatch.setattr(ingest.media, "probe", lambda p: types.SimpleNamespace(duration_s=2.0, width=720,
                                                                               height=1280, has_audio=True))
    monkeypatch.setattr(ingest.media, "detect_shots", lambda p, d: [])
    monkeypatch.setattr(ingest, "_captions", lambda p, d, w: ([], True))
    monkeypatch.setattr(ingest.media, "audio_envelope", lambda p: [])
    monkeypatch.setattr(ingest.media, "onsets_from_envelope", lambda e: [])
    obs = ingest.observe("x.mp4", str(tmp_path), url="https://www.tiktok.com/@a/video/1", platform="tiktok",
                         source_ref="r", transcriber=transcriber, language="tr")
    assert seen["language"] == "tr" and obs.language == "tr"


# --------------------------------------------------------------------------- 3. brand names
def test_brand_terms_from_handle_ocr_and_transcript():
    terms = brandterms.extract(
        url="https://www.tiktok.com/@velvele.official/video/1",
        ocr_texts=["fiyatlar yine uçtu", "VELVELE", "use code ADA10 at Moda Ruya"],
        overlay_texts=["VELVELE"],
        transcript="Bu sezon Velvele ile tanıştım, Moda Rüya da güzel ama Velvele başka. Check out @kumashouse",
    )
    low = {t.lower() for t in terms}
    assert "velvele" in low and "kumashouse" in low
    assert "moda ruya" in low or "moda rüya" in low
    assert "official" not in low and "bu" not in low and "check" not in low


def test_brief_avoid_terms_include_the_extracted_brand_and_block_the_script():
    caps = tuple(CaptionObs(at_s=0.25 + i * 0.5, text="VELVELE", y_center=0.55 + (i % 3) * 0.03, x_center=0.5)
                 for i in range(20))
    caps += tuple(CaptionObs(at_s=0.25 + i * 0.5, text=t, y_center=0.82) for i, t in
                  enumerate(["fiyatlar yine uçtu"] * 4 + ["kira bile artmış"] * 4))
    obs = Observations(url="https://www.tiktok.com/@modaevi/video/1", platform="tiktok", source_ref="platform:tiktok:mv1",
                       duration_s=10.0, width=720, height=1280, shots=(ShotObs(0.0, 10.0, 0.2),), captions=caps,
                       speech=(SpeechObs(0.0, 10.0, "Velvele sweatshirt aldım, fiyatlar uçtu"),), language="tr")
    brief = analyze.heuristic_brief(obs)
    low = {t.lower() for t in brief.source.avoid_terms}
    assert {"velvele", "modaevi"} <= low
    plan = rewrite.build_plan(brief, OXHAN, variation="a", options=CloneOptions())
    assert "velvele" not in json.dumps(plan).lower()
    bad = {**plan, "lines": [*plan["lines"], {"id": "x", "speaker": "H", "text": "Velvele is great."}]}
    assert ipguard.check_plan(bad, banned_terms=brief.source.avoid_terms, source_texts=[])
    spaced = {**plan, "lines": [*plan["lines"], {"id": "y", "speaker": "H", "text": "Children of Khan rocks."}]}
    assert ipguard.check_plan(spaced, banned_terms=["childrenofkhan"], source_texts=[])


def test_llm_lines_with_a_source_brand_fall_back_to_the_template_writer():
    brief = RENT.model_copy(update={"source": RENT.source.model_copy(update={"avoid_terms": ["velvele"]})})
    slots, _ = rewrite.story_slots(brief)

    def brand_llm(prompt):
        assert "velvele" in prompt.lower()  # the writer is told the names to avoid
        return json.dumps({"lines": [{"slot": s.index, "speaker": "H", "text": f"Velvele line {i}."}
                                     for i, s in enumerate(slots)]})

    plan = rewrite.build_plan(brief, OXHAN, variation="a", options=CloneOptions(), llm=brand_llm)
    assert plan["clone"]["writer"] == "bank" and "velvele" not in json.dumps(plan["lines"]).lower()


# --------------------------------------------------------------------------- 4. OCR captions
def _obs(t, text, y, x=0.5):
    return CaptionObs(at_s=t, text=text, y_center=y, x_center=x)


def test_shirt_print_that_moves_with_the_subject_is_not_a_caption():
    caps = []
    for i in range(16):  # 8 s of a talking head; the print sways with the body
        t = 0.25 + i * 0.5
        caps.append(_obs(t, "VERY TURKISH TIME", 0.58 + 0.05 * ((i % 4) - 1.5), 0.5 + 0.03 * (i % 3)))
    for i, txt in enumerate(["eggs are twelve", "eggs are twelve", "rent went up", "rent went up",
                             "landlord texted", "landlord texted", "ugh bro", "ugh bro"]):
        caps.append(_obs(0.25 + i * 0.5, txt, 0.84))
    tracks = analyze.text_tracks(tuple(caps), 0.5)
    shirt = next(tr for tr in tracks if tr.text.startswith("VERY"))
    assert not analyze.is_caption_track(shirt, 8.0, 0.5)
    runs = analyze.caption_runs(tuple(caps), 0.5, 8.0)
    texts = [r[2] for r in runs if r[2]]
    assert texts == ["eggs are twelve", "rent went up", "landlord texted", "ugh bro"]
    assert all("TURKISH" not in t for t in texts)


def test_static_print_on_screen_the_whole_video_is_not_a_caption():
    caps = [_obs(0.25 + i * 0.5, "CLUB NAME 1987", 0.5) for i in range(20)]
    caps += [_obs(0.25 + i * 0.5, txt, 0.8) for i, txt in enumerate(["so i quit", "so i quit", "and left", "and left"])]
    runs = analyze.caption_runs(tuple(caps), 0.5, 10.0)
    assert [r[2] for r in runs if r[2]] == ["so i quit", "and left"]


def test_captions_need_the_caption_zone_and_more_than_one_frame():
    caps = (_obs(0.25, "tiktok @someone", 0.97), _obs(0.75, "tiktok @someone", 0.97),  # watermark strip
            _obs(1.25, "random sign", 0.3),  # one frame, nothing else in that lane
            _obs(1.75, "real caption", 0.8), _obs(2.25, "real caption", 0.8))
    runs = analyze.caption_runs(caps, 0.5, 3.0)
    assert [r[2] for r in runs if r[2]] == ["real caption"]


def test_word_by_word_captions_in_one_lane_still_count():
    words = ["prices", "went", "crazy", "again", "this", "year"]
    caps = tuple(_obs(0.25 + i * 0.5, w, 0.8) for i, w in enumerate(words))
    runs = analyze.caption_runs(caps, 0.5, 3.0)
    assert [r[2] for r in runs if r[2]] == words
