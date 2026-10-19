"""Menivor ad packs: parse, validate and turn into exact API request bodies.

An ad pack (``gtm/menivor-ads/<product>.json``, schema ``menivor-ad-pack/v1``)
describes how Menivor should advertise one of our own products:

* ``captures``  - what to record: a website, an App Store / Google Play
  listing, or a native game on a simulator (games are native only; web game
  capture was removed). Each entry becomes one ``POST /api/v1/capture`` body.
* ``product``   - the Ad Studio ``ManualProduct`` (title, description, bullets)
  so the project is created from reviewed facts instead of a scrape.
* ``concepts``  - exactly 5 ad concepts. Each one is an Ad Studio angle
  (``kind`` / ``hook`` / ``pain`` / ``proof`` / ``offer`` / ``cta``) plus the
  capture-ad settings (free format, target platform, aspect, script).
* ``facts``     - the grounded claims the copy may use, each with the file or
  URL it came from. Every number in the copy must appear in a fact.

This module is pure (no network, no app imports) so the pack files can be
checked anywhere. The limits below mirror the API; ``tests/reelforge/
test_seed_ad_packs.py`` fails if they drift from the app's own constants and
validates the generated bodies against the real pydantic request models.

Nothing built here publishes: every ``POST /capture/{id}/ads`` body has
``platforms: []`` (a non-empty list would auto-publish the rendered reel), and
the Ad Studio project is created without variants.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA = "menivor-ad-pack/v1"
PROJECT_TITLE_PREFIX = "Menivor ad pack: "

# --- mirrors of the API's own limits (drift-checked in tests) --------------- #
#: app.domains.adstudio.angles.ANGLE_KINDS
ANGLE_KINDS: tuple[str, ...] = ("problem_solution", "social_proof", "offer", "demo", "before_after")
#: app.domains.adstudio.angles.FIELD_MAX
ANGLE_FIELD_MAX = 220
#: app.domains.adstudio.variants.FORMATS minus ugc_avatar (paid avatar provider)
STUDIO_FORMATS: tuple[str, ...] = ("showcase", "before_after")
#: app.domains.capture.service.FORMATS
ASPECTS: tuple[str, ...] = ("9:16", "16:9", "1:1")
#: app.domains.capture.models.SOURCE_KINDS
CAPTURE_KINDS: tuple[str, ...] = ("website", "app_store", "play_store", "native_game")
#: app.domains.capture.service.DURATION_LIMITS (store listings take no duration)
DURATION_LIMITS: dict[str, tuple[int, int]] = {"website": (10, 45), "native_game": (10, 60)}
#: app.domains.capture.ads.FREE_VOICES
FREE_VOICES: tuple[str, ...] = ("en-US-AriaNeural-Female", "en-US-GuyNeural-Male", "tr-TR-EmelNeural-Female")
#: app.domains.capture.ads.MAX_SCRIPT_CHARS
MAX_SCRIPT_CHARS = 1200
#: app.controllers.v1.social._SUPPORTED_PLATFORMS
PLATFORMS: tuple[str, ...] = ("tiktok", "instagram", "youtube_shorts")
#: capture AdsBody.language
LANGUAGES: tuple[str, ...] = ("en", "tr")
#: native target limits (app.domains.capture.native)
NATIVE_PLATFORMS: tuple[str, ...] = ("ios", "android")
SETTLE_MAX_S = 30

#: Free ad formats (ids from app.core.launch.formats) -> capture ad mode.
FREE_FORMATS: dict[str, str] = {"captions_only": "captions", "faceless_free_voice": "voiceover"}

CONCEPT_COUNT = 5
MANUAL_LIMITS = {"title": 200, "brand": 80, "description": 2000}
MAX_BULLETS = 8
MAX_CAPTURES = 3

_APP_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)+$")
_DEVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_DEEP_LINK = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]{0,31}://[A-Za-z0-9._~:/?#@!$&*+,;=%\[\]-]{0,480}$")
_APPLE_ID = re.compile(r"/id(\d{5,12})(?:[/?#]|$)")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

# --- honesty lint ----------------------------------------------------------- #
#: Claims we cannot make: we have no testimonials, ratings, rankings or user counts.
BANNED_PHRASES: tuple[str, ...] = (
    "testimonial", "loved by", "trusted by", "users love", "customers love", "thousands of",
    "millions of", "#1", "number one", "best-selling", "bestselling", "five-star", "5-star",
    "award-winning", "guaranteed", "rated", "top-rated", "join thousands", "everyone is using",
    "binlerce", "milyonlarca", "bir numara", "en çok tercih edilen", "garantili",
)
_STORE_CLAIMS = {
    "app_store": re.compile(r"\b(on|in|from) the app store\b|\bapp store'dan\b", re.IGNORECASE),
    "play_store": re.compile(r"\b(on|in|from) google play\b|\bgoogle play'den\b", re.IGNORECASE),
}
_DOWNLOAD_NOW = re.compile(r"\b(download|install) (it )?(now|today)\b|\bhemen indir\b", re.IGNORECASE)
_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0xFE00, 0xFE0F), (0x1F1E6, 0x1F1FF))


class PackError(ValueError):
    """A pack that Menivor would reject, or copy that breaks the honesty rules."""


@dataclass(frozen=True)
class AdPack:
    path: Path
    data: dict[str, Any]

    @property
    def product_id(self) -> str:
        return str(self.data["product_id"])

    @property
    def project_title(self) -> str:
        return PROJECT_TITLE_PREFIX + str(self.data["product_name"])


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _has_emoji(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if any(lo <= code <= hi for lo, hi in _EMOJI_RANGES) or unicodedata.category(ch) == "So":
            return True
    return False


def _numbers(text: str) -> set[str]:
    return {token.replace(",", ".") for token in _NUMBER.findall(text or "")}


def _req_str(obj: dict[str, Any], key: str, where: str, *, max_len: int | None = None, allow_empty: bool = False) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise PackError(f"{where}.{key} must be a string")
    value = value.strip()
    if not value and not allow_empty:
        raise PackError(f"{where}.{key} is required")
    if max_len is not None and len(value) > max_len:
        raise PackError(f"{where}.{key} is longer than {max_len} characters")
    return value


def _check_public_url(url: str, where: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise PackError(f"{where} must be a public http(s) URL")
    return url


def _is_store_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("apps.apple.com", "itunes.apple.com", "play.google.com")


# --------------------------------------------------------------------------- #
# section validators
# --------------------------------------------------------------------------- #
def _validate_capture(raw: Any, index: int) -> None:
    where = f"captures[{index}]"
    if not isinstance(raw, dict):
        raise PackError(f"{where} must be an object")
    allowed = {"kind", "url", "native", "formats", "duration_s", "cursor", "note"}
    extra = set(raw) - allowed
    if extra:
        raise PackError(f"{where} has unknown field(s): {', '.join(sorted(extra))}")
    kind = raw.get("kind")
    if kind == "web_game":
        raise PackError(f"{where}: web game capture was removed; games are captured natively from a simulator")
    if kind not in CAPTURE_KINDS:
        raise PackError(f"{where}.kind must be one of {', '.join(CAPTURE_KINDS)}")
    formats = raw.get("formats")
    if not isinstance(formats, list) or not 1 <= len(formats) <= 3 or len(set(formats)) != len(formats):
        raise PackError(f"{where}.formats must list 1-3 distinct aspects")
    bad = [f for f in formats if f not in ASPECTS]
    if bad:
        raise PackError(f"{where}.formats has unsupported aspect(s): {', '.join(map(str, bad))}")
    duration = raw.get("duration_s")
    if kind in DURATION_LIMITS:
        low, high = DURATION_LIMITS[kind]
        if duration is not None and not (isinstance(duration, int) and low <= duration <= high):
            raise PackError(f"{where}.duration_s must be {low}-{high} seconds for {kind}")
    elif duration is not None:
        raise PackError(f"{where}.duration_s is not used for store listings; leave it null")
    if kind == "native_game":
        if raw.get("url"):
            raise PackError(f"{where}: native games are recorded from a simulator, not a URL")
        _validate_native(raw.get("native"), where)
        return
    if raw.get("native") is not None:
        raise PackError(f"{where}.native is only for native_game captures")
    url = _check_public_url(_req_str(raw, "url", where, max_len=2048), f"{where}.url")
    parsed = urlparse(url)
    if kind == "app_store":
        if parsed.hostname not in ("apps.apple.com", "itunes.apple.com") or not _APPLE_ID.search(parsed.path + "/"):
            raise PackError(f"{where}.url is not an App Store app link (apps.apple.com/.../id123456789)")
    elif kind == "play_store":
        if parsed.hostname != "play.google.com" or "id=" not in parsed.query:
            raise PackError(f"{where}.url is not a Google Play app link")
    elif _is_store_host(url):
        raise PackError(f"{where}: store links must use kind app_store or play_store")


def _validate_native(raw: Any, where: str) -> None:
    if not isinstance(raw, dict):
        raise PackError(f"{where}.native is required for native_game captures")
    allowed = {"platform", "device", "app_id", "deep_link", "title", "settle_s"}
    extra = set(raw) - allowed
    if extra:
        raise PackError(f"{where}.native has unknown field(s): {', '.join(sorted(extra))}")
    if raw.get("platform") not in NATIVE_PLATFORMS:
        raise PackError(f"{where}.native.platform must be ios or android")
    device = str(raw.get("device") or "")
    if raw["platform"] == "android" and not device:
        raise PackError(f"{where}.native.device (adb serial) is required on android")
    if device and not _DEVICE.match(device):
        raise PackError(f"{where}.native.device is not a simulator UDID, 'booted' or adb serial")
    app_id = str(raw.get("app_id") or "")
    if not app_id or len(app_id) > 150 or not _APP_ID.match(app_id):
        raise PackError(f"{where}.native.app_id must be the game's bundle id / package name")
    link = str(raw.get("deep_link") or "")
    if link and not _DEEP_LINK.match(link):
        raise PackError(f"{where}.native.deep_link must look like mygame://play?menivor_demo=1")
    if len(str(raw.get("title") or "")) > 80:
        raise PackError(f"{where}.native.title is longer than 80 characters")
    settle = raw.get("settle_s", 4)
    if not isinstance(settle, int) or not 0 <= settle <= SETTLE_MAX_S:
        raise PackError(f"{where}.native.settle_s must be 0-{SETTLE_MAX_S}")


def _validate_product(raw: Any, language: str) -> None:
    if not isinstance(raw, dict):
        raise PackError("product must be an object")
    allowed = {"title", "brand", "description", "bullets", "images", "language"}
    extra = set(raw) - allowed
    if extra:
        raise PackError(f"product has unknown or unsupported field(s): {', '.join(sorted(extra))}")
    for key, limit in MANUAL_LIMITS.items():
        _req_str(raw, key, "product", max_len=limit, allow_empty=key == "brand")
    bullets = raw.get("bullets", [])
    if not isinstance(bullets, list) or len(bullets) > MAX_BULLETS or not all(isinstance(b, str) and b.strip() for b in bullets):
        raise PackError(f"product.bullets must be up to {MAX_BULLETS} non-empty strings")
    images = raw.get("images", [])
    if not isinstance(images, list) or len(images) > 10:
        raise PackError("product.images must be a list of up to 10 public image URLs")
    for i, img in enumerate(images):
        _check_public_url(str(img), f"product.images[{i}]")
    if raw.get("language", language) != language:
        raise PackError("product.language must match the pack language")


def _validate_concept(raw: Any, index: int, language: str, aspects: set[str]) -> None:
    where = f"concepts[{index}]"
    if not isinstance(raw, dict):
        raise PackError(f"{where} must be an object")
    required = ("id", "angle_kind", "angle_note", "hook", "pain", "proof", "offer", "cta",
                "format", "platform", "aspect", "script", "studio_format")
    allowed = set(required) | {"voice_name"}
    missing = [k for k in required if k not in raw]
    if missing:
        raise PackError(f"{where} is missing: {', '.join(missing)}")
    extra = set(raw) - allowed
    if extra:
        raise PackError(f"{where} has unknown field(s): {', '.join(sorted(extra))}")
    if raw["angle_kind"] not in ANGLE_KINDS:
        raise PackError(f"{where}.angle_kind must be one of {', '.join(ANGLE_KINDS)}")
    if raw["angle_kind"] == "social_proof":
        raise PackError(f"{where}: social_proof needs real reviews or users; none are verified yet")
    _req_str(raw, "hook", where, max_len=ANGLE_FIELD_MAX)
    _req_str(raw, "cta", where, max_len=ANGLE_FIELD_MAX)
    for key in ("pain", "proof", "offer"):
        _req_str(raw, key, where, max_len=ANGLE_FIELD_MAX, allow_empty=True)
    _req_str(raw, "angle_note", where, max_len=400)
    script = _req_str(raw, "script", where, max_len=MAX_SCRIPT_CHARS)
    if raw["hook"].strip() not in script:
        raise PackError(f"{where}.script must open with (contain) the hook")
    if raw["format"] not in FREE_FORMATS:
        raise PackError(f"{where}.format must be a free format: {', '.join(FREE_FORMATS)}")
    voice = raw.get("voice_name", "")
    if raw["format"] == "faceless_free_voice":
        if voice not in FREE_VOICES:
            raise PackError(f"{where}.voice_name must be one of {', '.join(FREE_VOICES)}")
        if not voice.startswith(("tr-" if language == "tr" else "en-")):
            raise PackError(f"{where}.voice_name does not match the pack language")
    elif voice:
        raise PackError(f"{where}.voice_name is only used by faceless_free_voice")
    if raw["platform"] not in PLATFORMS:
        raise PackError(f"{where}.platform must be one of {', '.join(PLATFORMS)}")
    if raw["aspect"] not in ASPECTS:
        raise PackError(f"{where}.aspect must be one of {', '.join(ASPECTS)}")
    if raw["aspect"] not in aspects:
        raise PackError(f"{where}.aspect {raw['aspect']} is not recorded by any capture")
    if raw["studio_format"] not in STUDIO_FORMATS:
        raise PackError(f"{where}.studio_format must be one of {', '.join(STUDIO_FORMATS)} (free local renders)")


def _copy_fields(data: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    product = data.get("product") or {}
    for key in ("title", "description"):
        out.append((f"product.{key}", str(product.get(key) or "")))
    out += [(f"product.bullets[{i}]", str(b)) for i, b in enumerate(product.get("bullets") or [])]
    for i, concept in enumerate(data.get("concepts") or []):
        for key in ("hook", "pain", "proof", "offer", "cta", "script"):
            out.append((f"concepts[{i}].{key}", str(concept.get(key) or "")))
    return out


def lint_honesty(data: dict[str, Any]) -> None:
    """Reject copy with emoji, ungrounded numbers, invented social proof or false store claims."""
    facts = data.get("facts") or []
    grounded: set[str] = set()
    for fact in facts:
        grounded |= _numbers(str(fact.get("claim") or ""))
    availability = data.get("availability") or {}
    for where, text in _copy_fields(data):
        if _has_emoji(text):
            raise PackError(f"{where} contains an emoji")
        lowered = text.lower()
        for phrase in BANNED_PHRASES:
            if re.search(r"(?<!\w)" + re.escape(phrase.strip()) + r"(?!\w)", lowered):
                raise PackError(f"{where} uses {phrase!r}: we have no verified reviews, ratings or user counts")
        loose = _numbers(text) - grounded
        if loose:
            raise PackError(f"{where} uses number(s) {', '.join(sorted(loose))} that no fact supports")
        for store, pattern in _STORE_CLAIMS.items():
            if not availability.get(store) and pattern.search(text):
                raise PackError(f"{where} points to {store} but the product has no live {store} listing")
        if not (availability.get("app_store") or availability.get("play_store")) and _DOWNLOAD_NOW.search(text):
            raise PackError(f"{where} says download now but there is no live store listing")


def validate(data: Any) -> None:
    """Raise :class:`PackError` unless ``data`` is a complete, honest v1 pack."""
    if not isinstance(data, dict):
        raise PackError("a pack must be a JSON object")
    if data.get("schema") != SCHEMA:
        raise PackError(f"schema must be {SCHEMA!r}")
    product_id = str(data.get("product_id") or "")
    if not _ID.match(product_id):
        raise PackError("product_id must be a lowercase slug (the PORTFOLIO.json id)")
    name = _req_str(data, "product_name", "pack", max_len=200 - len(PROJECT_TITLE_PREFIX))
    if _has_emoji(name):
        raise PackError("product_name contains an emoji")
    language = data.get("language")
    if language not in LANGUAGES:
        raise PackError(f"language must be one of {', '.join(LANGUAGES)}")
    availability = data.get("availability")
    if not isinstance(availability, dict) or set(availability) != {"web", "app_store", "play_store"}:
        raise PackError("availability must have web, app_store and play_store (URL or null)")
    for key, value in availability.items():
        if value is not None:
            _check_public_url(str(value), f"availability.{key}")
    facts = data.get("facts")
    if not isinstance(facts, list) or not facts:
        raise PackError("facts must list the grounded claims the copy uses")
    for i, fact in enumerate(facts):
        if not isinstance(fact, dict):
            raise PackError(f"facts[{i}] must be an object")
        _req_str(fact, "claim", f"facts[{i}]")
        _req_str(fact, "source", f"facts[{i}]")
    captures = data.get("captures")
    if not isinstance(captures, list) or not 1 <= len(captures) <= MAX_CAPTURES:
        raise PackError(f"captures must list 1-{MAX_CAPTURES} capture sources")
    for i, capture in enumerate(captures):
        _validate_capture(capture, i)
    _validate_product(data.get("product"), language)
    concepts = data.get("concepts")
    if not isinstance(concepts, list) or len(concepts) != CONCEPT_COUNT:
        raise PackError(f"concepts must list exactly {CONCEPT_COUNT} ad concepts")
    aspects = {a for c in captures for a in c["formats"]}
    for i, concept in enumerate(concepts):
        _validate_concept(concept, i, language, aspects)
    ids = [c["id"] for c in concepts]
    if len(set(ids)) != len(ids):
        raise PackError("concept ids must be unique")
    lint_honesty(data)


def load_pack(path: Path) -> AdPack:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackError(f"{path}: cannot read pack ({exc})") from exc
    try:
        validate(data)
    except PackError as exc:
        raise PackError(f"{Path(path).name}: {exc}") from exc
    return AdPack(path=Path(path), data=data)


def load_dir(directory: Path) -> list[AdPack]:
    paths = sorted(p for p in Path(directory).glob("*.json") if p.is_file())
    if not paths:
        raise PackError(f"no ad packs (*.json) in {directory}")
    packs = [load_pack(p) for p in paths]
    ids = [p.product_id for p in packs]
    if len(set(ids)) != len(ids):
        raise PackError("two packs share a product_id")
    return packs


# --------------------------------------------------------------------------- #
# exact request bodies
# --------------------------------------------------------------------------- #
def capture_body(capture: dict[str, Any]) -> dict[str, Any]:
    """``POST /api/v1/capture`` body (router ``CreateBody``)."""
    body: dict[str, Any] = {"kind": capture["kind"], "formats": list(capture["formats"])}
    if capture.get("duration_s") is not None:
        body["duration_s"] = int(capture["duration_s"])
    if capture["kind"] == "native_game":
        native = {k: v for k, v in capture["native"].items() if v not in (None, "")}
        body["native"] = native
    else:
        body["url"] = capture["url"]
        body["cursor"] = bool(capture.get("cursor", True))
    return body


def project_body(pack: AdPack) -> dict[str, Any]:
    """``POST /api/v1/ad-studio/projects`` body (``CreateProjectBody``); no variants are queued."""
    data = pack.data
    product = data["product"]
    manual = {
        "title": product["title"],
        "brand": product.get("brand", ""),
        "description": product["description"],
        "bullets": list(product.get("bullets") or []),
        "images": list(product.get("images") or []),
        "language": data["language"],
    }
    angles = [
        {key: concept[key] for key in ("hook", "pain", "proof", "offer", "cta")} | {"kind": concept["angle_kind"], "source": "adpack"}
        for concept in data["concepts"]
    ]
    body: dict[str, Any] = {
        "title": pack.project_title,
        "product": manual,
        "language": data["language"],
        "angle_count": CONCEPT_COUNT,
        "use_llm": False,
        "angles": angles,
    }
    web = data["availability"].get("web") or data["availability"].get("app_store")
    if web:
        body["url"] = web
    return body


def ads_body(pack: AdPack, concept: dict[str, Any]) -> dict[str, Any]:
    """``POST /api/v1/capture/{id}/ads`` body (``AdsBody``) for one concept.

    ``platforms`` is always empty: the target platform is guidance for the
    human who publishes, never an auto-publish instruction.
    """
    body: dict[str, Any] = {
        "mode": FREE_FORMATS[concept["format"]],
        "aspects": [concept["aspect"]],
        "script": concept["script"],
        "language": pack.data["language"],
        "platforms": [],
    }
    if concept.get("voice_name"):
        body["voice_name"] = concept["voice_name"]
    return body


def capture_match_key(body: dict[str, Any]) -> tuple[str, str]:
    """(kind, source) used to find an existing capture of the same source (idempotency)."""
    if body["kind"] == "native_game":
        native = body["native"]
        if native.get("deep_link"):
            return "native_game", native["deep_link"]
        device = native.get("device") or ("booted" if native["platform"] == "ios" else "")
        return "native_game", f"{native['platform']}-device://{device}/{native.get('app_id') or 'running-app'}"
    return body["kind"], normalize_url(body["url"])


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{(parsed.hostname or '').lower()}{path}{query}"


def plan(pack: AdPack) -> dict[str, Any]:
    """Everything ``--apply`` would send for one pack, plus the follow-up ad bodies."""
    return {
        "product_id": pack.product_id,
        "project": project_body(pack),
        "captures": [capture_body(c) for c in pack.data["captures"]],
        "ads_after_capture": [
            {"concept": c["id"], "platform_hint": c["platform"], "body": ads_body(pack, c)}
            for c in pack.data["concepts"]
        ],
    }


__all__ = [
    "AdPack", "PackError", "SCHEMA", "ads_body", "capture_body", "capture_match_key", "lint_honesty",
    "load_dir", "load_pack", "normalize_url", "plan", "project_body", "validate",
]
