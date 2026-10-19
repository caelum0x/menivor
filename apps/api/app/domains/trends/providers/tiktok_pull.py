"""TikTok pull transport + ``TrendPullProvider`` (``name='tiktok'``).

Ported and trimmed from ``external/tiktok-api`` (``TikTokApi/tiktok.py`` +
``api/{hashtag,sound,trending,video}.py``). The monolithic ``TikTokApi`` class is
split into two collaborators so the network layer is fully substitutable in
tests:

* :class:`PlaywrightPullTransport` — the real signing + in-page ``fetch``
  transport (async session pool, ``sign_url``/``generate_x_bogus``,
  ``_get_valid_session_index``/``_recover_sessions``/``health_check``). Playwright
  is an OPTIONAL import: absent, the transport reports ``is_ready() == False`` and
  the provider degrades to ``is_enabled() == False`` — it never crashes a job.
* :class:`TikTokPullClient` — transport-agnostic request assembly:
  ``make_request`` (session-param merge + msToken + ``sign_url`` + fetch-in-page +
  retry/backoff + JSON decode) and the ``pull_hashtag_posts`` /
  ``pull_sound_posts`` / ``pull_trending`` endpoints returning raw ``itemList``
  dicts. Any transport it is handed satisfies :class:`PullTransport`, so tests
  inject a fake that returns canned JSON — no real network.

``requests`` / ``matplotlib`` / ``seaborn`` / ``yt_dlp`` are dropped;
``proxyproviders`` is an optional ``try/except`` import.

--------------------------------------------------------------------------------
MIT NOTICE
This file adapts code from davidteather/TikTok-Api
(https://github.com/davidteather/TikTok-Api), licensed under the MIT License.
Original copyright (c) David Teather and contributors. See that project for the
full license text.
--------------------------------------------------------------------------------
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import random
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote, urlencode

from loguru import logger

from app.domains.trends.providers._stealth import (
    EmptyResponseException,
    InvalidJSONException,
    random_choice,
    stealth_async,
)
from app.domains.trends.providers.base import (
    _configured_default_id,
    register_trend_pull_provider,
)

# ``proxyproviders`` is optional; absence simply disables smart proxy rotation.
try:  # pragma: no cover - optional dependency
    from proxyproviders import ProxyProvider  # type: ignore
except Exception:  # noqa: BLE001
    ProxyProvider = None  # type: ignore

# Playwright is optional. When absent, the real transport can never be ready and
# the provider degrades to disabled — importing this module still succeeds.
try:  # pragma: no cover - environment dependent
    from playwright.async_api import async_playwright  # type: ignore

    _PLAYWRIGHT_AVAILABLE = True
except Exception:  # noqa: BLE001
    async_playwright = None  # type: ignore
    _PLAYWRIGHT_AVAILABLE = False

_BASE_URL = "https://www.tiktok.com"
_HASHTAG_DETAIL_URL = f"{_BASE_URL}/api/challenge/detail/"
_HASHTAG_ITEMS_URL = f"{_BASE_URL}/api/challenge/item_list/"
_SOUND_ITEMS_URL = f"{_BASE_URL}/api/music/item_list/"
_TRENDING_URL = f"{_BASE_URL}/api/recommend/item_list/"
_PAGE_SIZE = 30
_MAX_PAGES = 20  # hard cap so a broken ``hasMore`` can't loop forever


@runtime_checkable
class PullTransport(Protocol):
    """The substitutable network seam the client drives.

    A real implementation signs + fetches through a browser session; a test
    double returns canned JSON. Implementations should not raise on transport
    failure — return ``None`` from :meth:`fetch` so the client's retry/degrade
    path stays in control.
    """

    def is_ready(self) -> bool:
        """True when at least one usable session/transport is available."""
        ...

    def ms_token(self) -> str | None:
        """The current session's msToken, if known (else ``None``)."""
        ...

    async def sign_url(self, url: str, *, session_index: int | None = None) -> str:
        """Return ``url`` with the platform anti-bot signature appended."""
        ...

    async def fetch(
        self, signed_url: str, headers: dict | None = None, *, session_index: int | None = None
    ) -> str | None:
        """Fetch ``signed_url`` in-session; return the raw body text or ``None``."""
        ...


@dataclasses.dataclass
class PullSession:
    """A single browser-backed session (context + page + captured headers)."""

    context: Any
    page: Any
    params: dict | None = None
    headers: dict | None = None
    ms_token: str | None = None
    base_url: str = _BASE_URL
    is_valid: bool = True


class PlaywrightPullTransport:
    """Real signing + in-page fetch transport (async session pool).

    Faithful trim of the upstream ``TikTokApi`` transport internals:
    ``create_sessions``/``close_sessions``, ``_get_valid_session_index``,
    ``_recover_sessions``, ``sign_url`` (via ``generate_x_bogus``), the in-page
    ``fetch`` script, and ``health_check``. Session/page creation is injectable
    via ``page_factory``/``browser_context_factory`` so a caller (or a test) can
    substitute a custom launcher without a real browser.
    """

    def __init__(self) -> None:
        self.sessions: list[PullSession] = []
        self.browser: Any = None
        self.playwright: Any = None
        self._proxy_provider = None
        self._session_creation_lock = asyncio.Lock()
        self._recovery_enabled = True

    # -- lifecycle --------------------------------------------------------- #
    def is_ready(self) -> bool:
        return _PLAYWRIGHT_AVAILABLE and any(s.is_valid for s in self.sessions)

    def ms_token(self) -> str | None:
        for session in self.sessions:
            if session.is_valid and session.ms_token:
                return session.ms_token
        return None

    async def create_sessions(
        self,
        *,
        num_sessions: int = 1,
        headless: bool = True,
        ms_tokens: list[str] | None = None,
        proxies: list[dict] | None = None,
        proxy_provider: Any = None,
        starting_url: str = _BASE_URL,
        page_factory: Any = None,
        browser_context_factory: Any = None,
        timeout: int = 30000,
    ) -> None:
        """Launch a browser + ``num_sessions`` primed pages. Requires Playwright."""
        if not _PLAYWRIGHT_AVAILABLE:
            logger.warning("trend_pull: Playwright not installed; cannot create sessions")
            return
        self._proxy_provider = proxy_provider if ProxyProvider is not None else None
        self.playwright = await async_playwright().start()
        if browser_context_factory is not None:
            self.browser = await browser_context_factory(self.playwright)
        else:
            args = ["--headless=new"] if headless else None
            self.browser = await self.playwright.chromium.launch(
                headless=False if headless else False,
                args=args,
                proxy=random_choice(proxies),
            )
        await asyncio.gather(
            *(
                self._create_session(
                    ms_token=random_choice(ms_tokens),
                    starting_url=starting_url,
                    page_factory=page_factory,
                    timeout=timeout,
                )
                for _ in range(max(1, num_sessions))
            ),
            return_exceptions=True,
        )

    async def _create_session(
        self, *, ms_token, starting_url, page_factory, timeout
    ) -> None:
        try:
            cookies = {"msToken": ms_token} if ms_token else None
            if page_factory is not None:
                context = self.browser
                page = await page_factory(context)
            else:
                context = await self.browser.new_context()
                if cookies:
                    await context.add_cookies(
                        [
                            {"name": k, "value": v, "domain": "www.tiktok.com", "path": "/"}
                            for k, v in cookies.items()
                        ]
                    )
                page = await context.new_page()
                await stealth_async(page)
                page.set_default_navigation_timeout(timeout)
                await page.goto(starting_url)
            self.sessions.append(
                PullSession(context=context, page=page, ms_token=ms_token, is_valid=True)
            )
        except Exception as exc:  # noqa: BLE001 - one failed session must not abort the pool
            logger.warning(f"trend_pull: session creation failed: {exc}")

    async def close_sessions(self) -> None:
        for session in self.sessions:
            for closer in (getattr(session.page, "close", None), getattr(session.context, "close", None)):
                try:
                    if closer:
                        await closer()
                except Exception:  # noqa: BLE001
                    pass
        self.sessions.clear()
        for stop in (getattr(self.browser, "close", None), getattr(self.playwright, "stop", None)):
            try:
                if stop:
                    await stop()
            except Exception:  # noqa: BLE001
                pass
        self.browser = None
        self.playwright = None

    # -- session selection ------------------------------------------------- #
    def _is_valid(self, session: PullSession) -> bool:
        if not session.is_valid:
            return False
        try:
            _ = session.page.url
            return True
        except Exception:  # noqa: BLE001
            session.is_valid = False
            return False

    async def _recover_sessions(self) -> None:
        async with self._session_creation_lock:
            self.sessions = [s for s in self.sessions if self._is_valid(s)]

    async def _get_valid_session_index(
        self, session_index: int | None = None
    ) -> tuple[int, PullSession]:
        for attempt in range(3):
            if session_index is not None and session_index < len(self.sessions):
                session = self.sessions[session_index]
                if self._is_valid(session):
                    return session_index, session
            else:
                valid = [(i, s) for i, s in enumerate(self.sessions) if self._is_valid(s)]
                if valid:
                    return random.choice(valid)
            if self._recovery_enabled and attempt < 2:
                await self._recover_sessions()
        raise EmptyResponseException("no valid trend_pull sessions available")

    # -- signing + fetch --------------------------------------------------- #
    async def _generate_x_bogus(self, url: str, session: PullSession) -> str | None:
        await session.page.wait_for_function(
            "window.byted_acrawler !== undefined", timeout=15000
        )
        result = await session.page.evaluate(
            f'() => {{ return window.byted_acrawler.frontierSign("{url}") }}'
        )
        return (result or {}).get("X-Bogus")

    async def sign_url(self, url: str, *, session_index: int | None = None) -> str:
        i, session = await self._get_valid_session_index(session_index)
        x_bogus = await self._generate_x_bogus(url, session)
        if not x_bogus:
            raise EmptyResponseException("failed to generate X-Bogus signature")
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}X-Bogus={x_bogus}"

    async def fetch(
        self, signed_url: str, headers: dict | None = None, *, session_index: int | None = None
    ) -> str | None:
        try:
            _, session = await self._get_valid_session_index(session_index)
            script = (
                "() => { return new Promise((resolve, reject) => {"
                f"fetch('{signed_url}', {{ method: 'GET', headers: {json.dumps(headers or {})} }})"
                ".then(r => r.text()).then(resolve).catch(e => reject(e.message)); }); }"
            )
            return await session.page.evaluate(script)
        except Exception as exc:  # noqa: BLE001 - transport failure -> client degrades
            logger.warning(f"trend_pull: in-page fetch failed: {exc}")
            return None

    async def health_check(self) -> dict:
        valid = sum(1 for s in self.sessions if self._is_valid(s))
        return {
            "total_sessions": len(self.sessions),
            "healthy_sessions": valid,
            "playwright_available": _PLAYWRIGHT_AVAILABLE,
            "ready": self.is_ready(),
        }


class TikTokPullClient:
    """Transport-agnostic TikTok request assembly + trend pull endpoints.

    Holds a :class:`PullTransport` (real Playwright transport in production, a
    fake in tests). All endpoint methods return raw ``itemList`` post dicts and
    NEVER raise on I/O failure — they return ``[]`` so a scrape degrades
    gracefully.
    """

    def __init__(self, transport: PullTransport | None = None) -> None:
        self._transport: PullTransport = transport or PlaywrightPullTransport()

    @property
    def transport(self) -> PullTransport:
        return self._transport

    def is_ready(self) -> bool:
        try:
            return bool(self._transport.is_ready())
        except Exception:  # noqa: BLE001
            return False

    async def make_request(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        *,
        retries: int = 3,
        exponential_backoff: bool = True,
    ) -> dict | None:
        """Sign + fetch ``url`` with merged params; decode JSON with retry/backoff.

        Merges default web params + the caller's ``params``, injects the session
        ``msToken``, signs via the transport, fetches in-session, and decodes the
        body. Returns the decoded dict, or ``None`` on any unrecoverable failure
        (the graceful-degradation contract — the caller yields ``[]``).
        """
        if not self.is_ready():
            return None

        merged = {**_default_params(), **(params or {})}
        if merged.get("msToken") is None:
            merged["msToken"] = self._safe_ms_token()

        encoded = f"{url}?{urlencode(merged, safe='=', quote_via=quote)}"
        try:
            signed = await self._transport.sign_url(encoded)
        except Exception as exc:  # noqa: BLE001 - signing failure -> degrade
            logger.warning(f"trend_pull: sign_url failed for {url}: {exc}")
            return None

        for attempt in range(1, max(1, retries) + 1):
            try:
                body = await self._transport.fetch(signed, headers)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"trend_pull: fetch raised for {url}: {exc}")
                body = None
            if body is None:
                if attempt >= retries:
                    return None
                await self._backoff(attempt, exponential_backoff)
                continue
            if body == "":
                logger.warning("trend_pull: empty response (bot detection?)")
                if attempt >= retries:
                    return None
                await self._backoff(attempt, exponential_backoff)
                continue
            try:
                return json.loads(body)
            except (json.JSONDecodeError, TypeError) as exc:
                if attempt >= retries:
                    # Surface the decode failure in the log via the ported
                    # exception type, but still degrade to ``None`` (never raise).
                    logger.error(
                        f"trend_pull: {InvalidJSONException.__name__}: could not "
                        f"decode response: {exc}"
                    )
                    return None
                await self._backoff(attempt, exponential_backoff)
        return None

    def _safe_ms_token(self) -> str | None:
        try:
            return self._transport.ms_token()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    async def _backoff(attempt: int, exponential: bool) -> None:
        await asyncio.sleep(2**attempt if exponential else 1)

    # -- endpoints --------------------------------------------------------- #
    async def pull_hashtag_posts(self, tag: str, *, max_posts: int = _PAGE_SIZE) -> list[dict]:
        """Raw posts tagged ``tag``: resolve challenge id, then paginate items."""
        tag = str(tag or "").strip().lstrip("#")
        if not tag:
            return []
        detail = await self.make_request(_HASHTAG_DETAIL_URL, {"challengeName": tag})
        challenge_id = _extract_challenge_id(detail)
        if not challenge_id:
            return []
        return await self._paginate(
            _HASHTAG_ITEMS_URL, {"challengeID": challenge_id, "count": _PAGE_SIZE}, max_posts
        )

    async def pull_sound_posts(self, sound_id: str, *, max_posts: int = _PAGE_SIZE) -> list[dict]:
        """Raw posts using native sound ``sound_id`` (paginated)."""
        sound_id = str(sound_id or "").strip()
        if not sound_id:
            return []
        return await self._paginate(
            _SOUND_ITEMS_URL, {"musicID": sound_id, "count": _PAGE_SIZE}, max_posts
        )

    async def pull_trending(self, *, max_posts: int = _PAGE_SIZE) -> list[dict]:
        """Raw posts from the For-You feed (paginated)."""
        return await self._paginate(
            _TRENDING_URL, {"from_page": "fyp", "count": _PAGE_SIZE}, max_posts
        )

    async def _paginate(self, url: str, base_params: dict, max_posts: int) -> list[dict]:
        """Collect ``itemList`` entries across cursor pages up to ``max_posts``."""
        collected: list[dict] = []
        cursor = 0
        for _ in range(_MAX_PAGES):
            if len(collected) >= max_posts:
                break
            resp = await self.make_request(url, {**base_params, "cursor": cursor})
            if not resp:
                break
            items = resp.get("itemList") or []
            collected.extend(items)
            if not resp.get("hasMore"):
                break
            cursor = resp.get("cursor", cursor + _PAGE_SIZE)
        return collected[:max_posts]

    async def health_check(self) -> dict:
        try:
            return await self._transport.health_check()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return {"ready": self.is_ready()}


def _default_params() -> dict:
    """The stable web params every TikTok API request carries."""
    return {
        "aid": "1988",
        "app_language": "en",
        "app_name": "tiktok_web",
        "channel": "tiktok_web",
        "device_platform": "web_pc",
        "region": "US",
        "priority_region": "",
        "os": "mac",
        "referer": "",
        "cookie_enabled": "true",
        "screen_width": "1920",
        "screen_height": "1080",
        "browser_language": "en-US",
        "browser_platform": "MacIntel",
        "browser_name": "Mozilla",
        "browser_version": "5.0",
        "browser_online": "true",
        "timezone_name": "America/New_York",
    }


def _extract_challenge_id(detail: dict | None) -> str | None:
    """Pull the numeric challenge id out of a ``challenge/detail`` response."""
    if not isinstance(detail, dict):
        return None
    info = detail.get("challengeInfo") or {}
    challenge = info.get("challenge") or {}
    challenge_id = challenge.get("id")
    return str(challenge_id) if challenge_id else None


class TikTokPullProvider:
    """``TrendPullProvider`` backed by :class:`TikTokPullClient`.

    ``is_enabled()`` gates on being the configured default backend AND the
    transport being ready; the per-user ToS consent/allowlist gate is enforced
    separately by the service/worker (see ``providers.consent``). All pull
    methods delegate to the client and inherit its never-raise contract.
    """

    name = "tiktok"

    def __init__(self, client: TikTokPullClient | None = None) -> None:
        self._client = client or TikTokPullClient()

    @property
    def client(self) -> TikTokPullClient:
        return self._client

    def is_enabled(self) -> bool:
        if _configured_default_id() != self.name:
            return False
        return self._client.is_ready()

    async def pull_hashtag_posts(self, tag: str, *, max_posts: int = _PAGE_SIZE) -> list[dict]:
        try:
            return await self._client.pull_hashtag_posts(tag, max_posts=max_posts)
        except Exception as exc:  # noqa: BLE001 - graceful degradation
            logger.warning(f"trend_pull: pull_hashtag_posts failed for {tag!r}: {exc}")
            return []

    async def pull_sound_posts(self, sound_id: str, *, max_posts: int = _PAGE_SIZE) -> list[dict]:
        try:
            return await self._client.pull_sound_posts(sound_id, max_posts=max_posts)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"trend_pull: pull_sound_posts failed for {sound_id!r}: {exc}")
            return []

    async def pull_trending(self, *, max_posts: int = _PAGE_SIZE) -> list[dict]:
        try:
            return await self._client.pull_trending(max_posts=max_posts)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"trend_pull: pull_trending failed: {exc}")
            return []


# Self-register the default provider instance at import time (mirrors broll).
register_trend_pull_provider(TikTokPullProvider())
