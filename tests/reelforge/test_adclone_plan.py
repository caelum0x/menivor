"""Ad Clone: brief schema, plan generation (make_episode format), IP-safety guard, presets."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domains.adclone import ipguard, planschema, presets, rewrite, scriptbank
from app.domains.adclone.rewrite import CloneOptions
from app.domains.adclone.schemas import CloneBrief

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "adclone" / "brief-tiktok-price-shock.json"
OXHAN = presets.load("oxhan")
CTA = OXHAN["cta"]["text"]


@pytest.fixture()
def brief() -> CloneBrief:
    return CloneBrief.model_validate(json.loads(FIXTURE.read_text()))


def _source_texts(b: CloneBrief) -> list[str]:
    return [t for x in b.beats for t in (x.line, x.on_screen_text) if t] + [b.transcript]


# --------------------------------------------------------------------------- brief schema
def test_fixture_brief_is_valid(brief):
    assert brief.hook.pattern == "price_shock" and brief.hook.end_s <= 3.0
    assert brief.beats[0].role == "hook" and brief.beats[-1].shot_type == "product_card"
    assert brief.pacing.beat_count == len(brief.beats) or brief.pacing.beat_count >= 1


def test_brief_rejects_out_of_order_beats(brief):
    data = brief.model_dump()
    data["beats"][1]["index"] = 5
    with pytest.raises(ValidationError):
        CloneBrief.model_validate(data)


def test_brief_rejects_long_hook_and_inverted_beat(brief):
    data = brief.model_dump()
    data["hook"]["end_s"] = 6.0
    with pytest.raises(ValidationError):
        CloneBrief.model_validate(data)
    data = brief.model_dump()
    data["beats"][0]["end_s"] = 0.0
    with pytest.raises(ValidationError):
        CloneBrief.model_validate(data)


# --------------------------------------------------------------------------- plan generation
def test_three_variations_are_valid_episode_plans(brief):
    plans = rewrite.build_plans(brief, OXHAN, CloneOptions(variations=3))
    assert [p["clone"]["variation"] for p in plans] == ["a", "b", "c"]
    assert len({p["episode"] for p in plans}) == 3 and len({p["slug"] for p in plans}) == 3
    hooks = {p["lines"][0]["text"] for p in plans}
    assert len(hooks) == 3  # each variation opens differently
    for p in plans:
        assert planschema.validate(p, cta_text=CTA) == []
        assert p["edit"][-1]["shot"] == "vP" and p["lines"][-1]["text"] == CTA
        assert p["target_seconds"] == 30 and p["aspect"] == "9:16"
        assert all(s["ar"] == "9:16" for s in p["stills"])


def test_plan_keeps_source_structure(brief):
    plan = rewrite.build_plan(brief, OXHAN, variation="a", options=CloneOptions())
    beat_map = plan["clone"]["beat_map"]
    # The hook is first, the source's later beats keep their order, the payoff closes.
    assert beat_map[0]["role"] == "hook" and beat_map[-1]["role"] == "payoff"
    order = [m["source_beat"] for m in beat_map[:-1]]
    assert order == sorted(order)
    # Source wide narration beats become voice-over on a wide still; close beats become talk clips.
    wide = {b.index for b in brief.beats if b.framing == "wide" and b.role not in ("payoff", "cta")}
    for m, seg in zip(beat_map, plan["edit"]):
        if m["source_beat"] in wide and m["line"]:
            assert "still" in seg and seg["lines"] == [m["line"]]
    assert plan["edit"][0]["pre"] <= 0.15  # the hook line lands straight away
    assert plan["clone"]["hook_pattern"] == "price_shock"


def test_plan_has_brand_cast_and_no_source_identity(brief):
    plan = rewrite.build_plan(brief, OXHAN, variation="b", options=CloneOptions())
    speakers = {ln["speaker"] for ln in plan["lines"]}
    assert speakers <= {"H", "O"} and "O" in speakers
    refs = {r for s in plan["shots"] for r in s["refs"]}
    assert {"@H", "@print"} <= refs
    text = json.dumps(plan).lower()
    for term in ("goggles", "white hair", "dante", "childrenofkhan", "children of khan", "chinese"):
        assert term not in text
    assert ipguard.copied_lines([ln["text"] for ln in plan["lines"]], _source_texts(brief), [CTA]) == []


def test_aspect_language_and_episode_options(brief):
    plan = rewrite.build_plan(brief, OXHAN, variation="a",
                              options=CloneOptions(aspect="16:9", language="tr", episode_base=40))
    assert plan["aspect"] == "16:9" and plan["language"] == "tr" and plan["episode"] == 40
    assert all(s["ar"] == "16:9" for s in plan["stills"])
    assert "Horizontal 16:9" in plan["stills"][0]["prompt"]
    same = rewrite.build_plan(brief, OXHAN, variation="a", options=CloneOptions(language="original"))
    assert same["language"] == "en"


@pytest.mark.parametrize("opts", [dict(variations=4), dict(aspect="1:1"), dict(target_seconds=15),
                                  dict(episode_base=99)])
def test_bad_options_are_refused(brief, opts):
    with pytest.raises(ValueError):
        rewrite.build_plans(brief, OXHAN, CloneOptions(**opts))


def test_talk_shot_durations_fit_the_lines(brief):
    plan = rewrite.build_plan(brief, OXHAN, variation="a", options=CloneOptions())
    lines = {ln["id"]: ln for ln in plan["lines"]}
    for s in plan["shots"]:
        speed = OXHAN["characters"][lines[s["lines"][0]]["speaker"]]["speed"] * lines[s["lines"][0]].get("speed", 1.0)
        need = s["lead"] + sum(rewrite.est_line_seconds(lines[lid].get("tts", lines[lid]["text"]), speed)
                               for lid in s["lines"]) + 0.3 * (len(s["lines"]) - 1) + 0.4
        assert s["dur"] >= min(need, 7 if s["kind"] == "talk" else 8) - 1e-6


def test_llm_writer_is_used_when_valid_and_rejected_when_it_copies(brief):
    slots, _ = rewrite.story_slots(brief)

    def good(prompt):
        assert "never reuse any 3+ word phrase" in prompt
        return json.dumps({"lines": [{"slot": s.index, "speaker": "H", "text": f"Original line number {i}."}
                                     for i, s in enumerate(slots)]})

    plan = rewrite.build_plan(brief, OXHAN, variation="a", options=CloneOptions(), llm=good)
    assert plan["clone"]["writer"] == "llm" and plan["lines"][0]["text"] == "Original line number 0."

    def copier(prompt):
        return json.dumps({"lines": [{"slot": s.index, "speaker": "H", "text": "my landlord just texted me"}
                                     for s in slots]})

    plan = rewrite.build_plan(brief, OXHAN, variation="a", options=CloneOptions(), llm=copier)
    assert plan["clone"]["writer"] == "bank"


def test_fallback_bank_follows_roles():
    slots = [scriptbank.Slot(0, "hook", "close", 2), scriptbank.Slot(1, "setup", "wide", 2),
             scriptbank.Slot(2, "escalation", "close", 1.5), scriptbank.Slot(3, "turn", "close", 2),
             scriptbank.Slot(4, "escalation", "close", 1.4)]
    lines = scriptbank.fallback_lines(slots, "price_shock", "a")
    b = scriptbank.bank("price_shock", "a")
    assert lines[0].text == b["hook"] and lines[2].speaker == "O" and lines[3].text == b["turn"]
    assert lines[4].text in b["after"]
    assert scriptbank.bank("unknown", "c")["hook"]


# --------------------------------------------------------------------------- IP guard
@pytest.fixture()
def plan(brief):
    return rewrite.build_plan(brief, OXHAN, variation="a", options=CloneOptions())


def _check(plan, brief):
    return ipguard.check_plan(plan, banned_terms=OXHAN["banned_design"] + brief.source.avoid_terms,
                              source_texts=_source_texts(brief), source_markers=[brief.source.source_ref],
                              allow_lines=[CTA])


def test_guard_passes_generated_plan(plan, brief):
    assert _check(plan, brief) == []


@pytest.mark.parametrize("phrase", ["white-haired hero with goggles", "a RED COAT", "dressed like Dante",
                                    "Devil May Cry style", "childrenofkhan logo"])
def test_guard_rejects_source_character_design(plan, brief, phrase):
    bad = copy.deepcopy(plan)
    bad["stills"][1]["prompt"] += f" {phrase}"
    assert any("design/brand term" in p for p in _check(bad, brief))
    with pytest.raises(ipguard.IPGuardError) as exc:
        ipguard.enforce(bad, banned_terms=OXHAN["banned_design"] + brief.source.avoid_terms, source_texts=[])
    assert exc.value.status_code == 422


@pytest.mark.parametrize("ref", ["/tmp/adclone-x/source.mp4", "video-src/source.mp4", "vo/source-voice.wav",
                                 "../outside.png", "/abs/frame.jpg"])
def test_guard_rejects_source_footage_audio_and_foreign_paths(plan, brief, ref):
    bad = copy.deepcopy(plan)
    bad["shots"][0]["refs"] = [*bad["shots"][0]["refs"], ref]
    assert any("ref" in p for p in _check(bad, brief))


def test_guard_rejects_reference_to_the_source_ref(plan, brief):
    bad = copy.deepcopy(plan)
    bad["stills"][0]["refs"] = [f"stills/{brief.source.source_ref}.png"]
    assert any("source video" in p for p in _check(bad, brief))


def test_guard_rejects_cloned_voice(plan, brief):
    bad = copy.deepcopy(plan)
    bad["characters"] = {"N": {"name": "X", "voice": {"reference_audio": "source.wav"}}}
    assert any("cloned" in p for p in _check(bad, brief))


def test_guard_rejects_verbatim_and_near_verbatim_lines(plan, brief):
    bad = copy.deepcopy(plan)
    bad["lines"][1]["text"] = "My landlord just texted me."
    bad["lines"][2]["text"] = "rents up another six percent this year"
    problems = _check(bad, brief)
    assert sum("copies the source" in p for p in problems) == 2


def test_guard_allows_our_brand_line_even_if_the_source_shares_its_shape(plan, brief):
    assert ipguard.copied_lines([CTA, "You met me at a very Turkish time in my life."],
                                _source_texts(brief), [CTA]) == []


@pytest.mark.parametrize("desc", ["clone my neighbour's voice", "sounds like Morgan Freeman",
                                  "an impression of a famous actor", ""])
def test_voice_design_descriptions_must_be_original(desc):
    with pytest.raises(ipguard.IPGuardError):
        ipguard.check_voice_description(desc)
    ipguard.check_voice_description("warm deep Turkish man, late 20s, light accent")


# --------------------------------------------------------------------------- shared schema + presets
def test_planschema_catches_renderer_rule_breaks(plan):
    bad = copy.deepcopy(plan)
    bad["edit"] = bad["edit"][:-1]
    bad["shots"][0]["dur"] = 9
    bad["lines"][-1]["text"] = "Buy now."
    bad["ambience"] = "beach"
    problems = planschema.validate(bad, cta_text=CTA)
    joined = " | ".join(problems)
    for frag in ("dur must be an integer", "last edit segment", "spoken CTA", "ambience", "used 0 times"):
        assert frag in joined


def test_preset_updates_are_immutable_and_saved_to_override(tmp_path, monkeypatch):
    updated = presets.with_voice(OXHAN, "H", "AbCdEf1234567890")
    assert OXHAN["characters"]["H"]["voice"]["elevenlabs_voice_id"] == ""
    assert updated["characters"]["H"]["voice"]["elevenlabs_voice_id"] == "AbCdEf1234567890"
    with pytest.raises(presets.PresetError):
        presets.save(updated)  # no override dir configured
    monkeypatch.setenv(presets.OVERRIDE_ENV, str(tmp_path))
    path = presets.save(updated)
    assert path.parent == tmp_path
    assert presets.load("oxhan")["characters"]["H"]["voice"]["elevenlabs_voice_id"] == "AbCdEf1234567890"
    with pytest.raises(presets.PresetError):
        presets.with_voice(OXHAN, "H", "bad id!")
    with pytest.raises(presets.PresetError):
        presets.load("nike")


def test_public_view_has_no_paths():
    view = presets.public_view(OXHAN)
    assert view["end_card"] == "Get yours at oxhanatelier.com"
    assert "sheet" not in json.dumps(view)
