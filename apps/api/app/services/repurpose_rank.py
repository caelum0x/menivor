"""Virality ranker for the repurpose domain.

Scores raw transcript windows into short-form "viral moment" candidates. Each
segment is rated 0..100 on four axes — hook strength, emotional peak,
standalone clarity and shareability — and annotated with a punchy title, an
opening hook line and a short reason. The heavy lifting is delegated to the
existing LLM dispatch layer (:func:`app.services.llm._generate_response`), so
this module inherits every configured provider (OpenAI, Azure, Gemini, Qwen,
Ollama, the Railyard relay hop, …) without duplicating provider plumbing.

The ranker degrades gracefully: when the LLM is unavailable, returns malformed
output, or errors on a given retry, a deterministic keyword/structure heuristic
fills in the scores so the repurpose flow never hard-fails. The public entry
point is :func:`rank_segments`; its return shape matches what
:func:`app.domains.repurpose.policy.candidate_from_dict` consumes
(``start_s``/``end_s``/``score``/``title``/``hook``/``transcript``/``reason``).
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from app.services.llm import _generate_response, _max_retries, _strip_code_fence

# --------------------------------------------------------------------------- #
# Tuning constants (no magic numbers inline).
# --------------------------------------------------------------------------- #
MIN_SCORE = 0
MAX_SCORE = 100
DEFAULT_LANGUAGE = "auto"
MAX_LANGUAGE_LENGTH = 64
# Guard the prompt size: transcripts can be long, but the ranker only needs a
# representative window of each segment to judge its viral potential.
MAX_SEGMENT_TEXT_LENGTH = 600
MAX_TITLE_LENGTH = 120
MAX_HOOK_LENGTH = 200
MAX_REASON_LENGTH = 240
# Cap how many segments go into a single prompt to keep token cost bounded;
# any overflow is scored by the deterministic heuristic.
MAX_SEGMENTS_PER_REQUEST = 40

# Heuristic vocabulary — deterministic signals used when the LLM is unavailable.
_HOOK_WORDS = frozenset(
    {
        "how", "why", "what", "when", "who", "secret", "secrets", "mistake",
        "mistakes", "never", "always", "stop", "avoid", "warning", "truth",
        "nobody", "everyone", "trick", "hack", "hacks", "proven", "instantly",
        "finally", "reason", "because", "here's", "heres", "listen",
    }
)
_EMOTION_WORDS = frozenset(
    {
        "love", "hate", "amazing", "incredible", "shocking", "shocked", "crazy",
        "insane", "unbelievable", "fear", "afraid", "angry", "excited",
        "heartbreaking", "painful", "wow", "terrible", "horrible", "beautiful",
        "devastating", "surprising", "surprised", "dream", "nightmare", "cried",
    }
)
_SHAREABLE_WORDS = frozenset(
    {
        "you", "your", "everyone", "share", "tips", "tip", "guide", "steps",
        "step", "list", "top", "best", "worst", "free", "now", "today", "money",
        "growth", "viral", "trending", "results", "success", "win", "winning",
    }
)
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_INDEX_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _normalize_language(language: str | None) -> str:
    value = (language or DEFAULT_LANGUAGE).strip()
    if len(value) > MAX_LANGUAGE_LENGTH:
        value = value[:MAX_LANGUAGE_LENGTH]
    return value or DEFAULT_LANGUAGE


def _segment_text(segment: dict) -> str:
    """Return the transcript text of a segment (``text`` or ``transcript``)."""
    return str(segment.get("text", segment.get("transcript", "")) or "").strip()


def _clamp_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(number, maximum))


def _clamp_text(value: Any, max_length: int) -> str:
    text = ("" if value is None else str(value)).strip()
    if max_length and len(text) > max_length:
        return text[:max_length].rstrip()
    return text


def _language_instruction(language: str) -> str:
    if language.lower() == DEFAULT_LANGUAGE:
        return (
            "Write \"title\", \"hook\" and \"reason\" in the same language as the "
            "transcript segment."
        )
    return f'Write "title", "hook" and "reason" in this language: {language}.'


# --------------------------------------------------------------------------- #
# Deterministic heuristic fallback.
# --------------------------------------------------------------------------- #
def _heuristic_signal(words: list[str], vocabulary: frozenset[str]) -> int:
    """Fraction (0..100) of words that hit a signal vocabulary, lightly scaled."""
    if not words:
        return 0
    hits = sum(1 for w in words if w in vocabulary)
    # A couple of strong signal words already indicate a viable moment, so scale
    # so that ~3 hits saturates rather than requiring the whole window to match.
    return _clamp_int((hits / 3.0) * MAX_SCORE, MIN_SCORE, MAX_SCORE)


def _clarity_signal(text: str, start_s: Any, end_s: Any) -> int:
    """Reward self-contained windows: complete sentences of a shareable length."""
    if not text:
        return MIN_SCORE
    length = len(text)
    # Very short or very long windows are worse standalone clips.
    if length < 40:
        length_score = 40
    elif length > 400:
        length_score = 55
    else:
        length_score = 85
    ends_clean = 20 if text[-1:] in ".!?。！？" else 0
    try:
        duration = int(end_s) - int(start_s)
    except (TypeError, ValueError):
        duration = 0
    duration_score = 15 if 12 <= duration <= 70 else 0
    return _clamp_int(length_score + ends_clean + duration_score, MIN_SCORE, MAX_SCORE)


def _heuristic_score(segment: dict) -> tuple[int, str]:
    """Deterministic 0..100 virality score + reason for one segment."""
    text = _segment_text(segment)
    words = [w.lower() for w in _WORD_RE.findall(text)]

    hook = _heuristic_signal(words, _HOOK_WORDS)
    emotion = _heuristic_signal(words, _EMOTION_WORDS)
    clarity = _clarity_signal(text, segment.get("start_s"), segment.get("end_s"))
    shareability = _heuristic_signal(words, _SHAREABLE_WORDS)
    if "?" in text:
        hook = _clamp_int(hook + 25, MIN_SCORE, MAX_SCORE)
    if any(ch.isdigit() for ch in text):
        shareability = _clamp_int(shareability + 15, MIN_SCORE, MAX_SCORE)

    # Weighted blend across the four viral axes.
    score = _clamp_int(
        0.30 * hook + 0.25 * emotion + 0.25 * clarity + 0.20 * shareability,
        MIN_SCORE,
        MAX_SCORE,
    )
    reason = (
        f"Heuristic score (LLM unavailable): hook {hook}, emotion {emotion}, "
        f"clarity {clarity}, shareability {shareability}."
    )
    return score, reason


def _heuristic_title(text: str) -> str:
    first = re.split(r"(?<=[.!?。！？])\s+", text.strip(), maxsplit=1)[0]
    return _clamp_text(first, MAX_TITLE_LENGTH)


def _fallback_segment(segment: dict) -> dict:
    """Annotate a single segment using only the deterministic heuristic."""
    text = _segment_text(segment)
    score, reason = _heuristic_score(segment)
    annotated = dict(segment)
    annotated["score"] = score
    annotated["reason"] = _clamp_text(segment.get("reason") or reason, MAX_REASON_LENGTH)
    annotated["title"] = _clamp_text(segment.get("title") or _heuristic_title(text), MAX_TITLE_LENGTH)
    annotated["hook"] = _clamp_text(segment.get("hook") or text, MAX_HOOK_LENGTH)
    annotated.setdefault("text", text)
    return annotated


def _fallback_rank(segments: list[dict]) -> list[dict]:
    return [_fallback_segment(segment) for segment in segments]


# --------------------------------------------------------------------------- #
# LLM prompt + response handling.
# --------------------------------------------------------------------------- #
def build_rank_prompt(segments: list[dict], language: str) -> str:
    """Build the ranking prompt for a batch of indexed transcript segments."""
    language = _normalize_language(language)
    lines = []
    for index, segment in enumerate(segments):
        text = _clamp_text(_segment_text(segment), MAX_SEGMENT_TEXT_LENGTH)
        lines.append(f"[{index}] {text}")
    segments_block = "\n".join(lines)

    return f"""
# Role: Short-Video Virality Analyst

## Goal
Rate each transcript segment for its potential as a standalone viral short-form
clip (TikTok / Reels / Shorts).

## Scoring axes (each 0-100, then combine into one overall score)
1. hook strength - does the opening grab attention in the first seconds?
2. emotional peak - does it trigger a strong emotion (surprise, awe, anger, joy)?
3. standalone clarity - does it make sense on its own, without surrounding context?
4. shareability - would a viewer send it to a friend or repost it?

## Constraints
1. Respond ONLY with a single valid minified JSON array. No markdown, no code fences, no commentary.
2. Each array element is an object with exactly these keys: "index", "score", "title", "hook", "reason".
3. "index": the integer segment index exactly as given below.
4. "score": one integer 0-100 for the overall viral potential (blend the four axes).
5. "title": a punchy clip title, at most {MAX_TITLE_LENGTH} characters.
6. "hook": the single strongest opening line to lead the clip, at most {MAX_HOOK_LENGTH} characters.
7. "reason": one short sentence justifying the score, at most {MAX_REASON_LENGTH} characters.
8. Include exactly one object per segment; do not add, drop, merge or reorder segments.
9. {_language_instruction(language)}

## Output Example
[{{"index":0,"score":82,"title":"...","hook":"...","reason":"..."}}]

## Transcript Segments
{segments_block}
""".strip()


def _parse_rank_response(response: str, segments: list[dict]) -> list[dict]:
    """Merge LLM scores/annotations onto ``segments`` by index.

    Raises ``ValueError`` when the payload is not a usable JSON array so the
    caller can retry or fall back to the heuristic.
    """
    data = None
    try:
        data = json.loads(_strip_code_fence(response))
    except Exception:
        match = re.search(r"\[.*\]", response or "", re.DOTALL)
        if match:
            data = json.loads(match.group())

    if not isinstance(data, list):
        raise ValueError("rank response is not a JSON array")

    by_index: dict[int, dict] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            idx = int(entry.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(segments):
            by_index[idx] = entry

    if not by_index:
        raise ValueError("rank response contained no usable segment scores")

    ranked: list[dict] = []
    for index, segment in enumerate(segments):
        entry = by_index.get(index)
        if entry is None:
            # The LLM omitted this segment — keep it via the heuristic so the
            # selection policy still sees every window.
            ranked.append(_fallback_segment(segment))
            continue
        text = _segment_text(segment)
        annotated = dict(segment)
        annotated["score"] = _clamp_int(entry.get("score", 0), MIN_SCORE, MAX_SCORE)
        annotated["title"] = _clamp_text(
            entry.get("title") or segment.get("title") or _heuristic_title(text),
            MAX_TITLE_LENGTH,
        )
        annotated["hook"] = _clamp_text(
            entry.get("hook") or segment.get("hook") or text, MAX_HOOK_LENGTH
        )
        annotated["reason"] = _clamp_text(
            entry.get("reason") or segment.get("reason") or "", MAX_REASON_LENGTH
        )
        annotated.setdefault("text", text)
        ranked.append(annotated)
    return ranked


def rank_segments(segments: list[dict], language: str = DEFAULT_LANGUAGE) -> list[dict]:
    """Score transcript ``segments`` into ranked viral-moment candidates.

    Returns a new list of segment dicts, each carrying an integer ``score``
    (0-100) plus ``title``/``hook``/``reason``, ready for
    :func:`app.domains.repurpose.policy.candidate_from_dict`. Input dicts are not
    mutated. Degrades to a deterministic heuristic when the LLM layer is
    unavailable or returns unusable output.
    """
    if not segments:
        return []

    language = _normalize_language(language)

    # Bound prompt size: rank the head via the LLM, tail via the heuristic.
    head = segments[:MAX_SEGMENTS_PER_REQUEST]
    tail = segments[MAX_SEGMENTS_PER_REQUEST:]

    prompt = build_rank_prompt(head, language)
    logger.info(
        f"ranking {len(head)} transcript segment(s) for virality, language={language}"
        + (f" (+{len(tail)} via heuristic)" if tail else "")
    )

    ranked_head: list[dict] | None = None
    for attempt in range(_max_retries):
        try:
            response = _generate_response(prompt)
            if isinstance(response, str) and response.startswith("Error: "):
                logger.error(f"failed to rank segments: {response}")
                break
            ranked_head = _parse_rank_response(response, head)
            logger.success(f"ranked {len(ranked_head)} segment(s) via LLM")
            break
        except Exception as exc:  # noqa: BLE001 - retry, then fall back
            logger.warning(f"failed to parse rank response: {exc}")
        if attempt < _max_retries - 1:
            logger.warning(f"failed to rank segments, trying again... {attempt + 1}")

    if ranked_head is None:
        logger.warning("falling back to heuristic virality ranking")
        ranked_head = _fallback_rank(head)

    ranked = ranked_head + _fallback_rank(tail)
    ranked.sort(key=lambda s: int(s.get("score", 0) or 0), reverse=True)
    return ranked
