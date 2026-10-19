"""Menivor mobile/desktop icon configuration and media invariants."""

from __future__ import annotations

import json
import plistlib
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
MOBILE = REPO / "apps" / "mobile"
DESKTOP = REPO / "apps" / "desktop" / "packaging"


def _image(relative: str) -> Image.Image:
    return Image.open(MOBILE / relative)


def test_expo_icon_paths_exist_with_platform_dimensions():
    config = json.loads((MOBILE / "app.json").read_text())["expo"]
    paths = {
        config["icon"]: (1024, 1024),
        config["ios"]["icon"]: (1024, 1024),
        config["android"]["adaptiveIcon"]["foregroundImage"]: (1024, 1024),
        config["splash"]["image"]: (1024, 1024),
    }
    for relative, expected_size in paths.items():
        with _image(relative) as image:
            assert image.size == expected_size
            assert image.format == "PNG"
    # Favicon: a square PNG at least 48px (the editorial mark ships at 96px).
    with _image(config["web"]["favicon"]) as favicon:
        assert favicon.format == "PNG"
        assert favicon.size[0] == favicon.size[1] >= 48


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info


def test_full_icon_is_opaque():
    # App Store rejects icons with an alpha channel. A palette PNG (compressed)
    # is fine as long as it carries no transparency.
    with _image("assets/icon.png") as icon:
        assert icon.mode in {"RGB", "P"}
        assert not _has_alpha(icon)


def test_splash_and_adaptive_background_use_locked_ink_color():
    # Editorial redesign (2026-09-06): ink #0a0a0b replaced the old #140A14.
    config = json.loads((MOBILE / "app.json").read_text())["expo"]
    assert config["android"]["adaptiveIcon"]["backgroundColor"] == "#0a0a0b"
    assert config["splash"]["backgroundColor"] == "#0a0a0b"


def test_desktop_packaging_references_real_menivor_icons():
    plist_path = DESKTOP / "macos" / "Info.plist"
    config = plistlib.loads(plist_path.read_bytes())
    assert config["CFBundleIconFile"] == "Menivor.icns"
    assert (DESKTOP / "macos" / config["CFBundleIconFile"]).stat().st_size > 0
    with Image.open(DESKTOP / "macos" / "Menivor-1024.png") as icon:
        assert icon.size == (1024, 1024)
    with Image.open(DESKTOP / "windows" / "Menivor.ico") as icon:
        assert icon.format == "ICO"
        assert icon.size == (256, 256)
    with Image.open(DESKTOP / "linux" / "menivor.png") as icon:
        assert icon.size == (512, 512)

    desktop_entry = (DESKTOP / "linux" / "reelforge.desktop").read_text()
    recipe = (DESKTOP / "linux" / "AppImageBuilder.yml").read_text()
    assert "Name=Menivor" in desktop_entry
    assert "Icon=menivor" in desktop_entry
    assert "name: Menivor" in recipe
    assert "icon: menivor" in recipe
