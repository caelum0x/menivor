"""Public template slugs for seeded templates whose internal slug names a brand.

The internal slugs (``minecraft-reddit-split`` ...) stay as they are: the
shared ``packages/shot-template-schema`` presets, stored channels, template
history and older app builds all reference them. The API shows the neutral
public slug everywhere and accepts either one on input.
"""

from __future__ import annotations

#: internal slug -> public slug
PUBLIC_TEMPLATE_SLUGS: dict[str, str] = {
    "minecraft-reddit-split": "story-gameplay-split",
    "movie-recap": "angle-first-recap",
    "fake-ai-podcast": "two-host-ai-podcast",
}
_INTERNAL_BY_PUBLIC: dict[str, str] = {public: internal for internal, public in PUBLIC_TEMPLATE_SLUGS.items()}


def public_slug(slug: str) -> str:
    """The slug the API shows for ``slug`` (internal or already public)."""
    value = str(slug or "").strip()
    return PUBLIC_TEMPLATE_SLUGS.get(value, value)


def internal_slug(slug: str) -> str:
    """The registry slug for ``slug`` (public or legacy input both work)."""
    value = str(slug or "").strip()
    return _INTERNAL_BY_PUBLIC.get(value, value)


__all__ = ["PUBLIC_TEMPLATE_SLUGS", "internal_slug", "public_slug"]
