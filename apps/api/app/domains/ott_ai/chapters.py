"""Chapters (MV16): chosen by the model through Relay, always starting on a sentence boundary.

The model sees numbered sentences with their times and answers with a JSON
array of ``{"start": <sentence number>, "title": "..."}``. Every start must be
a real sentence number, increasing, and the first chapter starts at sentence
0; titles are short and name no tool or model. The output is a WebVTT
chapters track plus the same list as JSON for the player and the storefront.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .subtitles import LLM, Cue, _default_llm, _stamp, parse_json_array

MIN_CHAPTER_S = 30.0
MAX_CHAPTERS = 20
MAX_TITLE = 60


def choose(sentences: Sequence[Cue], *, llm: LLM | None = None) -> list[dict[str, Any]]:
    from app.domains.presets_hub.catalog import vendor_hits

    if not sentences:
        return []
    listing = "\n".join(f"{n}. [{int(s.start // 60):02d}:{int(s.start % 60):02d}] {s.text}"
                        for n, s in enumerate(sentences))
    prompt = ("Split this video into chapters for viewers. Pick the sentence that starts each chapter and give it a "
              f"short title (at most {MAX_TITLE} characters). The first chapter starts at sentence 0. At most "
              f"{MAX_CHAPTERS} chapters, each at least {int(MIN_CHAPTER_S)} seconds long. Answer with only a JSON "
              'array like [{"start": 0, "title": "..."}].\n' + listing)
    raw = parse_json_array((llm or _default_llm)(prompt))
    chapters: list[dict[str, Any]] = []
    last = -1
    for item in raw[:MAX_CHAPTERS]:
        if not isinstance(item, dict):
            continue
        try:
            start = int(item.get("start"))
        except (TypeError, ValueError):
            continue
        title = " ".join(str(item.get("title") or "").split())[:MAX_TITLE]
        if not (0 <= start < len(sentences)) or start <= last or not title or vendor_hits(title):
            continue
        if chapters and sentences[start].start - chapters[-1]["start_s"] < MIN_CHAPTER_S:
            continue
        chapters.append({"sentence": start, "start_s": round(sentences[start].start, 3), "title": title})
        last = start
    if not chapters or chapters[0]["sentence"] != 0:
        first = chapters[0]["title"] if chapters and chapters[0]["sentence"] == 0 else "Start"
        chapters = [{"sentence": 0, "start_s": round(sentences[0].start, 3), "title": first},
                    *[c for c in chapters if c["sentence"] != 0]]
    end = sentences[-1].end
    for n, chapter in enumerate(chapters):
        chapter["end_s"] = round(chapters[n + 1]["start_s"] if n + 1 < len(chapters) else end, 3)
    return chapters


def to_vtt(chapters: Sequence[dict[str, Any]]) -> str:
    blocks = ["WEBVTT", ""]
    for n, chapter in enumerate(chapters, start=1):
        blocks += [f"chapter-{n}", f"{_stamp(chapter['start_s'])} --> {_stamp(chapter['end_s'])}", chapter["title"], ""]
    return "\n".join(blocks)


__all__ = ["MAX_CHAPTERS", "MIN_CHAPTER_S", "choose", "to_vtt"]
