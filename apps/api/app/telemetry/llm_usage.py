"""Per-stage LLM usage capture for per-job cost actuals.

A pipeline stage opens a capture (:func:`begin`), every LLM call made through
``app.services.llm._generate_response`` inside it is recorded (:func:`record`),
and the stage closes it (:func:`end`) to write one cost row with the model and
token counts. Tokens are estimated from characters (4 chars per token) because
not every provider path returns usage; ``tokens_estimated`` says so in the row.

Uses a ``ContextVar`` so concurrent stages never see each other's calls, and
recording outside a capture is a no-op.
"""

from __future__ import annotations

import math
from contextvars import ContextVar, Token
from typing import Any

CHARS_PER_TOKEN: int = 4

_calls: ContextVar[list[dict[str, Any]] | None] = ContextVar("menivor_llm_calls", default=None)


def begin() -> Token:
    return _calls.set([])


def end(token: Token) -> list[dict[str, Any]]:
    calls = list(_calls.get() or [])
    _calls.reset(token)
    return calls


def record(*, model: str, prompt_chars: int, completion_chars: int, ok: bool = True) -> None:
    calls = _calls.get()
    if calls is None:
        return
    calls.append(
        {
            "model": str(model or "unknown"),
            "prompt_chars": max(0, int(prompt_chars)),
            "completion_chars": max(0, int(completion_chars)),
            "ok": bool(ok),
        }
    )


def tokens(chars: int) -> int:
    return int(math.ceil(max(0, int(chars)) / CHARS_PER_TOKEN))


def summarize(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """``{model, calls, prompt_tokens, completion_tokens, tokens_estimated}``."""
    models = sorted({c["model"] for c in calls})
    return {
        "model": models[0] if len(models) == 1 else ",".join(models),
        "calls": len(calls),
        "failed_calls": sum(1 for c in calls if not c["ok"]),
        "prompt_tokens": sum(tokens(c["prompt_chars"]) for c in calls),
        "completion_tokens": sum(tokens(c["completion_chars"]) for c in calls),
        "tokens_estimated": True,
    }


__all__ = ["begin", "end", "record", "summarize", "tokens"]
