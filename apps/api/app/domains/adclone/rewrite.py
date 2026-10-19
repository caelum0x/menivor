"""Clone brief + product preset -> episode plan(s) in the ``make_episode.py`` YAML format.

What carries over from the source: the hook position and pattern, the order and framing of the
beats, which beats are talk vs insert, and the pacing (cut tightness, insert lengths). What never
carries over: characters, footage, audio, voice, wording (see :mod:`ipguard`).

Coverage follows the episode pipeline: one talk clip per (speaker, framing) setup, each
character's lines recorded together and cut between pauses; inserts are still push-ins; one
payoff shot ends on the brand's spoken CTA.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass

from . import ipguard
from .captions import style_from_brief
from .presets import public_view
from .schemas import CloneBrief
from .scriptbank import VARIATIONS, Line, Slot, fallback_lines, llm_lines
from .storyline import Storyline, storyline

ASPECTS = ("9:16", "16:9")
CANVAS = {"9:16": (1080, 1920), "16:9": (1920, 1080)}  # same canvases as assemble.CANVAS
CAPTION_TOP = {"9:16": 230, "16:9": 120}  # payoff caption y on that canvas (make_episode cap_y)
TALK_DUR = (4, 7)
PAYOFF_DUR = (5, 8)
TALK_TAIL = 0.4
LEAD = 0.25
GAP = 0.3
MAX_SHOT_SPEECH_S = 6.2
EPISODE_BASE = 80
_PAYOFF_TEXT = re.compile(r"time in my life|get yours|link in bio|shop now|order now", re.I)


@dataclass(frozen=True)
class CloneOptions:
    variations: int = 1
    aspect: str = "9:16"
    language: str = "original"
    target_seconds: int = 30
    set_key: str = ""
    episode_base: int = EPISODE_BASE

    def checked(self) -> "CloneOptions":
        if not 1 <= self.variations <= 3:
            raise ValueError("variations is 1, 2 or 3")
        if self.aspect not in ASPECTS:
            raise ValueError("aspect is 9:16 or 16:9")
        if not 25 <= self.target_seconds <= 35:
            raise ValueError("the episode pipeline renders 25-35 s cuts (30 s default)")
        if not 1 <= self.episode_base <= 96:
            raise ValueError("episode_base is 1..96")
        return self


def est_line_seconds(text: str, speed: float = 1.0) -> float:
    """Same estimate as work/vtt/cost.py (fitted on the EP03b ElevenLabs takes)."""
    letters = len(re.findall(r"[A-Za-z0-9]", text))
    breaks = len(re.findall(r"[.?!,;:](?=\s|$)", text.replace("...", "…")))
    secs = 0.06 * letters + 0.12 * breaks + 0.45 * text.count("...")
    return round(secs * 1.1 / max(speed, 0.5) + 0.05, 2)


def story_slots(brief: CloneBrief) -> tuple[list[Slot], list[int]]:
    """(talk slots, insert beat indexes). Product cards and the source's own payoff become our payoff."""
    slots, inserts = [], []
    for b in brief.beats:
        text = b.on_screen_text or b.line
        if b.shot_type == "product_card" or b.role in ("cta", "payoff") or _PAYOFF_TEXT.search(text):
            continue
        if text.strip():
            slots.append(Slot(b.index, b.role or "setup", "wide" if b.framing == "wide" else "close", b.duration_s))
        else:
            inserts.append(b.index)
    if not slots:
        first = brief.beats[0]
        slots.append(Slot(first.index, "hook", "close", first.duration_s))
    return slots, inserts


def pacing_profile(brief: CloneBrief) -> dict[str, float]:
    fast = brief.pacing.avg_beat_s < 2.2
    return {"pre": 0.15 if fast else 0.25, "post": 0.2 if fast else 0.35, "hold": 0.5 if fast else 0.8}


def _uses_banned(lines: list[Line], banned: tuple[str, ...]) -> bool:
    return any(ipguard._term_hit(ln.text, t) for ln in lines for t in banned if t)


def _variation_lines(brief: CloneBrief, preset: dict, slots: list[Slot], variation: str, language: str,
                     llm: Callable[[str], str] | None, source_texts: list[str],
                     story: Storyline) -> tuple[list[Line], str, str]:
    """(lines, writer, note). The note says why the template writer was used, when it was."""
    from .relay_writer import FAILED_NOTE, NOT_CONFIGURED_NOTE

    allow = [preset["cta"]["text"]]
    banned = story.context.avoid_terms
    if llm is None:
        note = NOT_CONFIGURED_NOTE
    else:
        got = llm_lines(slots, llm, pattern=brief.hook.pattern, hook_summary=brief.hook.summary, preset=preset,
                        variation=variation, language=language, avoid_text=" ".join(source_texts),
                        avoid_terms=tuple(brief.source.avoid_terms), premise=story.premise)
        texts = [ln.text for ln in got or []]
        if got and len(set(texts)) == len(texts) and not _uses_banned(got, banned) \
                and not ipguard.copied_lines(texts, source_texts, allow):
            return got, "llm", ""
        note = FAILED_NOTE
    if language not in ("en", ""):
        note += f"; the template lines are English, not {language!r}"
    return fallback_lines(slots, brief.hook.pattern, variation, context=story.context), "bank", note


def _group_shots(lines: list[tuple[str, Line, str]], speeds: dict[str, float]) -> list[dict]:
    """[(line_id, Line, framing)] -> coverage groups per (speaker, framing), split by speech length."""
    groups: list[dict] = []
    open_by_key: dict[tuple[str, str], dict] = {}
    for lid, ln, framing in lines:
        key = (ln.speaker, framing)
        secs = est_line_seconds(ln.text, speeds.get(ln.speaker, 1.0))
        g = open_by_key.get(key)
        if g is None or g["speech"] + GAP + secs > MAX_SHOT_SPEECH_S:
            g = {"speaker": ln.speaker, "framing": framing, "lines": [], "speech": 0.0}
            groups.append(g)
            open_by_key[key] = g
        g["speech"] += secs + (GAP if g["lines"] else 0.0)
        g["lines"].append(lid)
    return groups


def _dur(speech: float, lo_hi: tuple[int, int], lead: float = LEAD) -> int:
    return int(min(max(math.ceil(lead + speech + TALK_TAIL), lo_hi[0]), lo_hi[1]))


# Where the hero stands and where the print insert sits, per preset set (the old prompts always
# said "balcony railing" even on the street or studio set).
SET_PROPS = {
    "balcony": ("leans on the railing", "folded on the balcony ledge next to a tulip glass of red tea"),
    "street": ("leans against the bakkal's fruit crates", "folded on a fruit crate outside the bakkal"),
    "studio": ("stands in the hard spotlight", "folded on a glossy plinth under the spotlight"),
}
DEFAULT_PROPS = ("stands relaxed in the set", "folded neatly in the set")


def _still_prompt(kind: str, speaker: str, ar: str, set_key: str = "balcony") -> str:
    pose, prop = SET_PROPS.get(set_key, DEFAULT_PROPS)
    shape = "Vertical 9:16" if ar == "9:16" else "Horizontal 16:9"
    who = {"H": "HERO", "O": "OXHAN", "N": "the side character"}.get(speaker, "HERO")
    desc = "{DESC_" + speaker + "}"
    if kind == "set":
        return (f"{shape} establishing shot, cinematic cutscene still, no people. {{SET}} The reference image is ONLY "
                "for the rendering style. {LOOK} {NOTEXT}")
    if kind == "wide":
        return (f"{shape} wide shot, full body, cinematic cutscene still. {{SET}} {who} (exactly the man in the first "
                f"reference image) {pose}, relaxed, looking at camera; chest print visible. {desc}. "
                "He wears {SWEAT}. {LOOK} {NOTEXT}")
    if kind == "insert":
        return (f"{shape} insert close-up, cinematic cutscene still: the sweatshirt chest print from the print "
                f"reference, {prop}, warm light. {{SET}} {{LOOK}} {{NOTEXT}}")
    return (f"{shape} medium close-up, chest-up, cinematic cutscene still. {{SET}} {who} (exactly the man in the "
            f"first reference image) faces the camera; hands below the chest so the print is fully visible and "
            f"legible. {desc}. He wears {{SWEAT}}. {{LOOK}} {{NOTEXT}}")


def _move_note(move: str) -> str:
    return {"push_in": "Slow push-in", "pull_out": "Slow pull-out", "pan": "Gentle pan",
            "handheld": "Light handheld drift"}.get(move, "Locked")


def build_plan(brief: CloneBrief, preset: dict, *, variation: str, options: CloneOptions,
               llm: Callable[[str], str] | None = None) -> dict:
    opts = options.checked()
    vi = VARIATIONS.index(variation)
    slots, inserts = story_slots(brief)
    source_texts = [t for b in brief.beats for t in (b.line, b.on_screen_text) if t] + [brief.transcript]
    language = brief.source.language if opts.language == "original" else opts.language
    story = storyline(brief, preset)
    written, writer, writer_note = _variation_lines(brief, preset, slots, variation, language, llm, source_texts,
                                                    story)
    beats = {b.index: b for b in brief.beats}
    set_key = opts.set_key or story.set_key or preset["default_set"]
    if set_key not in preset["sets"]:
        raise ValueError(f"set is one of {', '.join(preset['sets'])}")
    ar = opts.aspect
    lines_raw, tagged = [], []
    for n, ln in enumerate(written, start=1):
        lid = f"l{n}"
        lines_raw.append({"id": lid, "speaker": ln.speaker, "text": ln.text})
        slot = next(s for s in slots if s.index == ln.slot)
        tagged.append((lid, ln, slot.framing if ln.speaker == "H" else "close"))
    cta = preset["cta"]
    lines_raw.append({"id": "cta", "speaker": cta["speaker"], "split": True, "speed": 1.2, "text": cta["text"],
                      "tts": cta["tts"]})
    # Source wide beats are narration over a wide picture: our line is voiced over a wide still push-in
    # ($0 video); close/medium beats become lip-synced talk clips.
    voiced_over = [t for t in tagged if t[2] == "wide"]
    speeds = {k: float(c.get("speed", 1.0)) for k, c in preset["characters"].items()}
    groups = _group_shots([t for t in tagged if t[2] != "wide"], speeds)
    stills = [{"id": "s0", "refs": ["@H"], "ar": ar, "prompt": _still_prompt("set", "H", ar, set_key)}]
    still_for: dict[tuple[str, str], str] = {}
    setups = [(g["speaker"], g["framing"]) for g in groups] + [(ln.speaker, "wide") for _, ln, _ in voiced_over]
    for key in setups:
        if key not in still_for:
            sid = f"s{len(stills)}"
            ref = f"@{key[0]}" if key[0] in ("H", "O") else "s0"
            refs = [ref, "@print", "s0"] if ref != "s0" else ["s0", "@print"]
            stills.append({"id": sid, "refs": refs, "ar": ar,
                           "prompt": _still_prompt("wide" if key[1] == "wide" else "close", key[0], ar, set_key)})
            still_for[key] = sid
    insert_still = None
    if inserts:
        insert_still = f"s{len(stills)}"
        stills.append({"id": insert_still, "refs": ["@print", "s0"], "ar": ar,
                       "prompt": _still_prompt("insert", "H", ar, set_key)})
    line_beat = {lid: beats[ln.slot] for lid, ln, _ in tagged}
    shots, line_shot = [], {}
    for i, g in enumerate(groups, start=1):
        sid = f"v{g['speaker']}{i}"
        first_beat = line_beat[g["lines"][0]]
        speaker_ref = f"@{g['speaker']}" if g["speaker"] in ("H", "O") else None
        refs = [still_for[(g["speaker"], g["framing"])]] + ([speaker_ref] if speaker_ref else []) + ["@print"]
        shots.append({"id": sid, "kind": "talk", "framing": g["framing"], "dur": _dur(g["speech"], TALK_DUR),
                      "lead": LEAD, "gap": GAP, "lines": list(g["lines"]), "refs": refs,
                      "prompt": f"{_move_note(first_beat.camera_move)} {('wide' if g['framing'] == 'wide' else 'medium close-up')} "
                                "matching the reference still. He says each line straight to camera, natural "
                                "pauses between lines, small hand gestures below the chest print.",
                      "audio": "quiet ambience"})
        for lid in g["lines"]:
            line_shot[lid] = sid
    pay_still = still_for.get(("H", "close")) or next(iter(still_for.values()), "s0")
    pay_speech = est_line_seconds(cta["tts"], 1.2 * speeds.get(cta["speaker"], 1.0))
    shots.append({"id": "vP", "kind": "payoff", "dur": _dur(pay_speech, PAYOFF_DUR, 0.3), "lead": 0.3,
                  "lines": ["cta"], "refs": [pay_still, "@H", "@print"],
                  "prompt": "Slow continuous push-in from medium to medium close-up; the chest print stays in frame "
                            "and legible for the first half. He looks straight into the camera, warm and a little "
                            "smug, says the whole line in one take, small nod after the first sentence, then holds.",
                  "audio": "soft ambience tail"})
    pace = pacing_profile(brief)
    scale = opts.target_seconds / max(brief.source.duration_s, 1.0)
    edit, beat_map = [], []
    by_beat: dict[int, list[str]] = {}
    line_speaker = {lid: ln.speaker for lid, ln, _ in tagged}
    for lid, ln, _ in tagged:
        by_beat.setdefault(ln.slot, []).append(lid)
    for b in brief.beats:
        if b.index in by_beat:
            for lid in by_beat[b.index]:
                if lid in line_shot:
                    seg = {"shot": line_shot[lid], "lines": [lid], "pre": pace["pre"] if edit else 0.1,
                           "post": pace["post"], "hold": pace["hold"]}
                else:
                    ln_s = round(min(max(b.duration_s * scale, 1.0), 4.0), 2)
                    seg = {"still": still_for[(line_speaker[lid], "wide")], "lines": [lid], "len": ln_s,
                           "max": round(ln_s + 1.2, 2), "push": 1.06}
                edit.append(seg)
                beat_map.append({"source_beat": b.index, "role": b.role, "segment": len(edit) - 1, "line": lid})
        elif b.index in inserts and insert_still:
            ln_s = round(min(max(b.duration_s * scale, 0.8), 3.0), 2)
            edit.append({"still": insert_still if b.index != 0 else "s0", "len": ln_s, "max": round(ln_s + 1.0, 2),
                         "push": 1.08 if b.camera_move in ("push_in", "unknown", "static") else 1.04,
                         **({"optional": True} if b.index == 0 else {})})
            beat_map.append({"source_beat": b.index, "role": b.role, "segment": len(edit) - 1, "line": None})
    edit.append({"shot": "vP", "lines": ["cta"], "cap_y": CAPTION_TOP[ar], "post": 0.6, "hold": 1.2})
    beat_map.append({"source_beat": next((b.index for b in brief.beats if b.role in ("payoff", "cta")),
                                         brief.beats[-1].index), "role": "payoff", "segment": len(edit) - 1,
                     "line": "cta"})
    ep = opts.episode_base + vi
    slug_id = re.sub(r"[^a-z0-9]+", "", (brief.source.source_ref.split(":")[-1] or "src").lower())[:8]
    side = {k: {"name": c["name"], "desc": c.get("desc", ""),
                "voice": {"local": {"blend": c["voice"]["kokoro"], "speed": 1.0},
                          **({"elevenlabs": c["voice"]["elevenlabs_voice_id"]}
                             if c["voice"].get("elevenlabs_voice_id") else {})}}
            for k, c in preset["characters"].items() if k not in ("H", "O") and any(g["speaker"] == k for g in groups)}
    plan = {
        "episode": ep, "slug": f"clone-{slug_id}-{variation}", "title": f"Clone {variation.upper()} of {brief.source.platform} ad",
        "target_seconds": opts.target_seconds, "ambience": preset["sets"][set_key]["ambience"],
        "set": preset["sets"][set_key]["text"], "aspect": ar, "canvas": dict(zip(("w", "h"), CANVAS[ar])), "language": language,
        "captions": style_from_brief(brief.caption_style.model_dump(), ar),
        **({"characters": side} if side else {}),
        "lines": lines_raw, "stills": stills, "shots": shots, "edit": edit,
        "clone": {"source_ref": brief.source.source_ref, "variation": variation, "writer": writer, "writer_note": writer_note,
                  "hook_pattern": brief.hook.pattern, "keeps": brief.keeps, "beat_map": beat_map,
                  "topic": story.topic, "premise": story.premise, "set_key": set_key,
                  "product": public_view(preset)["product"], "preset": preset["id"]},
    }
    banned = list(preset.get("banned_design") or []) + list(brief.source.avoid_terms)
    ipguard.enforce(plan, banned_terms=banned, source_texts=source_texts, source_markers=[brief.source.source_ref],
                    allow_lines=[cta["text"]])
    return plan


def build_plans(brief: CloneBrief, preset: dict, options: CloneOptions,
                llm: Callable[[str], str] | None = None) -> list[dict]:
    opts = options.checked()
    return [build_plan(brief, preset, variation=v, options=opts, llm=llm) for v in VARIATIONS[:opts.variations]]
