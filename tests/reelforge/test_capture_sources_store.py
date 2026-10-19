"""Capture: URL classification and store-listing parsing (pure, no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.domains.adstudio.fetch import FetchError
from app.domains.capture import store
from app.domains.capture.sources import SourceError, apple_ref, classify, detect_kind, play_ref


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #
def test_apple_ref_reads_id_and_country() -> None:
    assert apple_ref("https://apps.apple.com/tr/app/orbit-arcade/id6741234567") == {"app_id": "6741234567", "country": "tr"}
    assert apple_ref("https://apps.apple.com/app/id6741234567?l=en") == {"app_id": "6741234567", "country": "us"}
    assert apple_ref("https://itunes.apple.com/us/app/x/id123456789") == {"app_id": "123456789", "country": "us"}
    assert apple_ref("https://apps.apple.com/us/developer/x/id12") is None
    assert apple_ref("https://example.com/id6741234567") is None


def test_play_ref_reads_package_and_locale() -> None:
    assert play_ref("https://play.google.com/store/apps/details?id=com.example.game&hl=tr&gl=tr") == {
        "package": "com.example.game", "hl": "tr", "gl": "TR",
    }
    assert play_ref("https://play.google.com/store/apps/details?id=com.a.b") == {"package": "com.a.b", "hl": "en", "gl": "US"}
    assert play_ref("https://play.google.com/store/apps/details?id=bad") is None
    assert play_ref("https://play.google.com/store/apps/dev?id=123") is None


def test_classify_auto_and_explicit_kinds() -> None:
    assert detect_kind("https://apps.apple.com/us/app/x/id123456789") == "app_store"
    assert classify("https://play.google.com/store/apps/details?id=com.a.b").kind == "play_store"
    assert classify("https://example.com/").kind == "website"
    # Web games are not captured (our games are native); old kind is refused with guidance.
    with pytest.raises(SourceError, match="native game"):
        classify("https://games.example.com/flowblast", "web_game")
    with pytest.raises(SourceError, match="simulator"):
        classify("https://games.example.com/flowblast", "native_game")


def test_classify_rejects_mismatches() -> None:
    with pytest.raises(SourceError):
        classify("https://example.com/", "app_store")
    with pytest.raises(SourceError):
        classify("https://apps.apple.com/us/app/x/id123456789", "website")
    with pytest.raises(SourceError):
        classify("https://example.com/", "tiktok")


# --------------------------------------------------------------------------- #
# App Store (iTunes Lookup)
# --------------------------------------------------------------------------- #
ITUNES = {
    "resultCount": 1,
    "results": [{
        "kind": "software",
        "trackName": "Orbit Arcade",
        "sellerName": "Ereboslab",
        "description": "Dodge planets.\nChain combos for a high score!",
        "artworkUrl512": "https://is1.mzstatic.com/icon512.png",
        "screenshotUrls": [f"https://is1.mzstatic.com/s{i}.png" for i in range(10)],
        "averageUserRating": 4.63,
        "userRatingCount": 120,
        "formattedPrice": "Free",
        "primaryGenreName": "Games",
        "trackViewUrl": "https://apps.apple.com/us/app/orbit-arcade/id6741234567",
    }],
}


def test_parse_itunes_maps_fields_and_caps_screenshots() -> None:
    listing = store.parse_itunes(ITUNES)
    assert listing["title"] == "Orbit Arcade"
    assert listing["developer"] == "Ereboslab"
    assert listing["icon_url"].endswith("icon512.png")
    assert len(listing["screenshots"]) == store.MAX_SCREENSHOTS
    assert listing["rating"] == 4.6 and listing["rating_count"] == 120


def test_parse_itunes_empty_is_404() -> None:
    with pytest.raises(store.StoreError) as err:
        store.parse_itunes({"resultCount": 0, "results": []})
    assert err.value.status_code == 404


def test_fetch_app_store_uses_lookup_api() -> None:
    seen = {}

    def getter(url, **kwargs):
        seen["url"] = url
        return SimpleNamespace(text=lambda: json.dumps(ITUNES))

    listing = store.fetch_app_store({"app_id": "6741234567", "country": "tr"}, getter=getter)
    assert seen["url"].startswith("https://itunes.apple.com/lookup?id=6741234567&country=tr")
    assert listing["store"] == "app_store"


def test_fetch_maps_fetch_errors() -> None:
    def getter(url, **kwargs):
        raise FetchError(424, "blocked")

    with pytest.raises(store.StoreError) as err:
        store.fetch_play_store({"package": "com.a.b"}, getter=getter)
    assert err.value.status_code == 424


# --------------------------------------------------------------------------- #
# Google Play (public page)
# --------------------------------------------------------------------------- #
PLAY_HTML = """
<html><head>
<meta property="og:title" content="Aqua Sort - Apps on Google Play">
<meta name="description" content="Sort the water. Relax with 250 levels.">
<meta property="og:image" content="https://play-lh.googleusercontent.com/ICON123=w526-h296">
</head><body>
<a href="/store/apps/dev?id=555"><span>Ereboslab</span></a>
<img src="https://play-lh.googleusercontent.com/ICON123=s64">
<img src="https://play-lh.googleusercontent.com/AVATAR=w48-h48">
<img src="https://play-lh.googleusercontent.com/SHOT_A=w526-h296-rw">
<img src="https://play-lh.googleusercontent.com/SHOT_B=w526-h296-rw">
<img src="https://play-lh.googleusercontent.com/SHOT_A=w1052-h592-rw">
<div aria-label="Rated 4.4 stars out of five stars"></div>
</body></html>
"""


def test_parse_play_reads_listing() -> None:
    listing = store.parse_play(PLAY_HTML, url="https://play.google.com/store/apps/details?id=com.a.b")
    assert listing["title"] == "Aqua Sort"
    assert listing["developer"] == "Ereboslab"
    assert listing["description"].startswith("Sort the water")
    assert listing["icon_url"] == "https://play-lh.googleusercontent.com/ICON123=s512"
    assert listing["screenshots"] == [
        "https://play-lh.googleusercontent.com/SHOT_A=w1080",
        "https://play-lh.googleusercontent.com/SHOT_B=w1080",
    ]
    assert listing["rating"] == 4.4


def test_parse_play_without_title_is_404() -> None:
    with pytest.raises(store.StoreError):
        store.parse_play("<html><head></head></html>")


def test_download_image_rejects_tiny_and_non_images(tmp_path) -> None:
    from io import BytesIO

    from PIL import Image

    def as_bytes(size):
        buf = BytesIO()
        Image.new("RGB", size, (10, 20, 30)).save(buf, "PNG")
        return buf.getvalue()

    ok = store.download_image("u", str(tmp_path / "a.jpg"), getter=lambda *a, **k: SimpleNamespace(body=as_bytes((300, 600))))
    assert ok and (tmp_path / "a.jpg").exists()
    assert store.download_image("u", str(tmp_path / "b.jpg"), getter=lambda *a, **k: SimpleNamespace(body=as_bytes((20, 20)))) is None
    assert store.download_image("u", str(tmp_path / "c.jpg"), getter=lambda *a, **k: SimpleNamespace(body=b"nope")) is None
