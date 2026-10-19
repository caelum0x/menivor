"""Brand-kit import: website URL or Rally share -> the user's brand kit.

Menivor's brand kit is the existing :class:`~app.models.db.models.UserPreset`
("brand kit") row whose opaque ``config`` JSON the reel wizard applies. An
import does NOT add a new table: it writes a ``brand`` object (identity: name,
tagline, description, logo, colours, fonts, voice, audience, offer, website)
into that config, plus the preset-level ``language`` the wizard already
understands when the kit has none yet.

Re-importing the same source (same website host, or the same Rally share token)
replaces the brand block on the kit it created before instead of piling up
duplicates. Every write builds a fresh ``config`` dict (no in-place mutation).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from app.domains.brand.extract import brand_from_html
from app.domains.brand.rally import RallyShareError, fetch_rally_brand

SOURCE_WEBSITE = "website"
SOURCE_RALLY = "rally"
SOURCES = frozenset({SOURCE_WEBSITE, SOURCE_RALLY})
BRAND_CONFIG_KEY = "brand"
#: Preset-level language values the reel wizard accepts.
_WIZARD_LANGUAGES = frozenset({"tr", "en"})
MAX_KIT_NAME = 200


class BrandImportError(Exception):
    """A user-presentable import failure carrying an HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _host_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def extract_from_website(
    raw_url: str,
    *,
    getter: Callable[..., Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Fetch a site's homepage through the SSRF guard and extract its brand.

    Returns ``(source_key, brand)``. A product page URL also works: the page is
    read as-is, which is what the user pasted.
    """
    from app.domains.adstudio.fetch import FetchError, safe_get

    get = getter or safe_get
    try:
        result = get(raw_url, accept_language="en-US,en;q=0.9,tr;q=0.8")
    except FetchError as exc:
        if exc.status_code == 424:
            raise BrandImportError(
                424,
                "the website blocked the automated visit; enter your brand details manually instead",
            ) from exc
        raise BrandImportError(exc.status_code, exc.message) from exc
    content_type = (result.content_type or "").lower()
    if content_type and "html" not in content_type and "xml" not in content_type:
        raise BrandImportError(422, "that URL is not a web page")
    brand = brand_from_html(result.text(), result.url)
    if not brand["name"] and not brand["description"]:
        raise BrandImportError(
            422,
            "could not find a brand name or description on that page; try your homepage",
        )
    return f"{SOURCE_WEBSITE}:{_host_key(result.url)}", brand


def extract_from_rally(
    raw_share: str,
    *,
    getter: Callable[..., Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Resolve a Rally share link/token into ``(source_key, brand)``."""
    try:
        token, brand = fetch_rally_brand(raw_share, getter=getter)
    except RallyShareError as exc:
        raise BrandImportError(exc.status_code, exc.message) from exc
    return f"{SOURCE_RALLY}:{token}", brand


def extract(source: str, value: str, *, getter: Callable[..., Any] | None = None) -> tuple[str, dict[str, Any]]:
    if source == SOURCE_WEBSITE:
        return extract_from_website(value, getter=getter)
    if source == SOURCE_RALLY:
        return extract_from_rally(value, getter=getter)
    raise BrandImportError(422, "source must be 'website' or 'rally'")


def _stamped(brand: dict[str, Any], source: str, source_key: str) -> dict[str, Any]:
    return {
        **brand,
        "source": source,
        "source_key": source_key,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }


def kit_config(
    existing: dict[str, Any] | None,
    brand: dict[str, Any],
    source: str,
    source_key: str,
) -> dict[str, Any]:
    """Return a NEW preset config with the imported brand block applied.

    Existing render knobs (avatar, voice, layout, captions, music) are kept. The
    preset-level ``language`` is only filled when the kit has none, so an import
    never overrides a choice the creator made.
    """
    base = dict(existing or {})
    config = {**base, BRAND_CONFIG_KEY: _stamped(brand, source, source_key)}
    language = str(brand.get("language") or "").lower()
    if not base.get("language") and language in _WIZARD_LANGUAGES:
        config["language"] = language
    return config


def default_kit_name(brand: dict[str, Any], source_key: str) -> str:
    name = str(brand.get("name") or "").strip()
    if not name:
        name = _host_key(str(brand.get("website_url") or "")) or source_key.split(":", 1)[-1]
    return f"{name} brand kit"[:MAX_KIT_NAME]


def find_imported_kit(presets: list[Any], source_key: str) -> Any | None:
    """The caller's kit previously imported from ``source_key``, if any."""
    for preset in presets:
        config = getattr(preset, "config", None) or {}
        block = config.get(BRAND_CONFIG_KEY) if isinstance(config, dict) else None
        if isinstance(block, dict) and block.get("source_key") == source_key:
            return preset
    return None


def save_to_kit(
    session: Any,
    *,
    user_id: str,
    brand: dict[str, Any],
    source: str,
    source_key: str,
    preset_id: str | None = None,
    name: str | None = None,
) -> Any:
    """Write the brand into the user's brand kit (``UserPreset``) and return it.

    * ``preset_id`` given: update that kit (must be owned by the caller, else 404).
    * otherwise: update the kit previously imported from the same source, or
      create a new private kit.
    """
    from app.models.db.repositories import UserPresetRepository

    repo = UserPresetRepository(session)
    if preset_id:
        preset = repo.get(preset_id, user_id)
        if preset is None:
            raise BrandImportError(404, "brand kit not found")
    else:
        preset = find_imported_kit(repo.list_for_user(user_id), source_key)

    kit_name = (name or "").strip()[:MAX_KIT_NAME]
    if preset is None:
        return repo.create(
            user_id,
            kit_name or default_kit_name(brand, source_key),
            kit_config({}, brand, source, source_key),
        )
    preset.config = kit_config(dict(preset.config or {}), brand, source, source_key)
    if kit_name:
        preset.name = kit_name
    session.flush()
    return preset


def latest_brand_for_user(session: Any, user_id: str) -> dict[str, Any] | None:
    """The most recently created kit's brand block, for generation consumers."""
    from app.models.db.repositories import UserPresetRepository

    for preset in UserPresetRepository(session).list_for_user(user_id):
        block = (preset.config or {}).get(BRAND_CONFIG_KEY)
        if isinstance(block, dict):
            return dict(block)
    return None


def preset_view(preset: Any) -> dict[str, Any]:
    created_at = getattr(preset, "created_at", None)
    workspace_id = getattr(preset, "workspace_id", None)
    return {
        "id": preset.id,
        "name": preset.name,
        "config": dict(preset.config or {}),
        "workspace_id": workspace_id,
        "shared": workspace_id is not None,
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


__all__ = [
    "BRAND_CONFIG_KEY",
    "BrandImportError",
    "SOURCES",
    "SOURCE_RALLY",
    "SOURCE_WEBSITE",
    "default_kit_name",
    "extract",
    "extract_from_rally",
    "extract_from_website",
    "find_imported_kit",
    "kit_config",
    "latest_brand_for_user",
    "preset_view",
    "save_to_kit",
]
