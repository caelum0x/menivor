"""Where a style's product visuals come from.

* :func:`page_image` - the pasted page's own preview image (``og:image`` /
  ``twitter:image``), fetched through the SSRF-safe fetcher. It is the
  creator's own page, so this is their own marketing image.
* :func:`anime_images` - ORIGINAL AI-generated anime-style illustrations
  (Replicate FLUX schnell). Prompts describe original characters and scenes
  only: no franchise, studio, artist or character names are ever sent.
* :func:`title_card` - a branded card rendered locally with FFmpeg when there
  is no image at all.

Every helper is best-effort and returns ``[]`` / ``""`` on failure so a style
can always fall back to the next source.
"""

from __future__ import annotations

import os
import re
from html import unescape
from typing import Any, Callable
from urllib.parse import urljoin

from loguru import logger

# FLUX schnell on Replicate is billed per output image.
ANIME_MODEL = "black-forest-labs/flux-schnell"
ANIME_COST_PER_IMAGE_USD = 0.003
DEFAULT_ANIME_IMAGES = 4
MAX_ANIME_IMAGES = 6
_IMAGE_MAX_BYTES = 8_000_000
_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_META_IMAGE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](?:og:image(?::url)?|twitter:image(?::src)?)[\"'][^>]*>",
    re.IGNORECASE,
)
_CONTENT = re.compile(r"content=[\"']([^\"']+)[\"']", re.IGNORECASE)
# Words that would steer the model toward an existing franchise or studio look.
_BLOCKED_TERMS = re.compile(
    r"\b(ghibli|miyazaki|naruto|one piece|dragon ball|pokemon|pok[eé]mon|disney|pixar|"
    r"demon slayer|jujutsu|attack on titan|sailor moon|studio|makoto shinkai)\b",
    re.IGNORECASE,
)
ANIME_STYLE_SUFFIX = (
    "original anime-style illustration, original characters, clean cel shading, "
    "soft cinematic lighting, vibrant colors, vertical 9:16 composition, "
    "no text, no letters, no logos, no watermark"
)


def meta_image_url(html: str, page_url: str) -> str:
    """The absolute ``og:image``/``twitter:image`` URL of a page, else ``""``."""
    for tag in _META_IMAGE.finditer(html or ""):
        match = _CONTENT.search(tag.group(0))
        if match:
            candidate = unescape(match.group(1).strip())
            if candidate:
                absolute = urljoin(page_url, candidate)
                if absolute.startswith(("http://", "https://")):
                    return absolute
    return ""


def page_image(source_url: str, dest_dir: str, *, fetch: Callable[..., Any] | None = None) -> list[str]:
    """Download the page's preview image into ``dest_dir``; ``[]`` on any failure."""
    url = str(source_url or "").strip()
    if not url:
        return []
    try:
        if fetch is None:
            from app.domains.adstudio.fetch import safe_get as fetch
        page = fetch(url, max_bytes=2_000_000)
        image_url = meta_image_url(page.text(), getattr(page, "url", url) or url)
        if not image_url:
            return []
        image = fetch(image_url, max_bytes=_IMAGE_MAX_BYTES, accept="image/*")
        content_type = str(image.content_type or "").split(";")[0].strip().lower()
        suffix = _IMAGE_TYPES.get(content_type)
        if not suffix or not image.body:
            return []
        os.makedirs(dest_dir, exist_ok=True)
        path = os.path.join(dest_dir, f"page{suffix}")
        with open(path, "wb") as handle:
            handle.write(image.body)
        return [path]
    except Exception as exc:  # noqa: BLE001 - visuals are best-effort
        logger.warning(f"style visuals: page image unavailable: {type(exc).__name__}: {exc}")
        return []


def scene_beats(script: str, count: int) -> list[str]:
    """Up to ``count`` short scene descriptions from the script's paragraphs."""
    parts = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n|(?<=[.!?])\s+", script or "")]
    parts = [p for p in parts if len(p) > 3]
    if not parts:
        return []
    step = max(1, len(parts) // max(1, count))
    return [parts[i][:220] for i in range(0, len(parts), step)][:count]


def anime_prompt(beat: str, subject: str) -> str:
    """An original anime-style scene prompt for one script beat."""
    safe_beat = _BLOCKED_TERMS.sub("", beat or "").strip()
    safe_subject = _BLOCKED_TERMS.sub("", subject or "").strip()
    scene = safe_beat or safe_subject or "a creator working late at a desk"
    return (
        f"A young creator in a cozy modern city, scene: {scene}. "
        f"Theme: {safe_subject[:120]}. {ANIME_STYLE_SUFFIX}"
    )


def anime_image_count() -> int:
    raw = (os.getenv("STYLE_ANIME_IMAGES") or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_ANIME_IMAGES
    except ValueError:
        value = DEFAULT_ANIME_IMAGES
    return max(1, min(MAX_ANIME_IMAGES, value))


def anime_images(
    script: str,
    subject: str,
    dest_dir: str,
    *,
    count: int | None = None,
    generate: Callable[..., str] | None = None,
    download: Callable[[str, str], str] | None = None,
) -> tuple[list[str], float]:
    """Generate original anime-style scenes; returns ``(paths, spend_usd)``."""
    api_key = (os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if generate is None and not api_key:
        logger.warning("style visuals: REPLICATE_API_TOKEN not set; no anime scenes")
        return [], 0.0
    total = count or anime_image_count()
    beats = scene_beats(script, total) or [subject]
    while len(beats) < total:
        beats.append(beats[len(beats) % max(1, len(beats))])
    if generate is None:
        from app.domains.gateway.replicate_image import replicate_generate_image

        def generate(prompt: str) -> str:  # type: ignore[misc]
            return replicate_generate_image(ANIME_MODEL, prompt, api_key=api_key, aspect_ratio="9:16")

    fetch = download or _download
    os.makedirs(dest_dir, exist_ok=True)
    paths: list[str] = []
    spend = 0.0
    for index, beat in enumerate(beats[:total]):
        try:
            url = generate(anime_prompt(beat, subject))
            spend += ANIME_COST_PER_IMAGE_USD
            paths.append(fetch(url, os.path.join(dest_dir, f"anime-{index}.img")))
        except Exception as exc:  # noqa: BLE001 - keep whatever scenes succeeded
            logger.warning(f"style visuals: anime scene {index} failed: {type(exc).__name__}: {exc}")
    logger.info(f"style visuals: {len(paths)} anime scenes, provider spend ~${spend:.3f}")
    return paths, spend


CHARACTER_PROMPT = (
    "An original friendly cartoon narrator character: a round-faced raccoon in a "
    "hoodie with oversized headphones, sitting at a desk and talking with lively "
    "expression, bold flat 2D cartoon style, thick clean outlines, solid warm "
    "background, centered head-and-shoulders portrait, no text, no logos, not "
    "based on any existing show or character"
)


def character_image(
    dest_dir: str,
    *,
    generate: Callable[[str], str] | None = None,
    download: Callable[[str, str], str] | None = None,
) -> tuple[list[str], float]:
    """One ORIGINAL cartoon narrator portrait; returns ``([path], spend_usd)``."""
    api_key = (os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if generate is None and not api_key:
        return [], 0.0
    if generate is None:
        from app.domains.gateway.replicate_image import replicate_generate_image

        def generate(prompt: str) -> str:  # type: ignore[misc]
            return replicate_generate_image(ANIME_MODEL, prompt, api_key=api_key, aspect_ratio="1:1")

    os.makedirs(dest_dir, exist_ok=True)
    try:
        url = generate(CHARACTER_PROMPT)
        path = (download or _download)(url, os.path.join(dest_dir, "narrator.img"))
        return [path], ANIME_COST_PER_IMAGE_USD
    except Exception as exc:  # noqa: BLE001 - the story scene works without it
        logger.warning(f"style visuals: narrator portrait failed: {type(exc).__name__}: {exc}")
        return [], 0.0


def _download(url: str, dest: str) -> str:
    import requests

    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        written = 0
        with open(dest, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 16):
                written += len(chunk)
                if written > _IMAGE_MAX_BYTES:
                    raise ValueError("generated image too large")
                handle.write(chunk)
    return dest


__all__ = [
    "ANIME_COST_PER_IMAGE_USD",
    "ANIME_MODEL",
    "anime_image_count",
    "anime_images",
    "anime_prompt",
    "character_image",
    "meta_image_url",
    "page_image",
    "scene_beats",
]
