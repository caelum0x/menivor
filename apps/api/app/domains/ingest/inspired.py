"""Pure "a reel inspired by this" draft from a social post's inspiration.

Keeps the post's ANGLE (hook style, topic, format) and retells it for the
user's own product. It never copies the caption into the script, never names
the original author, and never implies the original video is the user's.
"""

from __future__ import annotations

import re

from app.domains.ingest.classify import PLATFORM_NAMES

_LIST = re.compile(r"^\s*(\d+|three|five|seven|ten)\b", re.IGNORECASE)
_HOWTO = re.compile(r"^\s*(how to|how i|here'?s how|the (easiest|fastest|best) way)", re.IGNORECASE)
_POV = re.compile(r"^\s*pov\b", re.IGNORECASE)
_STOP = re.compile(r"^\s*(stop|don'?t|never|quit)\b", re.IGNORECASE)

_HOOKS = {
    "pov": "POV: you finally found a better way to handle {topic}.",
    "question": "What if {topic} took half the effort?",
    "list": "3 things nobody tells you about {topic}.",
    "howto": "How to get better results with {topic}, fast.",
    "warning": "Stop doing {topic} the hard way.",
    "statement": "This changed how I think about {topic}.",
}
_BEATS = {
    "short video": "Most people overcomplicate {topic}. Here is the simple version.",
    "video": "Here is the problem with {topic}, and the fix in under a minute.",
    "live video": "Here is the one moment that matters for {topic}.",
    "image pin": "One picture explains the whole idea behind {topic}.",
    "image post": "One picture explains the whole idea behind {topic}.",
    "photo carousel": "Swipe through the steps for {topic}, one at a time.",
}
_DEFAULT_BEAT = "Here is the idea behind {topic}, in plain words."


def hook_style(hook: str) -> str:
    """Classify a hook's structure: pov / question / list / howto / warning / statement."""
    text = (hook or "").strip()
    if _POV.match(text):
        return "pov"
    if text.endswith("?"):
        return "question"
    if _LIST.match(text):
        return "list"
    if _HOWTO.match(text):
        return "howto"
    if _STOP.match(text):
        return "warning"
    return "statement"


def build_inspired_draft(inspiration: dict, platform: str | None) -> dict:
    """Assemble ``{video_subject, hook, video_script, broll_prompts, angle, inspired_by}``."""
    topic = (inspiration.get("topic") or "").strip() or "this"
    fmt = inspiration.get("format") or "post"
    style = hook_style(inspiration.get("hook") or "")
    hook = _HOOKS[style].format(topic=topic)
    beats = [
        _BEATS.get(fmt, _DEFAULT_BEAT).format(topic=topic),
        f"That is exactly what our product is built for when it comes to {topic}.",
        "Show it working in one quick, real example.",
    ]
    script = " ".join([hook, *beats, "Check the link to try it."])
    source_name = PLATFORM_NAMES.get(platform or "", "social")
    return {
        "video_subject": f"Your product, told through {topic}",
        "hook": hook,
        "video_script": script,
        "broll_prompts": [
            f"dynamic b-roll that visualizes {topic}",
            f"close-up of hands using the product for {topic}",
            "clean product hero shot, soft studio light",
        ],
        "angle": f"Same {style} hook and {fmt} format as the {source_name} post, retold for your product",
        "inspired_by": {"platform": platform, "format": fmt, "hook_style": style},
    }


__all__ = ["build_inspired_draft", "hook_style"]
