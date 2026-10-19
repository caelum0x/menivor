"""Best hook first (M1.3): write 5 opening lines, let an LLM judge pick one.

The first seconds decide most of a reel's retention, so the script stage does
not settle for the first hook the writer produced:

1. **Candidates.** The script's own opening line plus four alternatives from
   one LLM call (same product, same angle when the job has a hook style).
   When the LLM is down the alternatives come from the deterministic hook
   templates in ``services.loops.hook_suggestions``.
2. **Judge.** A second LLM call scores all five 0-10 for scroll-stopping power
   and clarity. When it fails, a transparent heuristic scores them instead.
3. **Winner.** The top score replaces the script's first paragraph; a tie keeps
   the original, and only an LLM verdict may replace it (heuristic scores are
   recorded, never acted on). Nothing else in the script changes.

Every LLM call goes through ``services.llm._generate_response`` (Relay on
Claude credits in production). ``MENIVOR_HOOK_JUDGE=off`` disables the step.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable

from loguru import logger

HOOK_COUNT = 5
MAX_HOOK_CHARS = 200
_OFF = frozenset({"0", "off", "false", "no"})
_FILLER_OPENERS = ("so ", "hey ", "hi ", "in this video", "today ", "welcome", "let me")

Generate = Callable[[str], str]


@dataclass(frozen=True)
class HookVerdict:
    """The judged candidates (index 0 is the script's own hook)."""

    hooks: tuple[str, ...]
    scores: tuple[float, ...]
    winner: int
    source: str  # "llm" or "heuristic"
    candidates_source: str  # "llm" or "templates"

    @property
    def best(self) -> str:
        return self.hooks[self.winner]

    def as_dict(self) -> dict:
        return {
            "hooks": list(self.hooks),
            "scores": list(self.scores),
            "winner": self.winner,
            "source": self.source,
            "candidates_source": self.candidates_source,
        }


def judge_enabled() -> bool:
    """``MENIVOR_HOOK_JUDGE`` (default on)."""
    return os.environ.get("MENIVOR_HOOK_JUDGE", "on").strip().lower() not in _OFF


def first_paragraph(script: str) -> tuple[str, str]:
    """``(hook, rest)``: the first paragraph and everything after it."""
    parts = re.split(r"(\n\s*\n)", str(script or "").strip(), maxsplit=1)
    hook = parts[0].strip()
    rest = "".join(parts[1:]) if len(parts) > 1 else ""
    return hook, rest


def replace_hook(script: str, hook: str) -> str:
    """``script`` with its first paragraph replaced by ``hook``."""
    _old, rest = first_paragraph(script)
    return f"{hook.strip()}{rest}" if rest else hook.strip()


def _clean(line: object) -> str:
    text = re.sub(r"\s+", " ", str(line or "")).strip().strip('"').strip()
    return text[:MAX_HOOK_CHARS]


def heuristic_score(hook: str) -> float:
    """0-10 from plain signals: short, concrete, speaks to the viewer, no filler."""
    text = _clean(hook)
    if not text:
        return 0.0
    words = text.split()
    score = 5.0
    score += 1.5 if 4 <= len(words) <= 14 else (-1.5 if len(words) > 22 else 0.0)
    score += 1.0 if re.search(r"\byou(r)?\b|\bsen\b|\bsiz\b", text, re.IGNORECASE) else 0.0
    score += 1.0 if re.search(r"\d", text) else 0.0
    score += 0.5 if text.endswith("?") else 0.0
    score -= 2.0 if text.lower().startswith(_FILLER_OPENERS) else 0.0
    return round(max(0.0, min(10.0, score)), 2)


def _json_block(text: str) -> object:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    match = re.search(r"[\[{].*[\]}]", raw, re.DOTALL)
    return json.loads(match.group(0) if match else raw)


def candidates_prompt(hook: str, subject: str, language: str, angle: str, count: int) -> str:
    angle_line = f"Keep this angle: {angle}.\n" if angle else ""
    return (
        "You write the first spoken line of a short vertical video ad.\n"
        f"Product or topic: {subject[:300]}\n"
        f"Current opening line: {hook[:MAX_HOOK_CHARS]}\n"
        f"{angle_line}"
        f"Language: {language or 'same as the current line'}.\n"
        f"Write {count} different opening lines, each under 15 words, each a complete "
        "sentence a person would say out loud. No emoji, no hashtags, no claims the "
        "product cannot back up.\n"
        'Answer with JSON only: {"hooks": ["...", "..."]}'
    )


def judge_prompt(hooks: list[str], subject: str) -> str:
    numbered = "\n".join(f"{i}. {h}" for i, h in enumerate(hooks))
    return (
        "You judge opening lines for short vertical videos. Score each 0-10 for how "
        "likely a viewer keeps watching past the first 3 seconds: clear, specific, "
        "honest, and hard to scroll past. Penalise vague or hype lines.\n"
        f"Topic: {subject[:300]}\n{numbered}\n"
        'Answer with JSON only: {"scores": [n0, n1, ...]} in the same order.'
    )


def _llm(generate: Generate, prompt: str) -> str | None:
    try:
        text = generate(prompt)
    except Exception as exc:  # noqa: BLE001 - the judge is best-effort
        logger.warning(f"hook judge: LLM call failed: {exc}")
        return None
    if not text or str(text).startswith("Error: "):
        return None
    return str(text)


def _alternatives(hook: str, subject: str, language: str, angle: str, generate: Generate) -> tuple[list[str], str]:
    want = HOOK_COUNT - 1
    text = _llm(generate, candidates_prompt(hook, subject, language, angle, want))
    if text:
        try:
            data = _json_block(text)
            raw = data.get("hooks", []) if isinstance(data, dict) else data
            found = [_clean(h) for h in raw if _clean(h)]
            unique = [h for i, h in enumerate(found) if h.lower() not in {x.lower() for x in found[:i]}]
            unique = [h for h in unique if h.lower() != hook.lower()]
            if len(unique) >= want:
                return unique[:want], "llm"
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning(f"hook judge: unreadable candidates: {exc}")
    from app.services.loops.hook_suggestions import suggest_hooks

    templates = [_clean(s.text) for s in suggest_hooks(hook, limit=HOOK_COUNT)]
    return [h for h in templates if h and h.lower() != hook.lower()][:want], "templates"


def _scores(hooks: list[str], subject: str, generate: Generate) -> tuple[list[float], str]:
    text = _llm(generate, judge_prompt(hooks, subject))
    if text:
        try:
            data = _json_block(text)
            raw = data.get("scores", []) if isinstance(data, dict) else data
            scores = [max(0.0, min(10.0, float(value))) for value in raw]
            if len(scores) == len(hooks):
                return scores, "llm"
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning(f"hook judge: unreadable scores: {exc}")
    return [heuristic_score(h) for h in hooks], "heuristic"


def judge_hooks(
    script: str,
    *,
    subject: str,
    language: str = "",
    angle: str = "",
    generate: Generate | None = None,
) -> HookVerdict | None:
    """Judge the script's hook against four alternatives; ``None`` if no hook."""
    hook, _rest = first_paragraph(script)
    hook = _clean(hook)
    if not hook:
        return None
    if generate is None:
        from app.services.llm import _generate_response

        generate = _generate_response
    alternatives, candidates_source = _alternatives(hook, subject, language, angle, generate)
    hooks = [hook, *alternatives]
    scores, source = _scores(hooks, subject, generate)
    best = max(range(len(hooks)), key=lambda i: (scores[i], i == 0))  # ties keep the original
    return HookVerdict(tuple(hooks), tuple(round(s, 2) for s in scores), best, source, candidates_source)


def best_hook_script(
    script: str,
    *,
    subject: str,
    language: str = "",
    angle: str = "",
    generate: Generate | None = None,
) -> tuple[str, HookVerdict | None]:
    """``(script with the winning hook, verdict)``; the script unchanged on any doubt."""
    if not judge_enabled():
        return script, None
    try:
        verdict = judge_hooks(script, subject=subject, language=language, angle=angle, generate=generate)
    except Exception as exc:  # noqa: BLE001 - never fail a paid script over a hook
        logger.warning(f"hook judge failed (script unchanged): {exc}")
        return script, None
    # Only an LLM judge may replace the writer's hook: the heuristic is a
    # tie-breaker for the record, not good enough to overrule a writer.
    if verdict is None or verdict.winner == 0 or verdict.source != "llm":
        return script, verdict
    return replace_hook(script, verdict.best), verdict


__all__ = [
    "HOOK_COUNT",
    "HookVerdict",
    "best_hook_script",
    "first_paragraph",
    "heuristic_score",
    "judge_enabled",
    "judge_hooks",
    "replace_hook",
]
