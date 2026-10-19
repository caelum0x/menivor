"""Prompt moderation gate for every generation request (provider-pluggable).

This module is wired as an app-level FastAPI dependency (see ``app.asgi``). It
runs AFTER request-body validation and BEFORE the route handler, so a blocked
prompt never reaches credit debit, job creation or Celery enqueue: blocked
requests are never charged.

Providers (``MENIVOR_MODERATION_PROVIDER``):

* ``safeguard`` (default) - ``openai/gpt-oss-safeguard-20b`` classifying the
  text against Menivor's Acceptable Use Policy through a fallthrough chain:
  Railyard Relay -> Groq direct -> OpenRouter -> Claude Haiku (last resort). A
  hop that answers 429 is skipped for ~60s (``app.core.moderation_safeguard``).
* ``creem`` - the Creem Moderation API (``app.core.moderation_creem``). Kept
  available but not used: Menivor does not depend on Creem.

Decisions:

* ``allow`` -> continue.
* ``flag``  -> continue; logged at WARNING.
* ``deny``  -> HTTP 400 with a clear, human message; nothing is charged.

Outages (network error, timeout, 5xx, malformed or invalid answer) FAIL CLOSED
by default: the user gets a 503 asking them to retry.
``MENIVOR_MODERATION_FAIL_OPEN=1`` is an explicit, logged operator escape hatch
for an extended provider incident.

Configuration (env):

* ``MENIVOR_MODERATION_PROVIDER``   - ``safeguard`` (default) or ``creem``.
* ``MENIVOR_MODERATION``            - ``auto`` (default: on iff the provider is
  configured), ``on`` (required: fail closed when unconfigured), ``off``.
* ``MENIVOR_MODERATION_TIMEOUT_S``  - per-hop request timeout, default 8 seconds.
* ``MENIVOR_MODERATION_FAIL_OPEN``  - ``1`` to let generation continue on outage.
* ``MENIVOR_MODERATION_CACHE``      - ``off`` disables the 24h Redis decision cache.
* ``MENIVOR_MODERATION_DAILY_BUDGET`` - provider checks per user per day
  (default 300); cache hits are free. Over budget answers 429.

Cost-DoS rules: moderation only runs for a VERIFIED principal (a bearer or API
key that resolves to a user), so a made-up ``Authorization`` header plus a large
prompt gets a 401 with zero provider calls. Each user then has a daily budget of
provider checks, enforced by the fail-closed limiter in ``app.services.ratelimit``.

Prompt text is user content: it is never logged; only lengths, decisions,
categories and ids are.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Iterable

from fastapi import Request
from loguru import logger

from app.core import moderation_cache, moderation_creem, moderation_safeguard
from app.core.moderation_policy import POLICY_VERSION
from app.core.moderation_types import ModerationResult, ModerationUnavailable
from app.core.observability import request_correlation_id
from app.models.exception import HttpException

__all__ = [
    "ModerationResult",
    "ModerationUnavailable",
    "check_prompt",
    "enforce_moderation",
    "extract_prompt_text",
    "moderate_generation_request",
    "moderation_enabled",
]

PROVIDERS = {
    moderation_safeguard.NAME: moderation_safeguard,
    moderation_creem.NAME: moderation_creem,
}
DEFAULT_PROVIDER = moderation_safeguard.NAME
DEFAULT_TIMEOUT_S = 8.0
DEFAULT_DAILY_BUDGET = 300
_DAY_S = 86_400
MAX_PROMPT_CHARS = 12_000
MAX_DEPTH = 8

BLOCKED_MESSAGE = (
    "This request can't be generated because it goes against our Acceptable Use "
    "Policy. Please change the text and try again. You were not charged."
)
BUDGET_MESSAGE = (
    "You have reached today's limit for new prompts. It resets within 24 hours."
)
AUTH_UNAVAILABLE_MESSAGE = "We could not verify your sign-in right now. Please try again."
OUTAGE_MESSAGE = (
    "We couldn't run our content safety check right now. Please try again in a "
    "minute. You were not charged."
)

# Routes (method, path template) whose request text drives image, video, audio
# or script generation. Anything not listed here is untouched.
MODERATED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/jobs"),
        ("POST", "/api/v1/jobs/{job_id}/rerun"),
        ("POST", "/api/v1/jobs/{job_id}/cover"),
        ("POST", "/api/v1/jobs/{job_id}/timeline-exports"),
        ("POST", "/api/v1/videos"),
        ("POST", "/api/v1/scripts"),
        ("POST", "/api/v1/subtitle"),
        ("POST", "/api/v1/audio"),
        ("POST", "/api/v1/generation/broll/generate"),
        ("POST", "/api/v1/broll/generate"),
        ("POST", "/api/v1/stories/reddit"),
        ("POST", "/api/v1/characters"),
        ("POST", "/api/v1/characters/{character_id}/shot-prompt"),
        ("POST", "/api/v1/canon"),
        ("POST", "/api/v1/canon/{canon_id}/lock"),
        ("POST", "/api/v1/media/images"),
        ("POST", "/api/v1/media/videos"),
        ("POST", "/api/v1/media/audio"),
        ("POST", "/api/v1/series/channels"),
        ("PATCH", "/api/v1/series/channels/{channel_id}"),
        ("POST", "/api/v1/series/channels/{channel_id}/run"),
        ("POST", "/api/v1/capture/{capture_id}/ads"),
        ("POST", "/api/v1/design/generate"),
        ("POST", "/api/v1/design/docs"),
        ("POST", "/api/v1/design/docs/{doc_id}/ai-image"),
        ("POST", "/api/v1/ad-studio/analyze"),
        ("POST", "/api/v1/ad-studio/projects"),
        ("PATCH", "/api/v1/ad-studio/projects/{project_id}"),
        ("POST", "/api/v1/templates/{slug}/compile"),
        ("POST", "/api/v1/templates/{slug}/instantiate"),
        ("POST", "/api/v1/film/plan"),
        ("POST", "/api/v1/film/projects"),
        ("POST", "/api/v1/render/jobs"),
        ("POST", "/api/v1/audiobook/chapter"),
    }
)

# Keys whose string value is generation text wherever they appear in the body.
TEXT_KEYS: frozenset[str] = frozenset(
    {
        "prompt",
        "negative",
        "negative_prompt",
        "video_subject",
        "video_script",
        "translate_source_script",
        "music_prompt",
        "video_music_prompt",
        "sonilo_bgm_prompt",
        "video_script_prompt",
        "custom_system_prompt",
        "script",
        "subject",
        "text",
        "title",
        "headline",
        "caption",
        "action",
        "scene",
        "style",
        "product",
        "product_name",
        "brand_tone",
        "voice_tone",
        "description",
        "hook",
        "cta",
        "name",
    }
)

# Keys whose whole subtree (every nested string) is generation text.
SUBTREE_KEYS: frozenset[str] = frozenset(
    {
        "descriptors",
        "product_descriptors",
        "product_claims",
        "hooks",
        "beats",
        "angles",
        "inputs",
        "overlays",
        "character",
    }
)

_AUTH_HEADERS = ("authorization", "x-api-key")
_AUTH_COOKIES = ("__session",)
_URLISH = re.compile(r"^(https?://|r2://|s3://)\S*$", re.IGNORECASE)


def provider_name() -> str:
    name = (os.getenv("MENIVOR_MODERATION_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    return name if name in PROVIDERS else DEFAULT_PROVIDER


def _provider():
    return PROVIDERS[provider_name()]


def _mode() -> str:
    return (os.getenv("MENIVOR_MODERATION") or "auto").strip().lower()


def moderation_enabled() -> bool:
    mode = _mode()
    if mode in {"off", "0", "false", "no", "disabled"}:
        return False
    if mode in {"on", "1", "true", "yes", "required"}:
        return True
    return _provider().configured()


def _timeout_s() -> float:
    raw = (os.getenv("MENIVOR_MODERATION_TIMEOUT_S") or "").strip()
    try:
        return max(1.0, float(raw)) if raw else DEFAULT_TIMEOUT_S
    except ValueError:
        return DEFAULT_TIMEOUT_S


def _fail_open() -> bool:
    return (os.getenv("MENIVOR_MODERATION_FAIL_OPEN") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _add_text(out: list[str], value: str) -> None:
    text = value.strip()
    if len(text) < 2 or _URLISH.match(text):
        return
    out.append(text)


def _collect_all(node: Any, out: list[str], depth: int) -> None:
    if depth > MAX_DEPTH:
        return
    if isinstance(node, str):
        _add_text(out, node)
    elif isinstance(node, dict):
        for value in node.values():
            _collect_all(value, out, depth + 1)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _collect_all(value, out, depth + 1)


def _collect(node: Any, out: list[str], depth: int) -> None:
    if depth > MAX_DEPTH:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            k = str(key).lower()
            if k in SUBTREE_KEYS:
                _collect_all(value, out, depth + 1)
            elif k in TEXT_KEYS and isinstance(value, str):
                _add_text(out, value)
            elif k in TEXT_KEYS and isinstance(value, (list, tuple)):
                _collect_all(value, out, depth + 1)
            else:
                _collect(value, out, depth + 1)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _collect(value, out, depth + 1)


def extract_prompt_text(body: Any) -> str:
    """Join every generation-driving string in a JSON body (deduped, capped)."""
    found: list[str] = []
    _collect(body, found, 0)
    seen: set[str] = set()
    unique = [t for t in found if not (t in seen or seen.add(t))]
    return "\n".join(unique)[:MAX_PROMPT_CHARS]


def daily_budget() -> int:
    raw = (os.getenv("MENIVOR_MODERATION_DAILY_BUDGET") or "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_DAILY_BUDGET
    except ValueError:
        return DEFAULT_DAILY_BUDGET


def check_prompt(
    prompt: str,
    external_id: str = "",
    before_provider_call: Callable[[], None] | None = None,
) -> ModerationResult:
    """Moderate ``prompt`` with the configured provider, via the 24h cache.

    Raises ``ModerationUnavailable``. Only successful decisions are cached.
    ``before_provider_call`` runs on a cache miss, just before the paid call
    (the per-user budget hook); it may raise to stop the call.
    """
    name = provider_name()
    key = moderation_cache.cache_key(name, POLICY_VERSION, prompt)
    cached = moderation_cache.get(key)
    if cached is not None:
        return cached
    if before_provider_call is not None:
        before_provider_call()
    result = PROVIDERS[name].check(prompt, external_id=external_id, timeout_s=_timeout_s())
    moderation_cache.put(key, result)
    return result


def _budget_hook(user_id: str, request_id: str) -> Callable[[], None]:
    """Consume one unit of ``user_id``'s daily moderation budget or raise 429."""

    def consume() -> None:
        from app.services.ratelimit import rate_limit

        result = rate_limit(f"moderation:daily:{user_id}", daily_budget(), _DAY_S)
        if not result.allowed:
            logger.warning(f"moderation budget exhausted user={user_id} request_id={request_id}")
            raise HttpException(
                task_id=request_id,
                status_code=429,
                message=BUDGET_MESSAGE,
                data={"reset_s": result.reset_s},
            )

    return consume


def enforce_moderation(
    texts: Iterable[str] | str, *, request_id: str, surface: str = "", user_id: str = ""
) -> ModerationResult | None:
    """Moderate ``texts``; raise ``HttpException`` on deny/outage/over budget.

    Returns ``None`` when moderation is disabled or there is no text to check.
    With ``user_id`` every provider call (cache misses only) spends one unit of
    that user's daily moderation budget.
    """
    if not moderation_enabled():
        return None
    prompt = texts if isinstance(texts, str) else "\n".join(t for t in texts if t)
    prompt = prompt.strip()[:MAX_PROMPT_CHARS]
    if not prompt:
        return None
    try:
        hook = _budget_hook(user_id, request_id) if user_id else None
        result = check_prompt(prompt, external_id=request_id, before_provider_call=hook)
    except ModerationUnavailable as exc:
        if _fail_open():
            logger.error(
                f"moderation unavailable, FAIL-OPEN override active, surface={surface} "
                f"request_id={request_id}: {exc}"
            )
            return None
        logger.error(
            f"moderation unavailable, failing closed, surface={surface} "
            f"request_id={request_id}: {exc}"
        )
        raise HttpException(task_id=request_id, status_code=503, message=OUTAGE_MESSAGE)

    log_line = (
        f"moderation decision={result.decision} provider={result.provider} "
        f"cached={result.cached} categories={','.join(result.categories) or '-'} "
        f"surface={surface} request_id={request_id} "
        f"moderation_id={result.moderation_id} chars={len(prompt)}"
    )
    if result.decision == "deny":
        logger.warning(log_line)
        raise HttpException(task_id=request_id, status_code=400, message=BLOCKED_MESSAGE)
    if result.decision == "flag":
        logger.warning(log_line)
    else:
        logger.info(log_line)
    return result


def _has_credentials(request: Request) -> bool:
    if any(request.headers.get(h) for h in _AUTH_HEADERS):
        return True
    return any(request.cookies.get(c) for c in _AUTH_COOKIES)


def _verified_user_id(request: Request, request_id: str) -> str:
    """The id of the principal the request authenticates as, or raise.

    Uses the same resolver as every moderated handler, so a bad token is a 401
    here too; anything unexpected fails closed with a 503.
    """
    try:
        from app.core.auth.principal import resolve_principal
        from app.models.db.base import get_session

        with get_session() as session:
            return str(resolve_principal(request, session, request_id).id)
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - identity unknown: never spend on it
        logger.error(f"moderation: principal check failed request_id={request_id}: {type(exc).__name__}")
        raise HttpException(task_id=request_id, status_code=503, message=AUTH_UNAVAILABLE_MESSAGE)


async def moderate_generation_request(request: Request) -> None:
    """App-level dependency: moderate generation routes before the handler runs.

    Requests without credentials are skipped (the handler rejects them with
    401). Credentials are VERIFIED before any provider call: an invalid token
    is answered 401 here, so unauthenticated traffic can never spend
    moderation units. Verified users spend their daily budget on cache misses.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", "")
    if (request.method, path) not in MODERATED_ROUTES:
        return
    if not moderation_enabled() or not _has_credentials(request):
        return
    raw = await request.body()
    if not raw:
        return
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return  # not JSON (multipart etc.) - validated by the handler itself
    prompt = extract_prompt_text(body)
    if not prompt:
        return
    request_id = request_correlation_id(request)
    # Sync DB/httpx/redis clients inside a threadpool keep the event loop free.
    from starlette.concurrency import run_in_threadpool

    user_id = await run_in_threadpool(_verified_user_id, request, request_id)
    await run_in_threadpool(
        enforce_moderation,
        prompt,
        request_id=request_id,
        surface=f"{request.method} {path}",
        user_id=user_id,
    )
