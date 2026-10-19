"""Store-listing fetchers: App Store (iTunes Lookup API) and Google Play.

* App Store uses Apple's public, keyless iTunes Lookup API
  (``https://itunes.apple.com/lookup?id=<id>&country=<cc>``), which returns the
  title, developer, description, icon, screenshots and rating as JSON.
* Google Play has no public API, so the public listing page is fetched once
  and read from its Open Graph tags, meta description, ``play-lh`` image URLs
  and the "Rated N stars" label. Play changes its markup from time to time;
  every field is optional and the slideshow degrades to whatever was found.

All HTTP goes through the Ad Studio SSRF guard (:func:`safe_get`). Parsers are
pure so they are unit-tested against fixtures.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any, Callable
from urllib.parse import quote

from app.domains.adstudio.fetch import IMAGE_MAX_BYTES, FetchError, safe_get

MAX_SCREENSHOTS = 8
MAX_DESCRIPTION = 4000
ITUNES_LOOKUP = "https://itunes.apple.com/lookup?id={app_id}&country={country}&entity=software"
ITUNES_SEARCH = "https://itunes.apple.com/search?term={term}&country={country}&entity=software&limit={limit}"
PLAY_DETAILS = "https://play.google.com/store/apps/details?id={package}&hl={hl}&gl={gl}"
_ENGLISH = "en-US,en;q=0.9"
MAX_SEARCH_LIMIT = 50

Getter = Callable[..., Any]


class StoreError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _clean(text: Any, limit: int = 300) -> str:
    value = html.unescape(str(text or "")).replace("\r", "")
    value = re.sub(r"[ \t]+", " ", value).strip()
    return value[:limit]


def parse_itunes(payload: dict[str, Any], url: str = "") -> dict[str, Any]:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not results:
        raise StoreError(404, "the App Store has no app with that id in this country")
    app = next((r for r in results if isinstance(r, dict) and r.get("kind") in ("software", "mac-software")), results[0])
    shots = [s for s in (app.get("screenshotUrls") or []) if isinstance(s, str)]
    if not shots:
        shots = [s for s in (app.get("ipadScreenshotUrls") or []) if isinstance(s, str)]
    rating = app.get("averageUserRating")
    count = app.get("userRatingCount")
    return {
        "store": "app_store",
        "url": str(app.get("trackViewUrl") or url),
        "title": _clean(app.get("trackName"), 200),
        "developer": _clean(app.get("sellerName") or app.get("artistName"), 120),
        "description": _clean(app.get("description"), MAX_DESCRIPTION),
        "icon_url": str(app.get("artworkUrl512") or app.get("artworkUrl100") or ""),
        "screenshots": shots[:MAX_SCREENSHOTS],
        "rating": round(float(rating), 1) if isinstance(rating, (int, float)) and rating > 0 else None,
        "rating_count": int(count) if isinstance(count, int) and count > 0 else None,
        "price_label": _clean(app.get("formattedPrice"), 20),
        "genre": _clean(app.get("primaryGenreName"), 60),
        # Public-data extras consumed by the App Store audit (app/domains/appaudit):
        # the Lookup API has no "subtitle" field, so that is left to the caller to
        # mark honestly as unavailable rather than guessed from the title.
        "version": _clean(app.get("version"), 40),
        "current_version_release_date": str(app.get("currentVersionReleaseDate") or "") or None,
    }


_META = re.compile(r"<meta\s+[^>]*?(?:property|name|itemprop)=\"([^\"]+)\"[^>]*?content=\"([^\"]*)\"", re.I)
_META_REV = re.compile(r"<meta\s+[^>]*?content=\"([^\"]*)\"[^>]*?(?:property|name|itemprop)=\"([^\"]+)\"", re.I)
_PLAY_IMG = re.compile(r"https://play-lh\.googleusercontent\.com/[A-Za-z0-9_\-]+(?:=[A-Za-z0-9\-]+)?")
_RATING = re.compile(r"Rated\s+([0-5](?:\.\d)?)\s+stars?\s+out\s+of\s+five", re.I)
_DEVELOPER = re.compile(r"href=\"/store/apps/dev(?:eloper)?\?id=[^\"]+\"[^>]*>(?:<[^>]+>)*([^<]{1,120})<", re.I)


def _metas(page: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for key, value in _META.findall(page):
        found.setdefault(key.lower(), value)
    for value, key in _META_REV.findall(page):
        found.setdefault(key.lower(), value)
    return found


def _is_small(size: str) -> bool:
    """Icons/avatars are rendered tiny (``s64``, ``w48-h48``); screenshots are not."""
    match = re.match(r"^[sw](\d+)", size or "")
    return bool(match) and int(match.group(1)) < 200


def _play_base(img_url: str) -> str:
    return img_url.split("=", 1)[0]


def parse_play(page: str, url: str = "") -> dict[str, Any]:
    metas = _metas(page)
    title = _clean(metas.get("og:title") or metas.get("name"), 200)
    title = re.sub(r"\s*-\s*Apps on Google Play\s*$", "", title, flags=re.I)
    if not title:
        raise StoreError(404, "could not read that Google Play listing (the app may be unavailable in this country)")
    icon = metas.get("og:image", "")
    icon_base = _play_base(icon) if icon else ""
    seen: set[str] = {icon_base} if icon_base else set()
    shots: list[str] = []
    for match in _PLAY_IMG.findall(page):
        base = _play_base(match)
        size = match.split("=", 1)[1] if "=" in match else ""
        if base in seen or _is_small(size):
            continue
        seen.add(base)
        shots.append(f"{base}=w1080")
        if len(shots) >= MAX_SCREENSHOTS:
            break
    rating_match = _RATING.search(page)
    dev_match = _DEVELOPER.search(page)
    return {
        "store": "play_store",
        "url": url,
        "title": title,
        "developer": _clean(dev_match.group(1), 120) if dev_match else "",
        "description": _clean(metas.get("description") or metas.get("og:description"), MAX_DESCRIPTION),
        "icon_url": f"{icon_base}=s512" if icon_base else "",
        "screenshots": shots,
        "rating": float(rating_match.group(1)) if rating_match else None,
        "rating_count": None,
        "price_label": "",
        "genre": "",
    }


def _fetch_error(exc: FetchError) -> StoreError:
    return StoreError(exc.status_code, exc.message)


def fetch_app_store(ref: dict[str, str], *, getter: Getter = safe_get) -> dict[str, Any]:
    url = ITUNES_LOOKUP.format(app_id=quote(ref["app_id"]), country=quote(ref.get("country") or "us"))
    try:
        result = getter(url, accept="application/json", accept_language=_ENGLISH)
    except FetchError as exc:
        raise _fetch_error(exc) from exc
    try:
        payload = json.loads(result.text())
    except ValueError as exc:
        raise StoreError(502, "the App Store lookup returned an unreadable response") from exc
    return parse_itunes(payload)


def parse_itunes_search(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse the iTunes Search API's ``results`` array into ``(app_id, title, developer)`` rows."""
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    rows: list[dict[str, Any]] = []
    for entry in results:
        if not isinstance(entry, dict):
            continue
        app_id = entry.get("trackId")
        title = _clean(entry.get("trackName"), 200)
        if not app_id or not title:
            continue
        rows.append({
            "app_id": str(app_id),
            "title": title,
            "developer": _clean(entry.get("sellerName") or entry.get("artistName"), 120),
        })
    return rows


def fetch_app_store_search(term: str, *, country: str = "us", limit: int = MAX_SEARCH_LIMIT,
                           getter: Getter = safe_get) -> list[dict[str, Any]]:
    """Top ``limit`` App Store results for ``term`` via the public, keyless iTunes Search API."""
    url = ITUNES_SEARCH.format(
        term=quote(term.strip()), country=quote(country or "us"), limit=max(1, min(int(limit), MAX_SEARCH_LIMIT)),
    )
    try:
        result = getter(url, accept="application/json", accept_language=_ENGLISH)
    except FetchError as exc:
        raise _fetch_error(exc) from exc
    try:
        payload = json.loads(result.text())
    except ValueError as exc:
        raise StoreError(502, "the App Store search returned an unreadable response") from exc
    return parse_itunes_search(payload)


def fetch_play_store(ref: dict[str, str], *, getter: Getter = safe_get) -> dict[str, Any]:
    url = PLAY_DETAILS.format(package=quote(ref["package"]), hl=quote(ref.get("hl") or "en"), gl=quote(ref.get("gl") or "US"))
    try:
        result = getter(url, accept_language=_ENGLISH)
    except FetchError as exc:
        raise _fetch_error(exc) from exc
    return parse_play(result.text(), url=f"https://play.google.com/store/apps/details?id={ref['package']}")


def download_image(url: str, dest_path: str, *, getter: Getter = safe_get) -> str | None:
    """Download one listing image and re-encode it to JPEG. Returns the path or None."""
    try:
        result = getter(url, max_bytes=IMAGE_MAX_BYTES, accept="image/avif,image/webp,image/png,image/jpeg,*/*;q=0.5")
    except FetchError:
        return None
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(result.body)) as img:
            img.load()
            if img.width < 64 or img.height < 64:
                return None
            rgb = img.convert("RGB")
            rgb.save(dest_path, "JPEG", quality=92)
        return dest_path
    except Exception:  # noqa: BLE001 - one bad image never fails the capture
        return None


__all__ = [
    "StoreError",
    "download_image",
    "fetch_app_store",
    "fetch_app_store_search",
    "fetch_play_store",
    "parse_itunes",
    "parse_itunes_search",
    "parse_play",
]
