"""Title metadata suggestions (MV16): a title, a synopsis and tags from the transcript, through Relay.

Suggestions only: the creator applies them in the studio (the normal title
edit). Lengths match the catalog limits and nothing names a tool or model.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from .subtitles import LLM, Cue, _default_llm

MAX_TRANSCRIPT_CHARS = 6000


def _json_object(raw: str) -> dict:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the answer")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("not a JSON object")
    return value


def suggest(cues: Sequence[Cue], *, current_title: str = "", llm: LLM | None = None) -> dict[str, Any]:
    from app.domains.presets_hub.catalog import vendor_hits

    transcript = " ".join(c.text for c in cues)[:MAX_TRANSCRIPT_CHARS]
    if not transcript:
        raise ValueError("there is no speech to describe")
    prompt = ("Write catalog details for this video from its transcript. Answer with only JSON: "
              '{"title": "<at most 80 characters>", "synopsis": "<2-3 plain sentences>", '
              '"tags": ["<up to 8 short topic tags>"]}. Do not invent facts that are not in the transcript. '
              f"Current title: {current_title!r}.\nTranscript: {transcript}")
    data = _json_object((llm or _default_llm)(prompt))
    title = " ".join(str(data.get("title") or "").split())[:80]
    synopsis = " ".join(str(data.get("synopsis") or "").split())[:600]
    tags = [" ".join(str(t).split())[:30].lower() for t in (data.get("tags") or []) if str(t).strip()][:8]
    clean_tags = [t for t in dict.fromkeys(tags) if not vendor_hits(t)]
    if not title or vendor_hits(f"{title} {synopsis}"):
        raise ValueError("the suggestion was not usable")
    return {"title": title, "synopsis": synopsis, "tags": clean_tags}


__all__ = ["suggest"]
