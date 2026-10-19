"""``TrendPullProvider`` Protocol + name-keyed registry (trend ingestion).

Deliberately mirrors ``app/domains/broll/providers/base.py`` (the
``BrollGenProvider`` registry): a name-keyed map the service/worker layer can
consult to gate a pull (``is_enabled()``) before spending credits/scraping, and
that tests can monkeypatch with a fake provider.

Where the B-roll registry drives *AI clip generation*, this one drives *trend
ingestion* — pulling raw TikTok ``itemList`` post dicts for a hashtag, a native
sound, or the For-You feed, which the pure ``hashtag_analysis`` helpers fold into
the usage-count series the EXISTING ``trends.scoring`` scorer consumes.

Contract (identical graceful-degradation guarantee as the B-roll Protocol):
implementations MUST NOT raise on external I/O failure — they return ``None`` (or
``[]`` for the pull methods) so a failing scrape degrades gracefully instead of
crashing a reel job. A trend-pull failure never fails a render.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from loguru import logger


@runtime_checkable
class TrendPullProvider(Protocol):
    """Duck-typed contract every trend-ingestion backend must satisfy.

    Implementations MUST NOT raise on external I/O failure; they return ``None``
    or an empty list so a failing pull degrades gracefully. ``is_enabled()`` is
    the cheap pre-flight the service/worker checks before spending or scraping;
    it is gated on the configured default backend + transport availability. The
    per-user ToS *consent/allowlist* gate lives in :mod:`providers.consent` and
    is enforced by the service/worker BEFORE any of the ``pull_*`` calls.
    """

    name: str

    def is_enabled(self) -> bool:
        """True when this backend is the configured default AND ready to pull."""
        ...

    async def pull_hashtag_posts(self, tag: str, *, max_posts: int = 30) -> list[dict]:
        """Raw ``itemList`` post dicts tagged with ``tag`` (``[]`` on failure)."""
        ...

    async def pull_sound_posts(self, sound_id: str, *, max_posts: int = 30) -> list[dict]:
        """Raw ``itemList`` post dicts using native sound ``sound_id`` (``[]``)."""
        ...

    async def pull_trending(self, *, max_posts: int = 30) -> list[dict]:
        """Raw ``itemList`` post dicts from the For-You feed (``[]`` on failure)."""
        ...


# Populated at import time by concrete provider modules (e.g. tiktok_pull).
TREND_PULL_PROVIDERS: dict[str, TrendPullProvider] = {}

# Providers imported to seed the registry. Kept here (not in each module) so
# ``get_trend_pull_provider`` can lazily import without hardcoding module paths.
_DEFAULT_PROVIDER_MODULES: tuple[str, ...] = (
    "app.domains.trends.providers.tiktok_pull",
)
_DEFAULT_PROVIDER_ID: str = "tiktok"
_providers_loaded: bool = False


def register_trend_pull_provider(provider: TrendPullProvider) -> None:
    """Register a provider instance under its ``name`` (idempotent overwrite).

    Re-registering the same name overwrites the prior entry, which is what tests
    want when swapping in a fake provider.
    """
    name = getattr(provider, "name", "")
    if not name:
        logger.error("trend_pull provider missing a 'name' attribute; not registered")
        return
    TREND_PULL_PROVIDERS[name] = provider
    logger.debug(f"registered trend_pull provider: {name}")


def _ensure_providers_loaded() -> None:
    """Import default provider modules once so they self-register.

    Import failures are logged and swallowed — a missing optional dependency for
    one backend (e.g. Playwright absent) must not prevent resolving another
    already-registered one, nor crash a caller.
    """
    global _providers_loaded
    if _providers_loaded:
        return
    _providers_loaded = True
    for module_path in _DEFAULT_PROVIDER_MODULES:
        try:
            __import__(module_path)
        except Exception as exc:  # noqa: BLE001 - defensive: keep registry usable
            logger.error(
                f"failed to import trend_pull provider module {module_path}: {exc}"
            )


def _configured_default_id() -> str:
    """Default provider id: ``TREND_PULL_PROVIDER`` env wins, else ``tiktok``.

    Read from the environment (not app.config) so this module stays import-safe.
    """
    return (os.getenv("TREND_PULL_PROVIDER") or "").strip() or _DEFAULT_PROVIDER_ID


def get_trend_pull_provider(provider_id: str = "") -> TrendPullProvider:
    """Resolve a registered provider by id.

    With no ``provider_id`` the configured default (``TREND_PULL_PROVIDER`` env,
    else ``tiktok``) is used. Falls back to that default when an unknown id is
    requested so an out-of-date caller cannot hard-fail ingestion. Raises
    ``KeyError`` only when the registry is empty (no provider configured at all),
    a genuine deployment error worth surfacing.
    """
    _ensure_providers_loaded()

    default_id = _configured_default_id()
    if not provider_id:
        provider_id = default_id

    provider = TREND_PULL_PROVIDERS.get(provider_id)
    if provider is not None:
        return provider

    if provider_id != default_id:
        logger.warning(
            f"unknown trend_pull provider '{provider_id}', falling back to '{default_id}'"
        )
        fallback = TREND_PULL_PROVIDERS.get(default_id)
        if fallback is not None:
            return fallback

    raise KeyError(
        f"no trend_pull provider registered for '{provider_id}'; "
        f"available: {sorted(TREND_PULL_PROVIDERS)}"
    )
