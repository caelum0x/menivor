"""Cold-open rewrite suggestions — turn a weak hook into pattern-interrupt options.

When :func:`app.services.loops.hook_predictor.predict_hook` scores a cold-open
below the 70% gate, a creator needs concrete alternatives, not just a score. This
module rewrites the opening line into the highest-retention cold-open *shapes*
(shock-first, curiosity gap, question, negation, number/stakes) — the patterns the
research shows clear the first-3s gate — and biases the ordering by which weak
signals the predictor flagged.

The static f-string templates are always generated first (deterministic fallback).
When ``topic`` + ``language`` + an optional ``app_config`` are provided, the
top-ranked template is polished via a single LLM call
(:func:`app.services.llm._generate_response`).  If the LLM call fails for any
reason the static template is returned unchanged, so the function is always safe
to call without a configured LLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.loops import policy

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HookSuggestion:
    """One rewritten cold-open + why it works."""

    shape: str
    text: str
    rationale: str


def _first_clause(line: str) -> str:
    """The core payload of the opening line (drop leading filler)."""
    s = str(line or "").strip().rstrip(".!?").strip()
    for filler in ("so ", "basically ", "okay so ", "um ", "well ", "hey guys "):
        if s.lower().startswith(filler):
            s = s[len(filler):]
    return s.strip() or "this"


def suggest_hooks(
    opening_line: str,
    *,
    passes_gate: bool = False,
    reasons: tuple[str, ...] = (),
    limit: int = 5,
    topic: str = "",
    language: str = "",
    app_config: object = None,
) -> list[HookSuggestion]:
    """Return concrete cold-open rewrites, strongest shape first.

    When the hook already ``passes_gate`` an empty list is returned (no change
    needed). Otherwise the templates are ordered so the shape that addresses the
    predictor's flagged weakness leads.

    When both ``topic`` and ``language`` are non-empty, the top-ranked suggestion
    is polished by a single LLM rewrite via
    :func:`app.services.llm._generate_response` (the static template acts as the
    deterministic fallback on any failure).
    """
    if passes_gate:
        return []

    core = _first_clause(opening_line)
    suggestions = [
        HookSuggestion(
            "shock_first",
            f"{core[:1].upper()}{core[1:]}.",
            "State the most shocking line FIRST — no setup.",
        ),
        HookSuggestion(
            "curiosity_gap",
            f"Nobody tells you this about {core}…",
            "Open a curiosity gap the viewer must close.",
        ),
        HookSuggestion(
            "question",
            f"Ever wonder why {core}?",
            "A question hook makes the viewer stay for the answer.",
        ),
        HookSuggestion(
            "negation",
            f"Stop doing {core} — here’s why.",
            "A negation/pattern-interrupt breaks the scroll.",
        ),
        HookSuggestion(
            "stakes",
            f"This {core} cost me everything.",
            "Raise the stakes in the first sentence.",
        ),
    ]

    # Bias ordering by the predictor's flagged weaknesses.
    reason_text = " ".join(reasons).lower()

    def _rank(s: HookSuggestion) -> int:
        if "spiciest" in reason_text and s.shape == "shock_first":
            return -3
        if "text" in reason_text and s.shape in ("shock_first", "negation"):
            return -2
        if "tighten" in reason_text and s.shape == "shock_first":
            return -1
        return 0

    suggestions.sort(key=_rank)
    result = suggestions[: max(1, limit)]

    # LLM polish: rewrite the top suggestion when topic + language are available.
    if topic and language and result:
        result = _llm_polish_top(result, topic=topic, language=language, app_config=app_config)

    return result


def _llm_polish_top(
    suggestions: list[HookSuggestion],
    *,
    topic: str,
    language: str,
    app_config: object,
) -> list[HookSuggestion]:
    """Replace the top suggestion's text with an LLM-polished rewrite.

    Returns the original list unchanged on any failure so the caller always
    gets at least the deterministic fallback.
    """
    try:
        from app.services.llm import _generate_response  # noqa: PLC0415

        top = suggestions[0]
        prompt = (
            f"Rewrite this cold-open for {topic} in {language}, keep it punchy.\n"
            f"Shape: {top.shape}\n"
            f"Draft: {top.text}\n"
            f"Return only the rewritten single line, no explanation, no quotes."
        )
        polished_text = _generate_response(prompt, app_config).strip()
        if polished_text:
            polished = HookSuggestion(
                shape=top.shape,
                text=polished_text,
                rationale=top.rationale,
            )
            return [polished, *suggestions[1:]]
    except Exception as exc:
        _log.debug("LLM hook polish failed (%s) — using static template", exc)
    return suggestions


def needs_suggestions(score: float) -> bool:
    """True when a hook score is below the viral-reach gate (suggest rewrites)."""
    return float(score) < policy.HOOK_MIN_CLEARANCE
