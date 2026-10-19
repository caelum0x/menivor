"""Job-TEMPLATE and hook catalog for the ReelForge UGC pipeline.

This module powers two growth/product surfaces:

1. **Job templates** — a curated set of named, ready-to-run UGC formats
   ("App demo", "POV", "3 apps that…", "Before/After", "Founder story").
   Each template pre-fills a job configuration (subject hint, prompt scaffold,
   suggested compose ``layout``, ``caption_style``, ``language`` and
   ``target_duration_s``) so a new user can go from an empty form to a sane
   reel in one click.

2. **Hook browser** — thin, JSON-serializable accessors over the native hook
   catalogs stored in ``resource/hooks/<lang>.yaml`` (the very same files that
   ``app.services.script.ugc`` consumes as few-shot examples).

Public API::

    list_templates() -> list[dict]
    get_template(template_id: str) -> dict | None
    load_hooks(language: str) -> list[str]
    list_hooks() -> dict[str, list[str]]

Design notes:

* Templates are authored as :class:`JobTemplate` **frozen dataclasses** so the
  catalog is immutable at runtime (mutation raises ``FrozenInstanceError``).
* Every template is validated against the *real* compose layout ids, caption
  style preset ids and supported language codes at import time, so a typo in a
  template surfaces immediately rather than at job-submission time. Those
  registries are imported *optionally* (guarded) so this module keeps working —
  falling back to static allow-lists — even if the heavier compose/caption
  modules cannot be imported in a given environment.
* All resource I/O is defensive: a missing or malformed YAML file yields an
  empty hook list and a logged warning instead of crashing a request.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from types import MappingProxyType
from typing import Mapping

from loguru import logger

from app.utils import utils

# --------------------------------------------------------------------------- #
# Optional imports of the authoritative registries (guarded).
#
# We cross-check every template against these so an invalid layout / caption
# style / language cannot ship. If the heavy modules are unavailable we fall
# back to the static allow-lists below, which mirror the current registries.
# --------------------------------------------------------------------------- #
_FALLBACK_LAYOUT_IDS: frozenset[str] = frozenset({"hook_intro", "pip", "split"})
_FALLBACK_CAPTION_STYLE_IDS: frozenset[str] = frozenset(
    {"karaoke_yellow", "karaoke_green", "clean_white", "bold_violet"}
)
# Persona codes accepted by app.services.script.ugc (native TR / native EN).
_SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"tr", "en", "auto"})

# Hook catalogs authored natively per language.
_HOOK_LANGUAGES: tuple[str, ...] = ("tr", "en")


def _load_allowed_layout_ids() -> frozenset[str]:
    """Return the real compose layout ids, or a static fallback on import error."""
    try:
        from app.services.compose.compose_ffmpeg import _LAYOUTS  # type: ignore

        ids = frozenset(str(k) for k in _LAYOUTS)
        return ids or _FALLBACK_LAYOUT_IDS
    except Exception as exc:  # noqa: BLE001 - optional dependency; never hard-fail
        logger.debug(f"compose layout registry unavailable, using fallback: {exc}")
        return _FALLBACK_LAYOUT_IDS


def _load_allowed_caption_style_ids() -> frozenset[str]:
    """Return the real caption-style preset ids, or a static fallback."""
    try:
        from app.services.captions.presets import CAPTION_STYLE_PRESETS  # type: ignore

        ids = frozenset(str(k) for k in CAPTION_STYLE_PRESETS)
        return ids or _FALLBACK_CAPTION_STYLE_IDS
    except Exception as exc:  # noqa: BLE001 - optional dependency; never hard-fail
        logger.debug(f"caption style registry unavailable, using fallback: {exc}")
        return _FALLBACK_CAPTION_STYLE_IDS


_ALLOWED_LAYOUT_IDS: frozenset[str] = _load_allowed_layout_ids()
_ALLOWED_CAPTION_STYLE_IDS: frozenset[str] = _load_allowed_caption_style_ids()


# --------------------------------------------------------------------------- #
# Template model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class JobTemplate:
    """An immutable, pre-filled UGC job configuration.

    Attributes:
        id: Stable machine id (kebab/snake) used by ``get_template``.
        name: Human-friendly display name, e.g. ``"App demo"``.
        description: One-line explanation shown in the template picker.
        video_subject: A concrete subject *hint* pre-filled into the job form.
        prompt_scaffold: A reusable script-brief scaffold that steers the LLM.
            The ``{subject}`` placeholder is filled with the user's subject.
        layout: Suggested compose layout id (one of the real ``_LAYOUTS`` keys).
        caption_style: Suggested caption style preset id.
        language: Persona/language code (``"tr"``, ``"en"`` or ``"auto"``).
        target_duration_s: Suggested target reel duration in seconds.
        tags: Optional free-form discovery tags.
    """

    id: str
    name: str
    description: str
    video_subject: str
    prompt_scaffold: str
    layout: str
    caption_style: str
    language: str
    target_duration_s: int
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Fail fast on an internally inconsistent template definition."""
        if not self.id or not self.id.strip():
            raise ValueError("JobTemplate.id must be a non-empty string")
        if self.layout not in _ALLOWED_LAYOUT_IDS:
            raise ValueError(
                f"JobTemplate {self.id!r}: unknown layout {self.layout!r}; "
                f"expected one of {sorted(_ALLOWED_LAYOUT_IDS)}"
            )
        if self.caption_style not in _ALLOWED_CAPTION_STYLE_IDS:
            raise ValueError(
                f"JobTemplate {self.id!r}: unknown caption_style "
                f"{self.caption_style!r}; expected one of "
                f"{sorted(_ALLOWED_CAPTION_STYLE_IDS)}"
            )
        if self.language not in _SUPPORTED_LANGUAGES:
            raise ValueError(
                f"JobTemplate {self.id!r}: unknown language {self.language!r}; "
                f"expected one of {sorted(_SUPPORTED_LANGUAGES)}"
            )
        if self.target_duration_s <= 0:
            raise ValueError(
                f"JobTemplate {self.id!r}: target_duration_s must be positive"
            )

    def to_dict(self) -> dict:
        """Return a plain, JSON-serializable dict (tuples become lists)."""
        data = asdict(self)
        data["tags"] = list(self.tags)
        # Nested ``config`` mirrors the fields a job-submission form consumes so
        # a client can spread it directly onto a create-job payload.
        data["config"] = {
            "video_subject": self.video_subject,
            "prompt_scaffold": self.prompt_scaffold,
            "layout": self.layout,
            "caption_style": self.caption_style,
            "language": self.language,
            "target_duration_s": self.target_duration_s,
        }
        return data


# --------------------------------------------------------------------------- #
# Template catalog
# --------------------------------------------------------------------------- #
_TEMPLATES: tuple[JobTemplate, ...] = (
    JobTemplate(
        id="app_demo",
        name="App demo",
        description=(
            "Show a product/app in action with a screen-forward layout and a "
            "punchy value-prop voiceover."
        ),
        video_subject="a productivity app that automates your to-do list",
        prompt_scaffold=(
            "You are a real user casually demoing {subject}. Open with a "
            "relatable pain point, show the single best feature in action, and "
            "close with why it saves time. Keep it authentic, not salesy."
        ),
        layout="pip",
        caption_style="karaoke_yellow",
        language="en",
        target_duration_s=30,
        tags=("product", "demo", "saas"),
    ),
    JobTemplate(
        id="pov",
        name="POV",
        description=(
            "First-person point-of-view story that drops the viewer into a "
            "scenario for maximum relatability."
        ),
        video_subject="finally finding an app that fixes your morning routine",
        prompt_scaffold=(
            "Write in second-person POV about {subject}. Start with 'POV:' and "
            "a vivid scene, build a tiny emotional arc, and end on a satisfying "
            "payoff. Short, punchy sentences."
        ),
        layout="hook_intro",
        caption_style="bold_violet",
        language="en",
        target_duration_s=20,
        tags=("storytelling", "relatable", "pov"),
    ),
    JobTemplate(
        id="three_apps_that",
        name="3 apps that…",
        description=(
            "Fast-paced listicle rounding up three tools around a theme — great "
            "for saves and shares."
        ),
        video_subject="3 apps that make you look more productive than you are",
        prompt_scaffold=(
            "Create a rapid listicle: '3 apps that {subject}'. Give each app a "
            "one-line hook and a concrete reason it earns a spot. Number them "
            "1, 2, 3 and keep energy high throughout."
        ),
        layout="split",
        caption_style="karaoke_green",
        language="en",
        target_duration_s=35,
        tags=("listicle", "roundup", "saves"),
    ),
    JobTemplate(
        id="before_after",
        name="Before/After",
        description=(
            "Transformation format contrasting a painful 'before' with a "
            "delightful 'after' to sell the change."
        ),
        video_subject="how a habit tracker changed my week from chaos to calm",
        prompt_scaffold=(
            "Tell a before/after transformation about {subject}. Spend the "
            "first half on the messy 'before' and the second half on the "
            "'after'. Make the contrast obvious and the turning point clear."
        ),
        layout="split",
        caption_style="karaoke_yellow",
        language="en",
        target_duration_s=25,
        tags=("transformation", "before-after", "results"),
    ),
    JobTemplate(
        id="founder_story",
        name="Founder story",
        description=(
            "Authentic founder-to-camera narrative that builds trust and "
            "explains the 'why' behind the product."
        ),
        video_subject="why I quit my job to build a tool I wished existed",
        prompt_scaffold=(
            "Speak as the founder telling the origin story of {subject}. Lead "
            "with the frustration that started it, share one honest struggle, "
            "and end with the mission. Warm, sincere, first-person."
        ),
        layout="hook_intro",
        caption_style="clean_white",
        language="en",
        target_duration_s=45,
        tags=("founder", "brand", "trust"),
    ),
)

#: Immutable id → :class:`JobTemplate` registry.
TEMPLATES: Mapping[str, JobTemplate] = MappingProxyType(
    {tpl.id: tpl for tpl in _TEMPLATES}
)


def list_templates() -> list[dict]:
    """Return every job template as a plain dict, in catalog order."""
    return [tpl.to_dict() for tpl in _TEMPLATES]


def get_template(template_id: str) -> dict | None:
    """Return a single template dict by id, or ``None`` if unknown.

    Args:
        template_id: The template :attr:`JobTemplate.id`. Whitespace is
            trimmed; lookup is case-insensitive.
    """
    if not template_id or not template_id.strip():
        return None
    key = template_id.strip().lower()
    tpl = TEMPLATES.get(key)
    return tpl.to_dict() if tpl is not None else None


# --------------------------------------------------------------------------- #
# Hook catalog (hook browser)
# --------------------------------------------------------------------------- #
def _normalize_hook_language(language: str) -> str:
    """Map an arbitrary language hint to a supported hook-catalog code."""
    value = (language or "").strip().lower()
    if value.startswith("tr") or value.startswith("turk"):
        return "tr"
    if value.startswith("en") or value.startswith("engl"):
        return "en"
    return value


@lru_cache(maxsize=len(_HOOK_LANGUAGES) + 1)
def _load_hooks_cached(language: str) -> tuple[str, ...]:
    """Load and cache the hook lines for a normalized language code.

    Returns a tuple (hashable → ``lru_cache`` friendly). On any failure an
    empty tuple is returned and a warning is logged; hook loading never raises.
    """
    try:
        import yaml  # guarded: PyYAML is a hard dep of the app but stay defensive
    except Exception as exc:  # noqa: BLE001 - never let a missing dep crash a request
        logger.warning(f"PyYAML unavailable, cannot load hooks: {exc}")
        return ()

    if language not in _HOOK_LANGUAGES:
        logger.warning(f"unsupported hook language {language!r}; returning no hooks")
        return ()

    path = os.path.join(utils.resource_dir("hooks"), f"{language}.yaml")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        raw = data.get("hooks") if isinstance(data, dict) else None
        cleaned = tuple(str(h).strip() for h in (raw or []) if str(h).strip())
        if not cleaned:
            logger.warning(f"no hooks found in {path}")
        return cleaned
    except FileNotFoundError:
        logger.warning(f"hook file not found: {path}")
    except Exception as exc:  # noqa: BLE001 - resource loading must never crash
        logger.warning(f"failed to load hooks from {path}: {exc}")
    return ()


def load_hooks(language: str) -> list[str]:
    """Return the native hook lines for ``language`` from resource/hooks/<lang>.yaml.

    Accepts common variants (``"tr"``, ``"tr-TR"``, ``"turkish"``, ``"en"``,
    ``"en-US"``, ``"english"``). An unknown language yields an empty list.

    Args:
        language: The requested language hint.

    Returns:
        A fresh list of hook strings (empty on any failure).
    """
    normalized = _normalize_hook_language(language)
    return list(_load_hooks_cached(normalized))


def list_hooks() -> dict[str, list[str]]:
    """Return the full hook catalog keyed by language, e.g. ``{"tr": [...], "en": [...]}``.

    Intended for a hook-browser UI. Languages that fail to load appear with an
    empty list rather than being omitted, so the shape is stable.
    """
    return {lang: list(_load_hooks_cached(lang)) for lang in _HOOK_LANGUAGES}


__all__ = [
    "JobTemplate",
    "TEMPLATES",
    "list_templates",
    "get_template",
    "load_hooks",
    "list_hooks",
]
