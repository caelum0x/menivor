"""TypeSafe *System One* (Jev) async HTTP client.

A thin, dependency-light wrapper over the shared ``httpx`` client that speaks the
TypeSafe ``/systemone`` contract directly from Python — no vendor SDK:

    POST {base_url}/systemone
    Authorization: Bearer $TYPESAFE_API_KEY
    { "state": <str|obj>, "model": "jev-latest", "questions": { "<id>": {...} } }

All questions in one ``system_one`` call run in parallel on the server and cannot
see one another's answers, so callers batch every question a variant needs into a
single request (see :mod:`app.domains.growth.hook_ranker`).

The API key is read from the environment (``TYPESAFE_API_KEY``, falling back to the
lowercase ``typesafe_api_key`` used in the shared ``products/.env``). It is NEVER
hardcoded and NEVER logged. When the key is absent, :func:`typesafe_from_env`
returns ``None`` so callers can degrade gracefully instead of failing hard.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Mapping

import httpx
from loguru import logger

DEFAULT_BASE_URL = "https://api.typesafe.ai/v1"
DEFAULT_MODEL = "jev-latest"
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})

QuestionType = Literal["choice", "score", "noul"]


class TypeSafeError(RuntimeError):
    """A TypeSafe request failed (network, non-2xx, or malformed response)."""

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def choice(instructions: str, options: Mapping[str, str]) -> dict[str, Any]:
    """A choice question: the model PICKS one of ``options`` (built in code)."""
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


def score(instructions: str, levels: list[str]) -> dict[str, Any]:
    """A score question: ordered level descriptions, low → high."""
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


def noul(instructions: str, criteria: Mapping[str, str] | None = None) -> dict[str, Any]:
    """A noul (yes/no probability) question; answer is ``noul`` in ``[0, 1]``."""
    q: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if criteria is not None:
        q["criteria"] = dict(criteria)
    return q


@dataclass(frozen=True)
class TypeSafeClient:
    """Async client for the TypeSafe ``/systemone`` endpoint (Jev by default).

    Immutable config; one instance is safe to share across requests. Uses the
    repo's ``httpx`` async transport and retries retryable statuses with a bounded
    exponential backoff.
    """

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_s: float = 20.0
    max_retries: int = 3
    backoff_s: float = 0.4

    async def system_one(
        self,
        state: Any,
        questions: Mapping[str, dict[str, Any]],
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Ask one batch of typed questions over one piece of ``state``.

        Returns the parsed response ``{ "answers": {...}, "usage": {...} }``.
        Raises :class:`TypeSafeError` on exhausted retries or a non-2xx status.
        """
        payload = {
            "state": state,
            "model": model or self.model,
            "questions": dict(questions),
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        url = f"{self.base_url.rstrip('/')}/systemone"

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.post(url, json=payload, headers=headers)
                except httpx.RequestError as exc:  # network/timeout — retryable
                    last_error = exc
                    if attempt < self.max_retries:
                        await self._sleep(attempt, None)
                        continue
                    raise TypeSafeError(
                        f"TypeSafe request failed after {self.max_retries + 1} attempts: {exc}"
                    ) from exc

                if resp.is_success:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise TypeSafeError("TypeSafe returned a non-JSON body") from exc

                body = _safe_text(resp)
                if resp.status_code in _RETRYABLE_STATUS and attempt < self.max_retries:
                    last_error = TypeSafeError(
                        f"Retryable HTTP {resp.status_code}", status=resp.status_code, body=body
                    )
                    await self._sleep(attempt, resp.headers.get("retry-after"))
                    continue
                raise TypeSafeError(
                    f"TypeSafe request failed: HTTP {resp.status_code}",
                    status=resp.status_code,
                    body=body,
                )

        # Unreachable: the loop always returns or raises.
        raise TypeSafeError(f"TypeSafe request failed: {last_error}")

    async def _sleep(self, attempt: int, retry_after: str | None) -> None:
        import asyncio

        delay = _backoff_delay(attempt, retry_after, self.backoff_s)
        await asyncio.sleep(delay)


def _backoff_delay(attempt: int, retry_after: str | None, base_s: float) -> float:
    if retry_after:
        try:
            secs = float(retry_after)
            if secs >= 0:
                return secs
        except ValueError:
            pass
    return base_s * (2 ** attempt)


def _safe_text(resp: httpx.Response) -> str:
    try:
        return resp.text
    except Exception:  # pragma: no cover - defensive
        return ""


def _env_api_key() -> str:
    """Read the TypeSafe key from env. Canonical name first, then the shared lower one."""
    return (os.getenv("TYPESAFE_API_KEY") or os.getenv("typesafe_api_key") or "").strip()


def typesafe_from_env() -> TypeSafeClient | None:
    """Build a client from the environment, or ``None`` when no key is configured.

    A ``None`` return is the graceful-degradation signal: callers keep working with
    a documented, non-fabricated fallback rather than inventing a key or results.
    """
    api_key = _env_api_key()
    if not api_key:
        logger.warning(
            "TYPESAFE_API_KEY unset — Jev-powered features degrade to pass-through "
            "(no AI scoring). Set TYPESAFE_API_KEY to enable."
        )
        return None
    base_url = (os.getenv("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL).strip()
    model = (os.getenv("TYPESAFE_MODEL") or DEFAULT_MODEL).strip()
    return TypeSafeClient(api_key=api_key, base_url=base_url, model=model)
