"""TalkingHeadProvider Protocol + provider registry (§2.3).

Registry shape intentionally mirrors MPT's ``_VIDEO_MUSIC_PROVIDERS``
(``app/services/task.py``): a name-keyed map that the orchestration layer
can consult to gate a run (``is_enabled()``) before spending LLM/TTS budget,
and that tests can monkeypatch with a fake provider.

Providers register themselves at import time (see ``avatar/heygen.py``).
``get_avatar_provider`` lazily triggers the default provider import so callers
never touch a concrete backend module directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from loguru import logger


@runtime_checkable
class TalkingHeadProvider(Protocol):
    """Duck-typed contract every avatar backend must satisfy.

    Implementations MUST NOT raise on external I/O failure; they return
    ``None`` (or an empty list for ``list_avatars``) so a failing avatar
    stage degrades gracefully instead of crashing the pipeline.
    """

    name: str

    def is_enabled(self) -> bool:
        """True when the provider is configured (e.g. api key present)."""
        ...

    def list_avatars(self) -> list[dict]:
        """Return the provider's available avatars (empty list on failure)."""
        ...

    def generate_avatar(
        self,
        audio_url: str,
        avatar_id: str,
        *,
        width: int = 1080,
        height: int = 1920,
        background: dict | None = None,
        expected_duration_s: float | None = None,
        timeout_s: float = 1800.0,
        character_kind: str = "avatar",
    ) -> dict | None:
        """Render a lip-synced avatar clip driven by external audio.

        ``character_kind`` selects the driven subject: ``'avatar'`` (a HeyGen
        catalog/instant avatar, the default) or ``'talking_photo'`` (a
        creator-uploaded photo turned into a talking-photo avatar). For
        ``'talking_photo'`` the ``avatar_id`` carries the provider's
        ``talking_photo_id``. Providers that do not model HeyGen character types
        (e.g. reference-image drivers) MUST accept and ignore the argument.

        Returns ``{'avatar_video': <local_path>, 'duration': float,
        'provider_video_id': str}`` or ``None`` on failure/timeout.
        """
        ...


# Populated at import time by concrete provider modules (e.g. heygen).
AVATAR_PROVIDERS: dict[str, TalkingHeadProvider] = {}

# Providers imported to seed the registry. Kept here (not in each module) so
# ``get_avatar_provider`` can lazily import without hardcoding module paths in
# multiple places.
_DEFAULT_PROVIDER_MODULES: tuple[str, ...] = ("app.services.avatar.heygen",)
_DEFAULT_PROVIDER_ID: str = "heygen"
_providers_loaded: bool = False


def register_avatar_provider(provider: TalkingHeadProvider) -> None:
    """Register a provider instance under its ``name``.

    Idempotent: re-registering the same name overwrites the prior entry,
    which is what tests want when swapping in a fake provider.
    """
    name = getattr(provider, "name", "")
    if not name:
        logger.error("avatar provider missing a 'name' attribute; not registered")
        return
    AVATAR_PROVIDERS[name] = provider
    logger.debug(f"registered avatar provider: {name}")


def _ensure_providers_loaded() -> None:
    """Import default provider modules once so they self-register.

    Import failures are logged and swallowed — a missing optional dependency
    for one backend must not prevent resolving another already-registered one.
    """
    global _providers_loaded
    if _providers_loaded:
        return
    _providers_loaded = True
    for module_path in _DEFAULT_PROVIDER_MODULES:
        try:
            __import__(module_path)
        except Exception as exc:  # noqa: BLE001 - defensive: keep registry usable
            logger.error(f"failed to import avatar provider module {module_path}: {exc}")


def get_avatar_provider(provider_id: str = "heygen") -> TalkingHeadProvider:
    """Resolve a registered provider by id.

    Falls back to the default provider id when an unknown id is requested,
    so an out-of-date client value cannot hard-fail the pipeline. Raises
    ``KeyError`` only if the registry is empty (no provider configured at all),
    which is a genuine deployment error worth surfacing.
    """
    _ensure_providers_loaded()

    provider = AVATAR_PROVIDERS.get(provider_id)
    if provider is not None:
        return provider

    if provider_id != _DEFAULT_PROVIDER_ID:
        logger.warning(
            f"unknown avatar provider '{provider_id}', "
            f"falling back to '{_DEFAULT_PROVIDER_ID}'"
        )
        fallback = AVATAR_PROVIDERS.get(_DEFAULT_PROVIDER_ID)
        if fallback is not None:
            return fallback

    raise KeyError(
        f"no avatar provider registered for '{provider_id}'; "
        f"available: {sorted(AVATAR_PROVIDERS)}"
    )
