"""Import product images into the owner's media library (R2 ``uploads/``).

Each remote image is fetched through the SSRF guard, decoded with Pillow (which
also rejects non-images and decompression bombs), normalized to an RGB JPEG
capped at 2048px on the long edge, content-hashed for de-duplication, uploaded
privately, and recorded as an owned ``Asset`` (``kind='image'``). Owned
``uploads/`` keys are what the rest of the platform accepts as inputs — the
B-roll i2v generator, the editor, and the reel pipeline — so imported product
images are immediately reusable outside Ad Studio.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import io
import uuid
from typing import Any, Callable

from loguru import logger

from app.domains.adstudio.fetch import IMAGE_MAX_BYTES, FetchError, FetchResult, safe_get

MAX_IMPORTED_IMAGES = 8
MAX_EDGE = 2048
MIN_EDGE = 200
MAX_PIXELS = 60_000_000


def normalize_image(data: bytes) -> tuple[bytes, int, int] | None:
    """Decode arbitrary image bytes into a bounded RGB JPEG (None if unusable)."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as probe:
            width, height = probe.size
            if width * height > MAX_PIXELS:
                return None
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            if min(img.size) < MIN_EDGE:
                return None
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                canvas = Image.new("RGB", rgba.size, (255, 255, 255))
                canvas.paste(rgba, mask=rgba.split()[-1])
                img_rgb = canvas
            else:
                img_rgb = img.convert("RGB")
            img_rgb.thumbnail((MAX_EDGE, MAX_EDGE))
            out = io.BytesIO()
            img_rgb.save(out, "JPEG", quality=90, optimize=True)
            return out.getvalue(), img_rgb.size[0], img_rgb.size[1]
    except Exception:  # noqa: BLE001 - any decode failure means "skip this image"
        return None


def store_remote_images(
    urls: list[str],
    *,
    fetcher: Callable[..., FetchResult] | None = None,
    uploader: Callable[[str, bytes], None] | None = None,
) -> list[dict[str, Any]]:
    """Fetch, normalize, de-duplicate and upload up to 8 product images.

    Network-only (no DB session is held while remote stores respond); the
    returned entries are recorded as owned assets by :func:`register_images`.
    """
    fetch = fetcher or safe_get
    upload = uploader or _upload

    def _download(url: str) -> tuple[bytes, int, int] | None:
        try:
            result = fetch(url, max_bytes=IMAGE_MAX_BYTES, accept="image/jpeg,image/png,image/webp,image/*;q=0.8")
        except FetchError as exc:
            logger.info(f"adstudio image skipped ({exc.status_code}): {exc.message}")
            return None
        return normalize_image(result.body)

    candidates = list(dict.fromkeys(u for u in urls if u))[: MAX_IMPORTED_IMAGES + 4]
    if not candidates:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        downloaded = list(pool.map(_download, candidates))

    stored: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url, normalized in zip(candidates, downloaded):
        if len(stored) >= MAX_IMPORTED_IMAGES:
            break
        if normalized is None:
            continue
        data, width, height = normalized
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        key = f"uploads/{uuid.uuid4().hex}.jpg"
        try:
            upload(key, data)
        except Exception as exc:  # noqa: BLE001 - storage outage for one image
            logger.warning(f"adstudio image upload failed: {exc}")
            continue
        stored.append({"key": key, "origin_url": url, "width": width, "height": height, "size": len(data)})
    return stored


def register_images(session: Any, *, user_id: str, project_id: str, stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Record stored images as owned ``image`` assets; returns project entries."""
    from app.models.db.repositories import AssetRepository

    repo = AssetRepository(session)
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(stored):
        repo.create(
            user_id=user_id,
            kind="image",
            r2_key=item["key"],
            content_type="image/jpeg",
            size_bytes=int(item.get("size") or 0),
            meta={
                "filename": f"product-{index + 1}.jpg",
                "source": "adstudio",
                "project_id": project_id,
                "origin_url": str(item.get("origin_url") or "")[:1000],
                "upload_state": "registered",
            },
        )
        entries.append({k: item[k] for k in ("key", "origin_url", "width", "height")})
    return entries


def _upload(key: str, data: bytes) -> None:
    from app.platform.storage.r2 import get_r2_client

    get_r2_client().upload_bytes(key, data, content_type="image/jpeg")


def owned_image_entries(session: Any, *, user_id: str, keys: list[str]) -> list[dict[str, Any]]:
    """Validate caller-supplied upload keys (already in their library)."""
    from app.domains.media.service import require_owned_asset

    entries: list[dict[str, Any]] = []
    for key in dict.fromkeys(k.strip() for k in keys if k and k.strip()):
        require_owned_asset(session, user_id=user_id, key=key)
        entries.append({"key": key, "origin_url": "", "width": 0, "height": 0})
    return entries[:MAX_IMPORTED_IMAGES]


__all__ = ["MAX_IMPORTED_IMAGES", "normalize_image", "owned_image_entries", "register_images", "store_remote_images"]
