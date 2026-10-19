"""Text tools that spend no credits: hooks, scripts, and creative briefs from brand memory.

With Relay configured the LLM writes them (JSON, scrubbed); otherwise they are
built from the brand memory's own words, so they never invent facts.
"""

from __future__ import annotations

import json
from typing import Any

from app.domains.brand_agent import copy_rules, proposals

MAX_HOOKS = 10


def _brand(sections: dict[str, Any]) -> dict[str, Any]:
    pos = sections.get("positioning") or {}
    products = (sections.get("product") or {}).get("products") or [{}]
    voice = sections.get("voice_audience") or {}
    segments = voice.get("segments") or []
    pains = [p for seg in segments for p in seg.get("pains", [])]
    return {
        "name": pos.get("name") or products[0].get("name") or "your product",
        "one_liner": pos.get("one_liner", ""),
        "pricing": pos.get("pricing_hook", ""),
        "features": products[0].get("key_features") or [],
        "audience": segments[0]["name"] if segments else "",
        "pains": list(dict.fromkeys(pains)),
        "lines": voice.get("sample_lines") or [],
        "colors": pos.get("colors") or [],
    }


def _llm_json(llm: Any, task: str, sections: dict[str, Any]) -> dict[str, Any]:
    if llm is None:
        return {}
    prompt = f"{task}\nBRAND MEMORY: {json.dumps(sections)[:8000]}"
    return copy_rules.scrub_obj(proposals.parse_json(llm.complete(copy_rules.SYSTEM_PROMPT, prompt)))


def hooks(sections: dict[str, Any], *, count: int = 5, platform: str = "TikTok", llm: Any = None) -> list[str]:
    count = max(1, min(int(count or 5), MAX_HOOKS))
    reply = _llm_json(llm, f'Write {count} scroll-stopping {platform} hooks. JSON: {{"hooks": [..]}}', sections)
    written = [str(h).strip() for h in reply.get("hooks", []) if str(h).strip()] if reply else []
    if len(written) >= count:
        return written[:count]
    b = _brand(sections)
    pain = (b["pains"] or ["Doing everything the slow way"])[0]
    pain_lower = pain[:1].lower() + pain[1:]
    feature = (b["features"] or [b["one_liner"] or b["name"]])[0].rstrip(".")
    templates = [
        f"Tired of {pain_lower}?",
        f"{b['name']} in one line: {b['one_liner']}" if b["one_liner"] else f"Meet {b['name']}.",
        f"{b['pricing']}. That's the whole pricing page." if b["pricing"] else f"Why teams switch to {b['name']}.",
        f"{b['audience']}: this is for you." if b["audience"] else f"Who {b['name']} is for.",
        f"{feature}. Here's what that means.",
        f"3 things {b['name']} does that surprised me.",
        f"{pain}? Not anymore.",
        "Watch this before you pick your next tool.",
        f"The {b['name']} setup nobody talks about.",
        f"{b['lines'][0]}" if b["lines"] else f"Here's {b['name']} in 30 seconds.",
    ]
    out = list(dict.fromkeys([*written, *(copy_rules.scrub(t) for t in templates if t.strip())]))
    return out[:count]


def script(sections: dict[str, Any], *, seconds: int = 30, llm: Any = None) -> dict[str, Any]:
    seconds = max(10, min(int(seconds or 30), 90))
    reply = _llm_json(llm, f'Write a {seconds}-second UGC ad script. JSON: {{"lines": [..]}}', sections)
    lines = [str(x).strip() for x in reply.get("lines", []) if str(x).strip()] if reply else []
    if not lines:
        b = _brand(sections)
        pain = (b["pains"] or ["Hours lost on setup"])[0]
        lines = [
            hooks(sections, count=1)[0],
            f"{pain}. I know the feeling.",
            f"{b['name']}: {b['one_liner']}" if b["one_liner"] else f"I found {b['name']}.",
            *[f"It gives you {f[:1].lower() + f[1:]}." for f in b["features"][:2]],
            f"{b['pricing']}." if b["pricing"] else "",
            f"Try {b['name']}. Link below.",
        ]
    clean = [copy_rules.scrub(line) for line in lines if line]
    return {"kind": "script", "seconds": seconds, "lines": clean}


def creative_prompt(sections: dict[str, Any], request: str, *, kind: str, variation: int = 0) -> str:
    """The prompt sent to the image / video model, grounded in brand memory."""
    b = _brand(sections)
    parts = [
        request.strip() or f"An ad for {b['name']}",
        f"Brand: {b['name']}" + (f" - {b['one_liner']}" if b["one_liner"] else ""),
        f"Brand colors: {', '.join(b['colors'][:3])}" if b["colors"] else "",
        f"For: {b['audience']}" if b["audience"] else "",
        "Vertical 9:16, UGC style, natural light" if kind == "video" else "Clean ad layout, readable text",
        f"Variation {variation + 1}" if variation else "",
    ]
    return copy_rules.scrub(". ".join(p for p in parts if p))[:3900]


__all__ = ["creative_prompt", "hooks", "script"]
