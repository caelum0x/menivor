"""Seeded system shot-template registry.

Each module under this package exposes a ``TEMPLATE: ShotTemplateDef``. This
loader collects them into an ordered, slug-keyed mapping — the single source of
truth for the system templates the API serves (mirrors how
``app.domains.catalog.presets`` exposes the camera/VFX catalog). Custom user
templates (DB-backed) are a later phase that reuses the same ``ShotTemplateDef``.
"""

from __future__ import annotations

from ..definitions import ShotTemplateDef
from . import (
    anime_beat_edit,
    asmr_loop,
    before_after,
    brainrot_meme,
    countdown_ranking,
    day_in_the_life,
    faceless_facts,
    fake_podcast,
    gameplay_story,
    greenscreen_react,
    grwm_routine,
    listicle,
    meme_explainer,
    minecraft_reddit_split,
    movie_recap,
    news_brief,
    platform_hook_open,
    product_demo_ad,
    quiz_engagement,
    quote_motivation,
    recipe_quick,
    story_time,
    street_interview,
    talking_head_explainer,
    testimonial_ad,
    tutorial_howto,
)

# Order = curated display order in the template gallery.
_MODULES = (
    product_demo_ad,
    testimonial_ad,
    before_after,
    talking_head_explainer,
    faceless_facts,
    listicle,
    tutorial_howto,
    news_brief,
    story_time,
    quote_motivation,
    countdown_ranking,
    recipe_quick,
    grwm_routine,
    day_in_the_life,
    street_interview,
    meme_explainer,
    greenscreen_react,
    minecraft_reddit_split,
    quiz_engagement,
    gameplay_story,
    movie_recap,
    fake_podcast,
    asmr_loop,
    anime_beat_edit,
    brainrot_meme,
    platform_hook_open,
)

SYSTEM_TEMPLATES: tuple[ShotTemplateDef, ...] = tuple(m.TEMPLATE for m in _MODULES)

_BY_SLUG: dict[str, ShotTemplateDef] = {t.slug: t for t in SYSTEM_TEMPLATES}

# Fail fast on a duplicate slug (would silently shadow in the mapping).
if len(_BY_SLUG) != len(SYSTEM_TEMPLATES):  # pragma: no cover - authoring guard
    raise RuntimeError("duplicate shot-template slug in the seeded registry")


# ---------------------------------------------------------------------------
# Shared-schema reconciliation.
#
# The frontends render the ``/blueprints`` picker from the shared
# ``@reelforge/shot-template-schema`` package (Python port ``reelforge_shot_template``),
# NOT from this registry. To stop those two lists silently diverging — the picker
# advertising a genre the backend can't instantiate, or a blueprint whose slot
# timeline no longer matches what the renderer composes — we project every seeded
# ``ShotTemplateDef`` onto the schema's ``ShotTemplate`` shape at registry load and
# assert it is byte-identical (same slugs + same ``content_hash``) to the schema
# preset. A drift is an authoring bug and fails fast here, exactly like the
# duplicate-slug guard above. A stripped deploy that ships only ``apps/api``
# (no ``packages/``) simply skips the check — it can never break startup.
# ---------------------------------------------------------------------------


def _load_shot_template_schema():
    """Import ``reelforge_shot_template`` (adding the monorepo path if needed).

    Mirrors ``app.services.captions._engine`` / ``services.compose.vfx``: the
    shared package is a monorepo path dependency, not pip-installed. Returns the
    module, or ``None`` when the package is not shipped alongside this API.
    """
    try:  # Installed / already importable.
        import reelforge_shot_template as schema  # type: ignore

        return schema
    except ModuleNotFoundError:
        pass

    import sys as _sys
    from pathlib import Path as _Path

    # This file is apps/api/app/domains/templates/presets/__init__.py, so
    # parents[6] is the repo root and the package source lives under
    # packages/shot-template-schema/python.
    pkg_root = _Path(__file__).resolve().parents[6] / "packages" / "shot-template-schema" / "python"
    if not pkg_root.is_dir():
        return None
    path_str = str(pkg_root)
    if path_str not in _sys.path:
        _sys.path.insert(0, path_str)
    try:
        import reelforge_shot_template as schema  # type: ignore

        return schema
    except ModuleNotFoundError:
        return None


def _project_to_schema(schema, template: ShotTemplateDef) -> dict:
    """Project a seeded ``ShotTemplateDef`` onto the schema ``ShotTemplate`` shape.

    The blueprint is the template's slug/genre/aspect plus its slot role-sequence,
    with each slot's fractional timing expanded against ``default_duration_s`` into
    the integer-ms slots the schema pins. This is the single conversion rule the
    hand-authored schema presets mirror; ``presets.ts`` / ``presets.py`` MUST stay
    equal to it (regenerate them when a template changes).
    """
    dur_s = template.default_duration_s
    slots = [
        schema.make_slot(
            s.role,
            int(round(s.t_start_frac * dur_s * 1000)),
            int(round(s.t_end_frac * dur_s * 1000)),
            caption_preset=template.caption_style,
            transition_out=s.transition_out,
        )
        for s in sorted(template.slots, key=lambda x: x.order)
    ]
    return schema.make_template(template.slug, template.genre, template.aspect, slots)


def _reconcile_with_schema() -> None:
    """Assert the shared-schema blueprint list matches this seeded registry.

    Raises ``RuntimeError`` on any drift (missing slug, extra slug, or a blueprint
    whose projected ``content_hash`` differs). No-op when the shared package is not
    importable (stripped deploy).
    """
    schema = _load_shot_template_schema()
    if schema is None:  # Shared package not shipped with this API — skip.
        return

    schema_slugs = set(schema.list_presets())
    backend_slugs = set(_BY_SLUG)
    if schema_slugs != backend_slugs:
        missing = backend_slugs - schema_slugs
        extra = schema_slugs - backend_slugs
        raise RuntimeError(
            "shot-template drift: shared schema presets and seeded templates differ "
            f"(seeded-only={sorted(missing)}, schema-only={sorted(extra)}); "
            "regenerate packages/shot-template-schema presets from the backend registry"
        )
    for slug, template in _BY_SLUG.items():
        projected = _project_to_schema(schema, template)
        want = schema.get_preset(slug)
        if schema.content_hash(projected) != schema.content_hash(want):
            raise RuntimeError(
                f"shot-template drift: seeded {slug!r} blueprint no longer matches the "
                "shared schema preset; regenerate packages/shot-template-schema presets "
                "(slug/genre/aspect/slot role-sequence + ms timings must agree)"
            )


_reconcile_with_schema()


def all_templates() -> tuple[ShotTemplateDef, ...]:
    return SYSTEM_TEMPLATES


def get_template(slug: str) -> ShotTemplateDef | None:
    """A seeded template by internal slug, public slug (see ``aliases``) or legacy slug."""
    from .aliases import internal_slug

    return _BY_SLUG.get(internal_slug(slug))
