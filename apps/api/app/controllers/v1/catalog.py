"""ReelForge Creator Studio catalog controller (Phase 6).

Read-only reference endpoints served under ``/api/v1`` via
:func:`app.controllers.v1.base.new_router`. They expose the pickable options the
wizard renders — caption styles, background-music tracks and composition
layouts — so the frontend never hard-codes ids that must stay in lock-step with
the render pipeline.

Design notes
------------
* **Non-sensitive, unauthenticated.** These catalogs contain no per-user data
  (they are the same for everyone), so they are intentionally not gated behind
  the ``x-api-key`` / Clerk auth used by the job endpoints — mirroring how a
  public "options" list is served. No DB access is performed here.
* **Import-safe & never-crash.** The caption/music services are imported lazily
  inside each handler and any failure degrades to an empty list (logged), so a
  misconfigured resource directory yields ``{"data": []}`` rather than a 500.
* Every response uses the MPT envelope ``utils.get_response(status, data)``.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.schema import (
    CaptionStylesResponse,
    CoverStylesResponse,
    HookCatalogResponse,
    LayoutCatalogResponse,
    MusicCatalogResponse,
    MusicGeneratorsResponse,
    SocialPlatformsResponse,
    TemplateCatalogResponse,
)
from app.utils import utils

router = new_router()


# Static composition-layout catalog. Ids MUST match ``ReelForgeParams.layout``
# and the compose service's supported layouts (``pip`` | ``hook_intro`` |
# ``split``); the human name + description are UI copy only.
_LAYOUTS: tuple[dict[str, str], ...] = (
    {
        "id": "pip",
        "name": "Picture-in-picture",
        "description": (
            "Avatar in a rounded corner bubble over a full-screen screen "
            "recording — the default UGC reaction look."
        ),
    },
    {
        "id": "hook_intro",
        "name": "Hook intro",
        "description": (
            "Full-screen talking avatar delivers the hook, then cuts to the "
            "screen recording for the walkthrough."
        ),
    },
    {
        "id": "split",
        "name": "Split screen",
        "description": (
            "Avatar and screen recording stacked side-by-side (or top/bottom) "
            "so both are visible for the whole reel."
        ),
    },
)


@router.get(
    "/catalog/caption-styles",
    response_model=CaptionStylesResponse,
    summary="List caption styles",
)
def list_caption_styles_catalog(request: Request):
    """Return the caption-style preset catalog (id, name, description, colours)."""
    request_id = base.get_task_id(request)
    try:
        from app.services.captions.presets import list_caption_styles

        styles: list[dict[str, Any]] = list_caption_styles()
    except Exception as exc:  # noqa: BLE001 - degrade to empty catalog, never 500
        logger.warning(
            f"caption-style catalog unavailable, request_id: {request_id}: {exc}"
        )
        styles = []
    return utils.get_response(200, styles)


@router.get(
    "/catalog/music",
    response_model=MusicCatalogResponse,
    summary="List background-music tracks",
)
def list_music_catalog(request: Request):
    """Return the background-music catalog (id, name, filename, optional duration)."""
    request_id = base.get_task_id(request)
    try:
        from app.services.music import list_music

        tracks: list[dict[str, Any]] = list_music()
    except Exception as exc:  # noqa: BLE001 - degrade to empty catalog, never 500
        logger.warning(f"music catalog unavailable, request_id: {request_id}: {exc}")
        tracks = []
    return utils.get_response(200, tracks)


# AI background-music generators the pipeline can dispatch to. Kept in lock-step
# with ``task._VIDEO_MUSIC_PROVIDERS``: ``id`` is the ``bgm_provider`` value the
# job API accepts, ``module`` is the vendored MPT integration exposing the shared
# ``is_enabled()`` / ``MAX_PROMPT_LENGTH`` interface, and ``name`` is UI copy.
_MUSIC_GENERATORS: tuple[dict[str, str], ...] = (
    {
        "id": "elevenlabs",
        "name": "ElevenLabs",
        "module": "app.services.elevenlabs_music",
    },
    {
        "id": "sonilo",
        "name": "Sonilo",
        "module": "app.services.sonilo",
    },
)


def _enabled_music_generators(request_id: str) -> list[dict[str, Any]]:
    """Return the AI-BGM providers whose credentials are configured.

    Each vendored provider module (``elevenlabs_music`` / ``sonilo``) exposes the
    same ``is_enabled()`` guard and ``MAX_PROMPT_LENGTH`` constant used by the
    render pipeline. Import + probe each one defensively: a missing dependency or
    a raising ``is_enabled()`` simply drops that provider (logged) instead of
    failing the whole catalog, so the endpoint degrades to ``[]`` rather than 500.
    """
    generators: list[dict[str, Any]] = []
    for entry in _MUSIC_GENERATORS:
        try:
            import importlib

            service = importlib.import_module(entry["module"])
            if not service.is_enabled():
                continue
            max_prompt_length = int(getattr(service, "MAX_PROMPT_LENGTH", 0) or 0)
        except Exception as exc:  # noqa: BLE001 - degrade per-provider, never 500
            logger.warning(
                f"music generator {entry['id']!r} unavailable, "
                f"request_id: {request_id}: {exc}"
            )
            continue
        generators.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "max_prompt_length": max_prompt_length,
            }
        )
    return generators


@router.get(
    "/catalog/music-generators",
    response_model=MusicGeneratorsResponse,
    summary="List enabled AI background-music generators",
)
def list_music_generators_catalog(request: Request):
    """Return the AI-music providers whose API keys are configured (``is_enabled``).

    Each entry is ``{id, name, max_prompt_length}`` for a provider the render
    pipeline can generate a custom BGM track with from a ``music_prompt``. The UI
    uses this to show "Generate with AI" only when at least one provider is
    available. Import-safe: a missing provider dependency degrades to an empty
    catalog (logged) rather than a 500, mirroring the other catalog handlers.
    """
    request_id = base.get_task_id(request)
    try:
        generators = _enabled_music_generators(request_id)
    except Exception as exc:  # noqa: BLE001 - degrade to empty catalog, never 500
        logger.warning(
            f"music-generators catalog unavailable, request_id: {request_id}: {exc}"
        )
        generators = []
    return utils.get_response(200, generators)


@router.get(
    "/catalog/layouts",
    response_model=LayoutCatalogResponse,
    summary="List composition layouts",
)
def list_layouts_catalog(request: Request):
    """Return the static composition-layout catalog (pip / hook_intro / split)."""
    # Copy each entry so the response cannot mutate the module-level constant.
    return utils.get_response(200, [dict(layout) for layout in _LAYOUTS])


@router.get(
    "/catalog/templates",
    response_model=TemplateCatalogResponse,
    summary="List job templates",
)
def list_templates_catalog(request: Request):
    """Return the curated job-template catalog (Phase 7 growth surface).

    Each template pre-fills a sane UGC job configuration (subject hint, prompt
    scaffold, layout, caption style, language, duration) so a new user can go
    from an empty form to a ready reel in one click.
    """
    request_id = base.get_task_id(request)
    try:
        from app.services.templates import list_templates

        templates: list[dict[str, Any]] = list_templates()
    except Exception as exc:  # noqa: BLE001 - degrade to empty catalog, never 500
        logger.warning(
            f"template catalog unavailable, request_id: {request_id}: {exc}"
        )
        templates = []
    return utils.get_response(200, templates)


@router.get(
    "/catalog/dub-languages",
    summary="List supported dubbing languages",
)
@router.get(
    "/dub/languages",
    summary="List supported dubbing languages (dub-flow alias)",
)
def list_dub_languages_catalog(request: Request):
    """Return the languages a finished reel can be dubbed into (multi-language dubbing).

    Sourced from ``translate.SUPPORTED_DUB_LANGUAGES`` (the codes whose glyphs
    the bundled fonts and the ElevenLabs multilingual model cover) as a list of
    ``{code, name}`` entries. Import-safe: a failure to load the translate module
    degrades to an empty catalog (logged) rather than a 500, mirroring the other
    catalog handlers. Each entry is copied so the response can never mutate the
    module-level constant.
    """
    request_id = base.get_task_id(request)
    try:
        from app.services.translate import SUPPORTED_DUB_LANGUAGES

        languages: list[dict[str, Any]] = [dict(entry) for entry in SUPPORTED_DUB_LANGUAGES]
    except Exception as exc:  # noqa: BLE001 - degrade to empty catalog, never 500
        logger.warning(
            f"dub-languages catalog unavailable, request_id: {request_id}: {exc}"
        )
        languages = []
    return utils.get_response(200, languages)


@router.get(
    "/catalog/cover-styles",
    response_model=CoverStylesResponse,
    summary="List cover / thumbnail styles",
)
def list_cover_styles_catalog(request: Request):
    """Return the cover/thumbnail style catalog (id, name) for the generator UI.

    Sourced from :func:`app.services.cover.list_cover_styles`. Import-safe: a
    failure to load the cover module degrades to an empty catalog (logged)
    rather than a 500, mirroring the other catalog handlers.
    """
    request_id = base.get_task_id(request)
    try:
        from app.services.cover import list_cover_styles

        styles: list[dict[str, Any]] = list_cover_styles()
    except Exception as exc:  # noqa: BLE001 - degrade to empty catalog, never 500
        logger.warning(
            f"cover-style catalog unavailable, request_id: {request_id}: {exc}"
        )
        styles = []
    return utils.get_response(200, styles)


@router.get(
    "/catalog/social-platforms",
    response_model=SocialPlatformsResponse,
    summary="List supported social-caption platforms",
)
def list_social_platforms_catalog(request: Request):
    """Return the platforms the AI social-caption endpoint can tailor copy for.

    Each entry is ``{id, name}`` for a platform accepted by
    ``POST /api/v1/jobs/{job_id}/social`` (``tiktok`` / ``instagram`` /
    ``youtube_shorts``). Sourced from the single source of truth in the social
    controller so the two never drift. Import-safe: a failure to load that module
    degrades to an empty catalog (logged) rather than a 500, mirroring the other
    catalog handlers.
    """
    request_id = base.get_task_id(request)
    try:
        from app.controllers.v1.social import _SUPPORTED_PLATFORMS

        platforms: list[dict[str, Any]] = [
            {"id": pid, "name": spec["name"]}
            for pid, spec in _SUPPORTED_PLATFORMS.items()
        ]
    except Exception as exc:  # noqa: BLE001 - degrade to empty catalog, never 500
        logger.warning(
            f"social-platforms catalog unavailable, request_id: {request_id}: {exc}"
        )
        platforms = []
    return utils.get_response(200, platforms)


@router.get(
    "/catalog/hooks",
    response_model=HookCatalogResponse,
    summary="List native hooks by language",
)
def list_hooks_catalog(request: Request):
    """Return the native hook catalog keyed by language (Phase 7 hook browser).

    Powers a hook-browser UI over ``resource/hooks/<lang>.yaml``. A malformed or
    missing resource degrades to an empty catalog (never a 500).
    """
    request_id = base.get_task_id(request)
    try:
        from app.services.templates import list_hooks

        hooks: dict[str, list[str]] = list_hooks()
    except Exception as exc:  # noqa: BLE001 - degrade to empty catalog, never 500
        logger.warning(f"hook catalog unavailable, request_id: {request_id}: {exc}")
        hooks = {}
    return utils.get_response(200, hooks)
