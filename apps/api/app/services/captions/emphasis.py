"""Keyword emphasis for karaoke caption lines (M2.4).

Each caption line (2-4 words) gets at most one emphasised keyword, drawn in the
style's emphasis colour. The pick runs in this order:

1. Relay, Claude Haiku (one call per reel, all lines numbered in one prompt),
   only when Railyard Relay is configured and ``MENIVOR_CAPTION_EMPHASIS_LLM``
   is not ``0``. The answer is validated word by word against the real line, so
   the model can only choose a word that is actually on screen.
2. The deterministic content-word heuristic from ``hormozi.select_highlight``.

Any Relay failure, timeout, malformed answer or spend-cap stop falls back to the
deterministic pick for the affected lines. Emphasis never fails a render.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional, Sequence

try:  # loguru ships with the API; keep the module import-safe without it.
    from loguru import logger
except Exception:  # pragma: no cover - fallback only when loguru is absent.
    import logging

    logger = logging.getLogger(__name__)

from app.services.captions.hormozi import select_highlight

__all__ = [
    "EMPHASIS_MODEL",
    "EMPHASIS_TIMEOUT_S",
    "build_prompt",
    "deterministic_emphasis",
    "parse_llm_answer",
    "pick_emphasis",
]

#: Relay model for bulk caption work (cheap, fast).
EMPHASIS_MODEL = "claude-haiku-4-5"
#: Hard ceiling on the Relay call; captions must not wait on a slow gateway.
EMPHASIS_TIMEOUT_S = 8.0
#: Longest reel we send in one prompt; longer inputs use the fallback.
_MAX_LINES_FOR_LLM = 400
_ENV_FLAG = "MENIVOR_CAPTION_EMPHASIS_LLM"

# One chat call: ``(prompt) -> text``. Injectable for tests.
ChatFn = Callable[[str], str]


def _word_text(word: Any) -> str:
    if hasattr(word, "text"):
        return str(word.text)
    if isinstance(word, (tuple, list)) and word:
        return str(word[0])
    return str(word)


def _line_texts(lines: Sequence[Sequence[Any]]) -> list[tuple[str, ...]]:
    return [tuple(_word_text(w) for w in line) for line in lines]


def _normalise(token: str) -> str:
    return "".join(ch for ch in token.lower() if ch.isalnum())


def deterministic_emphasis(lines: Sequence[Sequence[Any]]) -> list[Optional[int]]:
    """Per-line index of the key content word, ``None`` for no emphasis.

    Single-word lines are not emphasised (the whole line is already the word).
    """
    picks: list[Optional[int]] = []
    for words in _line_texts(lines):
        if len(words) < 2:
            picks.append(None)
            continue
        idx = select_highlight(words)
        picks.append(idx if idx >= 0 else None)
    return picks


def build_prompt(lines: Sequence[Sequence[Any]]) -> str:
    """The single Relay prompt: numbered caption lines, JSON answer contract."""
    numbered = "\n".join(
        f"{n}: {' '.join(words)}" for n, words in enumerate(_line_texts(lines), start=1)
    )
    return (
        "You pick the one word per caption line that should be highlighted in a "
        "short vertical video. Choose the word that carries the meaning: a "
        "concrete noun, a strong verb, a number or a name. Never pick a filler "
        "word (the, a, and, is, to, of, it). If a line has no meaningful word, "
        "use null.\n"
        "Answer with JSON only, an object mapping each line number to the "
        "chosen word copied exactly from that line, for example "
        '{"1": "money", "2": null}.\n\n'
        f"Lines:\n{numbered}"
    )


def _extract_json_object(text: str) -> Optional[dict]:
    match = re.search(r"\{.*\}", text or "", flags=re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def parse_llm_answer(
    text: str, lines: Sequence[Sequence[Any]]
) -> list[Optional[int]]:
    """Map the model's JSON answer onto word indices, validated per line.

    A line whose answer is missing, not a string, or not one of that line's
    words keeps the deterministic pick. The model can never introduce a word.
    """
    fallback = deterministic_emphasis(lines)
    data = _extract_json_object(text)
    if data is None:
        return fallback
    picks = list(fallback)
    for n, words in enumerate(_line_texts(lines), start=1):
        if len(words) < 2:
            picks[n - 1] = None
            continue
        if str(n) not in data:
            continue
        answer = data[str(n)]
        if answer is None:
            picks[n - 1] = None
            continue
        if not isinstance(answer, str):
            continue
        wanted = _normalise(answer)
        if not wanted:
            continue
        for idx, word in enumerate(words):
            if _normalise(word) == wanted:
                picks[n - 1] = idx
                break
    return picks


def _llm_enabled() -> bool:
    flag = os.environ.get(_ENV_FLAG, "1").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    try:
        from app.domains.railyard import is_relay_enabled
        from app.integrations.railyard import relay_env
    except Exception:  # noqa: BLE001 - Relay package missing: deterministic only
        return False
    return bool(is_relay_enabled(relay_env()))


def _timeout_openai_factory(api_key: str, base_url: Optional[str]) -> Any:
    """OpenAI-SDK client with a short timeout and no SDK-level retries (pointed at Relay)."""
    from app.integrations.railyard.provider_clients import OpenAI

    kwargs: dict[str, Any] = {
        "api_key": api_key or "railyard-relay",
        "timeout": EMPHASIS_TIMEOUT_S,
        "max_retries": 0,
    }
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _relay_haiku_chat(prompt: str) -> str:
    """One Relay chat call on Claude Haiku (Claude credits through Relay)."""
    from app.domains.railyard import run_chat_text
    from app.integrations.railyard import relay_env

    return run_chat_text(
        prompt=prompt,
        model=EMPHASIS_MODEL,
        relay_provider="anthropic",
        temperature=0.0,
        env=relay_env(),
        openai_factory=_timeout_openai_factory,
    )


def pick_emphasis(
    lines: Sequence[Sequence[Any]],
    *,
    chat: Optional[ChatFn] = None,
) -> list[Optional[int]]:
    """Emphasis index per line: Relay Haiku first, deterministic fallback.

    ``chat`` overrides the Relay call (tests). Without it, Relay is used only
    when configured and enabled.
    """
    if not lines:
        return []
    if not any(len(line) >= 2 for line in lines):
        return deterministic_emphasis(lines)
    if len(lines) > _MAX_LINES_FOR_LLM:
        return deterministic_emphasis(lines)
    if chat is None:
        if not _llm_enabled():
            return deterministic_emphasis(lines)
        chat = _relay_haiku_chat
    try:
        answer = chat(build_prompt(lines))
    except Exception as exc:  # noqa: BLE001 - emphasis is best-effort
        logger.info(f"caption emphasis: Relay pick unavailable ({type(exc).__name__}); using fallback")
        return deterministic_emphasis(lines)
    return parse_llm_answer(answer, lines)
