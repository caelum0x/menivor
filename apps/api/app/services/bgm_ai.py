"""Best-effort AI background-music generation for ReelForge.

This is a thin adapter over MPT's already-vendored music-generation providers
(:mod:`app.services.elevenlabs_music` and :mod:`app.services.sonilo`). Both
expose the exact interface that :data:`app.services.task._VIDEO_MUSIC_PROVIDERS`
relies on:

* ``is_enabled() -> bool``
* ``generate_bgm(video_path, output_path, video_duration, prompt) -> str``
* a domain error type (``ElevenLabsMusicError`` / ``SoniloError``)
* ``MAX_PROMPT_LENGTH``

ReelForge only needs to *pick* an enabled provider, clamp the prompt and run the
generation — the heavy lifting (ffmpeg proxy, streaming, audio validation)
already lives in those provider modules, so nothing here re-implements MPT.

Everything in this module is **best-effort**: a missing optional dependency, a
disabled/misconfigured provider, or any generation failure resolves to ``None``
so the caller can compose the reel *without* background music. An AI-music
problem must NEVER fail the job.
"""

from __future__ import annotations

import os
from typing import Any, NamedTuple

from loguru import logger

__all__ = [
    "MusicProvider",
    "generate_ai_bgm",
    "resolve_provider",
]


class MusicProvider(NamedTuple):
    """A resolved music provider plus the metadata the caller needs.

    Mirrors an entry of :data:`app.services.task._VIDEO_MUSIC_PROVIDERS` but is
    built lazily (see :func:`_load_providers`) so an optional dependency issue in
    one provider module never breaks importing this module.
    """

    name: str
    service: Any
    error_type: type[BaseException]
    suffix: str
    content_type: str


# Resolution priority when no explicit provider is requested: the first ENABLED
# provider in this order wins. ElevenLabs shares the existing TTS account (so it
# is the most likely to already be configured), hence it leads.
_PROVIDER_ORDER: tuple[str, ...] = ("elevenlabs", "sonilo")


def _load_providers() -> dict[str, MusicProvider]:
    """Build the provider map lazily, guarding each optional import.

    The provider modules pull in ``requests``/ffmpeg-adjacent helpers; importing
    them defensively means a broken/absent provider is simply omitted from the
    map (with a warning) instead of taking down the whole ReelForge pipeline.
    """
    providers: dict[str, MusicProvider] = {}

    try:
        from app.services import elevenlabs_music

        providers["elevenlabs"] = MusicProvider(
            name="elevenlabs",
            service=elevenlabs_music,
            error_type=elevenlabs_music.ElevenLabsMusicError,
            suffix=".mp3",
            content_type="audio/mpeg",
        )
    except Exception as exc:  # noqa: BLE001 - optional provider import is guarded
        logger.warning(f"elevenlabs_music provider unavailable (skipped): {exc}")

    try:
        from app.services import sonilo

        providers["sonilo"] = MusicProvider(
            name="sonilo",
            service=sonilo,
            error_type=sonilo.SoniloError,
            suffix=".m4a",
            content_type="audio/mp4",
        )
    except Exception as exc:  # noqa: BLE001 - optional provider import is guarded
        logger.warning(f"sonilo provider unavailable (skipped): {exc}")

    return providers


def _is_enabled(provider: MusicProvider) -> bool:
    """Return whether ``provider`` is configured, swallowing lookup errors."""
    try:
        return bool(provider.service.is_enabled())
    except Exception as exc:  # noqa: BLE001 - a config probe must never raise up
        logger.warning(f"{provider.name} is_enabled() check failed: {exc}")
        return False


def resolve_provider(name: str = "") -> MusicProvider | None:
    """Resolve the music provider to use.

    * A non-empty ``name`` selects that specific provider — but only when it is
      enabled; an unknown or disabled name resolves to ``None``.
    * An empty ``name`` picks the first ENABLED provider in
      :data:`_PROVIDER_ORDER`.

    Returns ``None`` when nothing usable is available (the caller then composes
    without background music).
    """
    providers = _load_providers()
    wanted = (name or "").strip().lower()

    if wanted:
        provider = providers.get(wanted)
        if provider is None:
            logger.warning(f"unknown bgm_provider {name!r}; skipping AI music")
            return None
        if not _is_enabled(provider):
            logger.warning(
                f"bgm_provider {provider.name!r} is not enabled; skipping AI music"
            )
            return None
        return provider

    for candidate in _PROVIDER_ORDER:
        provider = providers.get(candidate)
        if provider is not None and _is_enabled(provider):
            return provider

    logger.info("no AI music provider is enabled; skipping AI music")
    return None


def _clamp_prompt(provider: MusicProvider, prompt: str) -> str:
    """Trim ``prompt`` to the provider's ``MAX_PROMPT_LENGTH`` (if any).

    The provider modules RAISE their domain error when a prompt exceeds the
    limit, so clamping up-front turns a hard failure into a graceful truncation.
    """
    text = str(prompt or "").strip()
    max_len = int(getattr(provider.service, "MAX_PROMPT_LENGTH", 0) or 0)
    if max_len > 0 and len(text) > max_len:
        logger.info(
            f"clamping {provider.name} music prompt "
            f"from {len(text)} to {max_len} characters"
        )
        return text[:max_len]
    return text


def generate_ai_bgm(
    *,
    video_path: str,
    output_dir: str,
    video_duration: float,
    prompt: str,
    provider_name: str = "",
) -> str | None:
    """Generate a custom BGM track (best-effort) and return its local path.

    Resolves an enabled provider (``provider_name`` or the first enabled one),
    clamps ``prompt`` to that provider's ``MAX_PROMPT_LENGTH`` and delegates to
    its ``generate_bgm``. On ANY failure — no enabled provider, the provider's
    domain error, or an unexpected exception — this returns ``None`` so the
    caller composes without music. It never raises.
    """
    provider = resolve_provider(provider_name)
    if provider is None:
        return None

    clamped_prompt = _clamp_prompt(provider, prompt)
    output_path = os.path.join(
        output_dir, f"ai-bgm-{provider.name}{provider.suffix}"
    )

    try:
        result = provider.service.generate_bgm(
            video_path=video_path,
            output_path=output_path,
            video_duration=video_duration,
            prompt=clamped_prompt,
        )
    except provider.error_type as exc:
        logger.warning(
            f"{provider.name} BGM generation failed (composing without music): {exc}"
        )
        return None
    except Exception as exc:  # noqa: BLE001 - AI music is strictly best-effort
        logger.warning(
            f"{provider.name} BGM generation raised unexpectedly "
            f"(composing without music): {exc}"
        )
        return None

    music_path = str(result or output_path)
    if not music_path or not os.path.isfile(music_path):
        logger.warning(
            f"{provider.name} reported success but produced no music file; "
            "composing without music"
        )
        return None

    logger.success(f"{provider.name} AI background music ready: {music_path}")
    return music_path


def content_type_for(music_path: str) -> str:
    """Best-effort R2 content-type for a generated music file by extension."""
    suffix = os.path.splitext(music_path)[1].lower()
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix in (".mp3", ""):
        return "audio/mpeg"
    return "application/octet-stream"
