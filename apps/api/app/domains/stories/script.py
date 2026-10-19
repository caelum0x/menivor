"""Pure narration builder: :class:`RedditThread` → one word-capped story script.

Cold-opens the spiciest line (first sentence ending in ``?``/``!``, else the first
sentence), replays the rest of the story in order, and appends a Part-2 CTA — then
caps the whole thing to ``max_words`` so it lands inside the preset's 20-60s bound.
This single string is the fan-out MATRIX BODY; there is deliberately no per-slot
segmentation (the compiler + TTS/caption stages time it downstream).
"""

from __future__ import annotations

import re

DEFAULT_MAX_WORDS = 130
_CTA = "Comment if you want Part 2."
_WS_RE = re.compile(r"\s+")
_SENT_RE = re.compile(r"[^.!?]*[.!?]+|[^.!?]+$")


def _sentences(text: str) -> list[str]:
    collapsed = _WS_RE.sub(" ", text or "").strip()
    if not collapsed:
        return []
    return [m.group(0).strip() for m in _SENT_RE.finditer(collapsed) if m.group(0).strip()]


def _hook_index(sentences: list[str]) -> int:
    """Index of the spiciest opener — first ``?``/``!`` sentence, else the first."""
    for i, sentence in enumerate(sentences):
        if sentence.endswith("?") or sentence.endswith("!"):
            return i
    return 0


def build_story_script(thread, *, max_words: int = DEFAULT_MAX_WORDS) -> str:
    """Build ONE narration string: cold-open → body → CTA, capped to ``max_words``.

    Deterministic and pure. The cold-open sentence is always first; body sentences
    follow in original order; the CTA is always appended. The final word count
    (narration + CTA) never exceeds ``max_words``.
    """
    sentences = _sentences(getattr(thread, "body", "") or "")
    if not sentences:
        title = str(getattr(thread, "title", "") or "").strip()
        sentences = _sentences(title) or ["You won't believe this one."]

    hook_i = _hook_index(sentences)
    ordered = [sentences[hook_i]] + [s for i, s in enumerate(sentences) if i != hook_i]

    cta_words = _CTA.split()
    budget = max(1, int(max_words) - len(cta_words))

    out_words: list[str] = []
    for sentence in ordered:
        words = sentence.split()
        if out_words and len(out_words) + len(words) > budget:
            break
        out_words.extend(words)
        if len(out_words) >= budget:
            out_words = out_words[:budget]
            break

    narration = " ".join(out_words).strip()
    return f"{narration} {_CTA}".strip()
