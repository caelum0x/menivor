"""Classify a capture URL into a source kind and extract store identifiers.

Pure functions, no network. ``classify`` accepts the user's requested kind
(``auto`` or one of :data:`SOURCE_KINDS`) and returns the resolved kind plus
the store reference needed by :mod:`app.domains.capture.store`.

* App Store: ``https://apps.apple.com/<cc>/app/<slug>/id<digits>`` (also the
  legacy ``itunes.apple.com`` host). The country code in the path is kept so
  the lookup returns the same storefront the user pasted.
* Google Play: ``https://play.google.com/store/apps/details?id=<package>``;
  ``hl``/``gl`` query params are kept when present.
* Anything else is a website. Games are captured natively from a simulator
  (``native_game``, see :mod:`app.domains.capture.native`), never from a URL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from app.domains.capture.models import (
    KIND_APP_STORE,
    KIND_NATIVE_GAME,
    KIND_PLAY_STORE,
    KIND_WEBSITE,
    LEGACY_KINDS,
    SOURCE_KINDS,
)

KIND_AUTO = "auto"
_APPLE_HOSTS = frozenset({"apps.apple.com", "itunes.apple.com"})
_PLAY_HOSTS = frozenset({"play.google.com"})
_APPLE_ID = re.compile(r"/id(\d{5,12})(?:[/?#]|$)")
_COUNTRY = re.compile(r"^[a-z]{2}$")
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
_LANG = re.compile(r"^[a-z]{2}(?:[-_][A-Za-z]{2})?$")


class SourceError(ValueError):
    """A user-presentable URL/kind problem (HTTP 422)."""


@dataclass(frozen=True)
class Source:
    kind: str
    url: str
    ref: dict[str, str] = field(default_factory=dict)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def apple_ref(url: str) -> dict[str, str] | None:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in _APPLE_HOSTS:
        return None
    match = _APPLE_ID.search(parsed.path + "/")
    if not match:
        return None
    first = parsed.path.strip("/").split("/", 1)[0].lower()
    country = first if _COUNTRY.match(first) else "us"
    return {"app_id": match.group(1), "country": country}


def play_ref(url: str) -> dict[str, str] | None:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in _PLAY_HOSTS:
        return None
    if not parsed.path.rstrip("/").endswith("/store/apps/details"):
        return None
    query = parse_qs(parsed.query)
    package = (query.get("id") or [""])[0].strip()
    if not package or len(package) > 150 or not _PACKAGE.match(package):
        return None
    hl = (query.get("hl") or ["en"])[0].strip() or "en"
    gl = (query.get("gl") or ["US"])[0].strip() or "US"
    return {
        "package": package,
        "hl": hl if _LANG.match(hl) else "en",
        "gl": gl.upper() if _COUNTRY.match(gl.lower()) else "US",
    }


def detect_kind(url: str) -> str:
    """Best guess without user input: store listings are unambiguous."""
    host = _host(url)
    if host in _APPLE_HOSTS:
        return KIND_APP_STORE
    if host in _PLAY_HOSTS:
        return KIND_PLAY_STORE
    return KIND_WEBSITE


def classify(url: str, requested_kind: str = KIND_AUTO) -> Source:
    """Resolve ``requested_kind`` against ``url`` (already normalized)."""
    kind = (requested_kind or KIND_AUTO).strip().lower()
    if kind in LEGACY_KINDS:
        raise SourceError("web game capture was removed; record the native game from a simulator instead")
    if kind == KIND_NATIVE_GAME:
        raise SourceError("native games are recorded from a simulator or emulator, not from a link")
    if kind != KIND_AUTO and kind not in SOURCE_KINDS:
        raise SourceError(f"unknown capture type {requested_kind!r}")
    detected = detect_kind(url)
    if kind == KIND_AUTO:
        kind = detected
    if kind == KIND_APP_STORE:
        ref = apple_ref(url)
        if ref is None:
            raise SourceError("that is not an App Store app link (expected apps.apple.com/.../id123456789)")
        return Source(kind, url, ref)
    if kind == KIND_PLAY_STORE:
        ref = play_ref(url)
        if ref is None:
            raise SourceError("that is not a Google Play app link (expected play.google.com/store/apps/details?id=...)")
        return Source(kind, url, ref)
    if detected in (KIND_APP_STORE, KIND_PLAY_STORE):
        # A store page recorded as a "website" would only capture the store UI.
        raise SourceError("store links are captured as store listings; pick App Store or Google Play")
    return Source(KIND_WEBSITE, url, {})


__all__ = ["KIND_AUTO", "Source", "SourceError", "apple_ref", "classify", "detect_kind", "play_ref"]
