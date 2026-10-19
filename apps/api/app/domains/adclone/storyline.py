"""Brief -> this link's story: topic, premise, set and writer context (pure, $0, no LLM).

The template writer used to give every link the same story on the same balcony. Here the
link's own brief decides: what is talked about (transcript, captions, hook), the hook device,
the setting the analysis saw, and a per-link seed so two links on one topic still differ.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .schemas import CloneBrief
from .scriptbank import BriefContext
from .topicbank import SETTING_WORDS, TOPICS

_PATTERN_LABEL = {"price_shock": "a price-shock opener", "question": "a question opener", "pov": "a POV opener",
                  "bold_claim": "a bold-claim opener", "list": "a list opener", "statement": "a deadpan statement"}


@dataclass(frozen=True)
class Storyline:
    topic: str
    premise: str
    set_key: str
    context: BriefContext


def _fold(text: str) -> str:
    return (text or "").replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")


def _hits(text: str, words: tuple[str, ...]) -> int:
    n = 0
    for w in words:
        w = _fold(w)
        if not w:
            continue
        if w.isalpha() and " " not in w:
            n += len(re.findall(r"(?<![\w])" + re.escape(w) + r"(?![\w])", text))
        else:
            n += text.count(w)
    return n


def link_seed(brief: CloneBrief) -> int:
    key = f"{brief.source.source_ref}|{brief.source.url}"
    return int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16) % 9973


def topic_of(brief: CloneBrief) -> str:
    text = _fold(" ".join([brief.transcript, brief.hook.summary, brief.setting,
                           *(b.on_screen_text for b in brief.beats), *(b.line for b in brief.beats)]))
    scores = {name: _hits(text, tuple(t["keywords"])) for name, t in TOPICS.items() if t["keywords"]}  # type: ignore[arg-type]
    if brief.hook.pattern == "price_shock":
        scores["money"] = scores.get("money", 0) + 1
    best = max(scores.items(), key=lambda kv: (kv[1], kv[0] == "money"), default=("everyday", 0))
    return best[0] if best[1] > 0 else "everyday"


def set_for(brief: CloneBrief, topic: str, set_keys: list[str], seed: int) -> str:
    """The brief's own setting first, then the topic's natural place, then a per-link pick."""
    if not set_keys:
        return ""
    setting = _fold(brief.setting)
    if setting:
        scored = {k: _hits(setting, words) for k, words in SETTING_WORDS.items() if k in set_keys}
        best = max(scored.items(), key=lambda kv: kv[1], default=("", 0))
        if best[1] > 0:
            return best[0]
    natural = str(TOPICS.get(topic, {}).get("set") or "")
    if natural in set_keys:
        return natural
    return set_keys[seed % len(set_keys)]


def storyline(brief: CloneBrief, preset: dict) -> Storyline:
    seed = link_seed(brief)
    topic = topic_of(brief)
    set_key = set_for(brief, topic, list(preset.get("sets") or {}), seed)
    beats = len([b for b in brief.beats if b.role not in ("cta",)])
    premise = (f"{TOPICS[topic]['premise']} Opens with {_PATTERN_LABEL.get(brief.hook.pattern, 'a hook')}, "
               f"{beats} beats, set: {set_key or 'default'}.")
    source_texts = tuple(t for b in brief.beats for t in (b.line, b.on_screen_text) if t) + (brief.transcript,)
    banned = tuple(brief.source.avoid_terms) + tuple(preset.get("banned_design") or [])
    ctx = BriefContext(topic=topic, pattern=brief.hook.pattern, seed=seed, avoid_terms=banned,
                       source_texts=source_texts)
    return Storyline(topic=topic, premise=premise, set_key=set_key, context=ctx)


__all__ = ["Storyline", "link_seed", "set_for", "storyline", "topic_of"]
