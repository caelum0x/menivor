"""Design Studio service: brand-kit layouts, owner-scoped documents, PNG export, scheduling.

Flow: ``generate`` (prompt + brand kit -> 3-4 layout options, nothing stored)
-> ``create_doc`` (the chosen option becomes a :class:`DesignDoc`) -> the
editor saves with ``update_doc`` -> the browser renders each page to PNG and
``export`` stores them in R2 as owned ``image`` assets -> ``schedule`` hands
the exported images to the approvals feed as a ``design_publish`` item;
approving it queues the image posts.

Only ``ai_image`` spends money: it goes through the media gateway, which
reserves and settles against the caller's wallet (success-only billing).
Every read and write is scoped to the owning user.
"""

from __future__ import annotations

import base64
import binascii
import io
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from loguru import logger
from sqlalchemy import func, select

from app.domains.design import canvas as canvas_mod
from app.domains.design import layouts
from app.domains.design.copy import design_copy
from app.domains.design.models import (
    SIZE_PRESETS,
    STATUS_DRAFT,
    STATUS_EXPORTED,
    STATUS_SCHEDULED,
    DesignDoc,
    DesignTemplate,
)

try:
    from app.models.db.base import get_session

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - reported as a 503
    get_session = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

MAX_EXPORT_BYTES = 15_000_000          # one PNG page
MAX_UPLOAD_BYTES = 10_000_000          # one image placed on the canvas
MAX_IMAGE_SIDE = 4096
MAX_LOGO_SIDE = 800
MAX_MEDIA_BYTES = 20_000_000
MAX_SCHEDULE_AHEAD = timedelta(days=365)
PLATFORMS = frozenset({
    "instagram", "facebook", "tiktok", "linkedin", "x", "threads", "pinterest", "bluesky",
    "youtube", "telegram", "discord", "mastodon", "app_store", "play_store", "website", "other",
})
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_DATA_URL_RE = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,", re.IGNORECASE)


class DesignError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.status_code = status_code
        super().__init__(message)


def _require_ready() -> None:
    if get_session is None:
        raise DesignError(f"design persistence unavailable: {_IMPORT_ERROR}", status_code=503)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


# --------------------------------------------------------------------------- #
# Storage seams (patched in tests)
# --------------------------------------------------------------------------- #
def _r2() -> Any:
    from app.platform.storage.r2 import get_r2_client

    return get_r2_client()


def _upload(key: str, data: bytes, content_type: str) -> None:
    _r2().upload_bytes(key, data, content_type=content_type)


def _download(key: str) -> bytes:
    import tempfile

    fd, path = tempfile.mkstemp(prefix="design-", suffix=".bin")
    os.close(fd)
    try:
        _r2().download_file(key, path)
        if os.path.getsize(path) > MAX_MEDIA_BYTES:
            raise DesignError("this image is too large to open in the editor", status_code=413)
        with open(path, "rb") as fp:
            return fp.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _presign(key: str, download_name: str | None = None) -> str | None:
    if not key:
        return None
    try:
        return _r2().presign_result_get(key, download_name=download_name)
    except Exception:  # noqa: BLE001 - a read never fails on one presign
        return None


def _fetch_remote(url: str) -> bytes:
    """Fetch a public image through the Ad Studio SSRF guard (or decode a data: URL)."""
    match = _DATA_URL_RE.match(url or "")
    if match:
        try:
            return base64.b64decode(url[match.end():], validate=False)
        except (binascii.Error, ValueError) as exc:
            raise DesignError("the image could not be decoded", status_code=502) from exc
    from app.domains.adstudio.fetch import IMAGE_MAX_BYTES, FetchError, safe_get

    try:
        return safe_get(url, max_bytes=IMAGE_MAX_BYTES, accept="image/*").body
    except FetchError as exc:
        raise DesignError(f"could not download the image: {exc}", status_code=502) from exc


# --------------------------------------------------------------------------- #
# Images
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Normalized:
    data: bytes
    content_type: str
    width: int
    height: int


def normalize_image(data: bytes, *, max_side: int = MAX_IMAGE_SIDE, keep_alpha: bool = True) -> Normalized:
    """Re-encode an image (strips metadata, caps size). PNG keeps transparency; else JPEG."""
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - Pillow is a core dependency
        raise DesignError("image processing is unavailable on this server", status_code=503) from exc
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            if max(img.size) > max_side:
                img.thumbnail((max_side, max_side))
            has_alpha = keep_alpha and (img.mode in ("RGBA", "LA", "P") and "transparency" in img.info
                                        or img.mode in ("RGBA", "LA"))
            out = io.BytesIO()
            if has_alpha:
                img.convert("RGBA").save(out, format="PNG", optimize=True)
                ctype = "image/png"
            else:
                img.convert("RGB").save(out, format="JPEG", quality=90)
                ctype = "image/jpeg"
            return Normalized(out.getvalue(), ctype, img.size[0], img.size[1])
    except DesignError:
        raise
    except Exception as exc:  # noqa: BLE001 - PIL raises many types for bad input
        raise DesignError("this file is not an image we can use (PNG, JPEG or WebP)") from exc


def _store_image(session: Any, user_id: str, norm: Normalized, *, source: str, extra: dict | None = None) -> dict:
    from app.models.db.repositories import AssetRepository

    ext = "png" if norm.content_type == "image/png" else "jpg"
    key = f"uploads/design-{uuid.uuid4().hex}.{ext}"
    _upload(key, norm.data, norm.content_type)
    asset = AssetRepository(session).create(
        user_id=user_id, kind="image", r2_key=key, content_type=norm.content_type, size_bytes=len(norm.data),
        meta={"filename": f"{source}.{ext}", "source": source, "width": norm.width, "height": norm.height,
              "upload_state": "registered", **(extra or {})},
    )
    return {"key": key, "asset_id": str(asset.id), "width": norm.width, "height": norm.height,
            "content_type": norm.content_type}


def decode_base64_image(value: str, *, max_bytes: int) -> bytes:
    raw = (value or "").strip()
    match = _DATA_URL_RE.match(raw)
    if match:
        raw = raw[match.end():]
    if len(raw) > max_bytes * 4 // 3 + 16:
        raise DesignError("the image is too large", status_code=413)
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DesignError("the image is not valid base64") from exc
    if not data:
        raise DesignError("the image is empty")
    if len(data) > max_bytes:
        raise DesignError("the image is too large", status_code=413)
    return data


def upload_image(user_id: str, data_b64: str) -> dict:
    """Place a user image on the canvas: normalise, store in R2, register as an owned asset."""
    _require_ready()
    norm = normalize_image(decode_base64_image(data_b64, max_bytes=MAX_UPLOAD_BYTES))
    with get_session() as session:  # type: ignore[misc]
        return _store_image(session, user_id, norm, source="design_upload")


def _owned(session: Any, user_id: str, key: str) -> bool:
    from app.models.db.models import Asset

    return session.execute(
        select(Asset.id).where(Asset.user_id == user_id, Asset.r2_key == key).limit(1)
    ).first() is not None


def media(user_id: str, key: str) -> tuple[bytes, str]:
    """Bytes of an owned image for the editor (same-origin fetch keeps the export canvas untainted)."""
    _require_ready()
    if not canvas_mod._KEY_RE.match(key or "") or ".." in key:
        raise DesignError("unknown image", status_code=404)
    with get_session() as session:  # type: ignore[misc]
        from app.models.db.models import Asset

        asset = session.execute(
            select(Asset).where(Asset.user_id == user_id, Asset.r2_key == key).limit(1)
        ).scalar_one_or_none()
        if asset is None:
            raise DesignError("unknown image", status_code=404)
        ctype = asset.content_type or "application/octet-stream"
    if not ctype.startswith("image/"):
        raise DesignError("unknown image", status_code=404)
    return _download(key), ctype


# --------------------------------------------------------------------------- #
# Brand kit
# --------------------------------------------------------------------------- #
def _kits(session: Any, user_id: str) -> list[Any]:
    from app.models.db.repositories import UserPresetRepository

    workspace_ids: list[str] = []
    try:
        from app.services import workspaces as ws_service

        workspace_ids = [ws.id for ws in ws_service.list_workspaces(session, user_id) if getattr(ws, "id", None)]
    except Exception as exc:  # noqa: BLE001 - sharing layer optional; own kits still work
        logger.debug(f"design: workspace lookup skipped for {user_id}: {exc}")
    return UserPresetRepository(session).list_for_user_and_workspaces(user_id, workspace_ids)


def resolve_brand(session: Any, user_id: str, brand_kit_id: str | None) -> tuple[dict, str | None]:
    """The chosen kit's brand block (or the newest kit that has one). ``({}, None)`` when none."""
    kits = _kits(session, user_id)
    if brand_kit_id:
        kit = next((k for k in kits if k.id == brand_kit_id), None)
        if kit is None:
            raise DesignError("brand kit not found", status_code=404)
        block = (kit.config or {}).get("brand")
        return (dict(block) if isinstance(block, dict) else {}), kit.id
    for kit in kits:
        block = (kit.config or {}).get("brand")
        if isinstance(block, dict):
            return dict(block), kit.id
    return {}, None


def _logo_key(session: Any, user_id: str, logo_url: str, fetch: Callable[[str], bytes]) -> str:
    """Import the brand logo once into the caller's library; reuse it afterwards."""
    from app.models.db.models import Asset

    url = (logo_url or "").strip()
    if not url.lower().startswith(("https://", "http://")) or len(url) > 1000:
        return ""
    for asset in session.execute(
        select(Asset).where(Asset.user_id == user_id, Asset.kind == "image").order_by(Asset.created_at.desc()).limit(200)
    ).scalars():
        meta = asset.meta or {}
        if meta.get("source") == "design_logo" and meta.get("origin_url") == url:
            return asset.r2_key
    try:
        norm = normalize_image(fetch(url), max_side=MAX_LOGO_SIDE)
        return _store_image(session, user_id, norm, source="design_logo", extra={"origin_url": url})["key"]
    except Exception as exc:  # noqa: BLE001 - a logo we cannot fetch is left out, never fatal
        logger.info(f"design: brand logo import skipped for {user_id}: {exc}")
        return ""


def style_from_brand(brand: dict, logo_key: str = "") -> layouts.BrandStyle:
    colors = [c for c in (canvas_mod.color(v, "") for v in (brand.get("colors") or [])) if c]
    fonts = [f for f in (canvas_mod.font(v, "") for v in (brand.get("fonts") or [])) if f]
    by_lum = sorted(colors, key=layouts.luminance)
    dark = by_lum[0] if by_lum and layouts.luminance(by_lum[0]) < 0.08 else layouts.DEFAULT_DARK
    light = by_lum[-1] if by_lum and layouts.luminance(by_lum[-1]) > 0.85 else layouts.DEFAULT_LIGHT
    mids = [c for c in colors if c not in (dark, light)]
    primary = mids[0] if mids else (colors[0] if colors else layouts.DEFAULT_PRIMARY)
    accent = next((c for c in mids[1:] if layouts.contrast(c, primary) >= 1.8), None)
    if accent is None:
        accent = layouts.DEFAULT_ACCENT if layouts.contrast(layouts.DEFAULT_ACCENT, primary) >= 1.8 else light
    return layouts.BrandStyle(
        name=str(brand.get("name") or "")[:80], primary=primary, accent=accent, light=light, dark=dark,
        heading_font=fonts[0] if fonts else layouts.DEFAULT_FONT,
        body_font=fonts[1] if len(fonts) > 1 else (fonts[0] if fonts else layouts.DEFAULT_FONT),
        logo_key=logo_key,
    )


def _brand_summary(brand: dict, style: layouts.BrandStyle, kit_id: str | None) -> dict:
    return {
        "brand_kit_id": kit_id,
        "name": style.name,
        "colors": {"primary": style.primary, "accent": style.accent, "light": style.light, "dark": style.dark},
        "fonts": {"heading": style.heading_font, "body": style.body_font},
        "logo_key": style.logo_key or None,
        "has_brand": bool(brand),
    }


# --------------------------------------------------------------------------- #
# Generate
# --------------------------------------------------------------------------- #
def size_of(preset: str) -> tuple[int, int]:
    if preset not in SIZE_PRESETS:
        raise DesignError(f"size must be one of {sorted(SIZE_PRESETS)}")
    return SIZE_PRESETS[preset]


def generate(user_id: str, *, prompt: str, size_preset: str, brand_kit_id: str | None = None,
             use_llm: bool = True, fetch: Callable[[str], bytes] | None = None,
             generate_text: Callable[[str], str] | None = None) -> dict:
    """3-4 layout options from built-in templates. Nothing is stored except the imported logo."""
    _require_ready()
    width, height = size_of(size_preset)
    prompt = " ".join((prompt or "").split())
    if len(prompt) < 3:
        raise DesignError("describe the design in a few words")
    with get_session() as session:  # type: ignore[misc]
        brand, kit_id = resolve_brand(session, user_id, brand_kit_id)
        logo = _logo_key(session, user_id, str(brand.get("logo_url") or ""), fetch or _fetch_remote) if brand else ""
    style = style_from_brand(brand, logo)
    copy, source = design_copy(prompt, brand, size_preset, use_llm=use_llm, generate=generate_text)
    options = [
        {"template": t.slug, "name": t.name, "description": t.description,
         "canvas": layouts.build(t.slug, width, height, copy, style)}
        for t in layouts.templates_for(size_preset)[:4]
    ]
    return {
        "size_preset": size_preset, "width": width, "height": height,
        "copy": {"headline": copy.headline, "subline": copy.subline, "cta": copy.cta, "badge": copy.badge,
                 "points": list(copy.points)},
        "copy_source": source,
        "brand": _brand_summary(brand, style, kit_id),
        "options": options,
    }


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
def doc_view(row: DesignDoc, *, full: bool = True) -> dict:
    keys = list(row.exported_keys or [])
    view = {
        "id": row.id,
        "title": row.title or "Untitled design",
        "size_preset": row.size_preset,
        "width": row.width,
        "height": row.height,
        "template_id": row.template_id,
        "brand_kit_id": row.brand_kit_id,
        "prompt": row.prompt or "",
        "status": row.status,
        "used_ai_image": bool(row.used_ai_image),
        "page_count": len((row.canvas_json or {}).get("pages") or []),
        "thumb_url": _presign(row.thumb_key),
        "exported_at": _iso(row.exported_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }
    if full:
        view["canvas"] = row.canvas_json or {}
        view["exports"] = [
            {"key": k, "url": _presign(k, download_name=f"design-{row.id}-{i + 1}.png")} for i, k in enumerate(keys)
        ]
    return view


def _get(session: Any, user_id: str, doc_id: str) -> DesignDoc:
    row = session.get(DesignDoc, doc_id)
    if row is None or row.user_id != user_id:
        raise DesignError("design not found", status_code=404)
    return row


def _check_images(session: Any, user_id: str, canvas: dict) -> None:
    for key in canvas_mod.image_keys(canvas):
        if not _owned(session, user_id, key):
            raise DesignError("an image on the canvas is not in your library", status_code=403)


def _clean_canvas(canvas: Any) -> dict:
    try:
        return canvas_mod.sanitize(canvas)
    except canvas_mod.CanvasError as exc:
        raise DesignError(str(exc)) from exc


def create_doc(user_id: str, *, title: str, size_preset: str, canvas: Any, template: str = "",
               template_id: str | None = None, brand_kit_id: str | None = None, prompt: str = "") -> dict:
    _require_ready()
    width, height = size_of(size_preset)
    with get_session() as session:  # type: ignore[misc]
        if template_id:
            tpl = session.get(DesignTemplate, template_id)
            if tpl is None or (tpl.user_id not in (None, user_id)) or not tpl.is_active:
                raise DesignError("template not found", status_code=404)
            if canvas is None:
                canvas = tpl.layout_json
        if canvas is None:
            raise DesignError("pick a layout to start from")
        clean = _clean_canvas(canvas)
        _check_images(session, user_id, clean)
        if brand_kit_id:
            resolve_brand(session, user_id, brand_kit_id)  # 404 on a foreign kit
        row = DesignDoc(
            user_id=user_id, title=(title or "").strip()[:200] or "Untitled design", size_preset=size_preset,
            width=width, height=height, canvas_json=clean, template_id=template_id, brand_kit_id=brand_kit_id,
            prompt=(prompt or "")[:2000], status=STATUS_DRAFT, exported_keys=[],
        )
        if template and template in layouts.TEMPLATES:
            row.title = row.title if title else f"{layouts.TEMPLATES[template].name} design"
        session.add(row)
        session.flush()
        return doc_view(row)


def list_docs(user_id: str, *, limit: int = 30, offset: int = 0) -> dict:
    _require_ready()
    limit = max(1, min(int(limit or 30), 100))
    with get_session() as session:  # type: ignore[misc]
        total = int(session.execute(
            select(func.count()).select_from(DesignDoc).where(DesignDoc.user_id == user_id)).scalar() or 0)
        rows = session.execute(
            select(DesignDoc).where(DesignDoc.user_id == user_id)
            .order_by(DesignDoc.updated_at.desc(), DesignDoc.id.desc()).limit(limit).offset(max(0, int(offset or 0)))
        ).scalars().all()
        return {"designs": [doc_view(r, full=False) for r in rows], "total": total, "limit": limit,
                "offset": offset}


def get_doc(user_id: str, doc_id: str) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        return doc_view(_get(session, user_id, doc_id))


def update_doc(user_id: str, doc_id: str, *, title: str | None = None, canvas: Any = None) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        row = _get(session, user_id, doc_id)
        if title is not None:
            row.title = title.strip()[:200] or "Untitled design"
        if canvas is not None:
            clean = _clean_canvas(canvas)
            _check_images(session, user_id, clean)
            row.canvas_json = clean
            if row.status == STATUS_EXPORTED:
                row.status = STATUS_DRAFT  # the export no longer matches the canvas
        session.flush()
        return doc_view(row)


def delete_doc(user_id: str, doc_id: str) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        row = _get(session, user_id, doc_id)
        session.delete(row)
    return {"deleted": True, "id": doc_id}


def duplicate_doc(user_id: str, doc_id: str) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        src = _get(session, user_id, doc_id)
        row = DesignDoc(
            user_id=user_id, title=f"{src.title} copy"[:200], size_preset=src.size_preset, width=src.width,
            height=src.height, canvas_json=dict(src.canvas_json or {}), template_id=src.template_id,
            brand_kit_id=src.brand_kit_id, prompt=src.prompt, status=STATUS_DRAFT, exported_keys=[],
            used_ai_image=src.used_ai_image,
        )
        session.add(row)
        session.flush()
        return doc_view(row)


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def _png_size(data: bytes) -> tuple[int, int]:
    if not data.startswith(_PNG_MAGIC) or len(data) < 24 or data[12:16] != b"IHDR":
        raise DesignError("each exported page must be a PNG")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def export(user_id: str, doc_id: str, pages_b64: list[str], *, now: datetime | None = None) -> dict:
    """Store browser-rendered PNG pages in R2 as owned image assets."""
    _require_ready()
    moment = now or _utcnow()
    with get_session() as session:  # type: ignore[misc]
        row = _get(session, user_id, doc_id)
        expected = len((row.canvas_json or {}).get("pages") or [])
        width, height = row.width, row.height
    if len(pages_b64) != expected:
        raise DesignError(f"send one PNG per page ({expected})")
    pages = [decode_base64_image(p, max_bytes=MAX_EXPORT_BYTES) for p in pages_b64]
    for data in pages:
        w, h = _png_size(data)
        if (w, h) != (width, height):
            raise DesignError(f"each page must be {width}x{height} pixels (got {w}x{h})")
    keys: list[str] = []
    with get_session() as session:  # type: ignore[misc]
        from app.models.db.repositories import AssetRepository

        repo = AssetRepository(session)
        for index, data in enumerate(pages):
            key = f"uploads/design-{doc_id}-{uuid.uuid4().hex[:12]}-{index + 1}.png"
            try:
                _upload(key, data, "image/png")
            except Exception as exc:  # noqa: BLE001 - storage outage
                logger.error(f"design export upload failed for {doc_id}: {exc}")
                raise DesignError("could not save the export; try again", status_code=502) from exc
            repo.create(user_id=user_id, kind="image", r2_key=key, content_type="image/png", size_bytes=len(data),
                        meta={"filename": f"design-{index + 1}.png", "source": "design_export", "design_id": doc_id,
                              "page": index + 1, "width": width, "height": height, "upload_state": "registered"})
            keys.append(key)
        row = _get(session, user_id, doc_id)
        row.exported_keys = keys
        row.exported_asset_key = keys[0]
        row.thumb_key = keys[0]
        row.exported_at = moment
        if row.status == STATUS_DRAFT:
            row.status = STATUS_EXPORTED
        session.flush()
        return doc_view(row)


# --------------------------------------------------------------------------- #
# AI image (the only metered path)
# --------------------------------------------------------------------------- #
def _default_image_model() -> str:
    configured = (os.environ.get("DESIGN_IMAGE_MODEL") or "").strip()
    if configured:
        return configured
    from app.domains.gateway.media_catalog import image_models

    models = sorted(image_models(), key=lambda m: m.price_micros)
    if not models:
        raise DesignError("no image model is configured on this server", status_code=503)
    return models[0].id


def ai_image(user_id: str, doc_id: str, *, prompt: str, model: str = "",
             create: Callable[..., dict] | None = None, fetch: Callable[[str], bytes] | None = None) -> dict:
    """Generate an image through the media gateway (charged to the wallet) and store it for the canvas."""
    _require_ready()
    prompt = " ".join((prompt or "").split())
    if len(prompt) < 3:
        raise DesignError("describe the image in a few words")
    with get_session() as session:  # type: ignore[misc]
        _get(session, user_id, doc_id)
        if create is None:
            from app.domains.gateway import media_gateway as gw

            try:
                result = gw.create_image(session, user_id=user_id, model=model or _default_image_model(),
                                         prompt=prompt[:2000])
            except gw.GatewayError as exc:
                raise DesignError(str(exc), status_code=exc.status_code) from exc
        else:
            result = create(session, user_id=user_id, model=model or "test-model", prompt=prompt)
    url = str(result.get("url") or "")
    if not url:
        raise DesignError("the image model returned no image", status_code=502)
    norm = normalize_image((fetch or _fetch_remote)(url), keep_alpha=False)
    with get_session() as session:  # type: ignore[misc]
        stored = _store_image(session, user_id, norm, source="design_ai",
                              extra={"generation_id": result.get("id"), "model": result.get("model")})
        row = _get(session, user_id, doc_id)
        row.used_ai_image = True
        session.flush()
    return {**stored, "cost_micros": int(result.get("cost_micros") or 0), "model": result.get("model")}


# --------------------------------------------------------------------------- #
# Schedule -> approvals feed
# --------------------------------------------------------------------------- #
def schedule(user_id: str, doc_id: str, *, platforms: list[str], caption: str = "",
             scheduled_at: datetime | None = None, now: datetime | None = None,
             channel_ids: list[str] | None = None) -> dict:
    """Queue the exported images as a ``design_publish`` approval item (nothing is posted here).

    Approving the item schedules one image post per platform through the
    extended publish connectors (:mod:`app.domains.approvals.producers`).
    """
    _require_ready()
    moment = now or _utcnow()
    wanted = list(dict.fromkeys(p.strip().lower() for p in platforms if p and p.strip()))
    if not wanted:
        raise DesignError("choose at least one place to post")
    unknown = [p for p in wanted if p not in PLATFORMS]
    if unknown:
        raise DesignError(f"unsupported platform: {', '.join(unknown)}")
    when = scheduled_at or moment
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if when < moment - timedelta(minutes=5):
        raise DesignError("the scheduled time is in the past")
    if when > moment + MAX_SCHEDULE_AHEAD:
        raise DesignError("schedule at most a year ahead")
    from app.domains.approvals.models import RISK_MEDIUM, SOURCE_DESIGN_PUBLISH
    from app.domains.approvals.service import enqueue

    with get_session() as session:  # type: ignore[misc]
        row = _get(session, user_id, doc_id)
        keys = list(row.exported_keys or [])
        if not keys:
            raise DesignError("export the design before scheduling it", status_code=409)
        caption = (caption or "").strip()[:2200]
        item = enqueue(
            user_id, SOURCE_DESIGN_PUBLISH, row.id, session=session,
            title=f"Post design \"{row.title}\" to {', '.join(wanted)}"[:300],
            summary=(caption or "No caption")[:1000], risk=RISK_MEDIUM,
            payload={
                "design_id": row.id, "design_title": row.title, "size_preset": row.size_preset,
                "image_keys": keys, "platforms": wanted, "caption": caption, "scheduled_at": when.isoformat(),
                "channel_ids": [str(c)[:32] for c in (channel_ids or []) if str(c or "").strip()][:12],
                "open_path": f"/studio/design/{row.id}", "editable_fields": ["caption"],
            },
        )
        row.status = STATUS_SCHEDULED
        session.flush()
        return {"design": doc_view(row), "approval": item}


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
def list_templates(user_id: str) -> dict:
    _require_ready()
    builtin = [{"id": None, "slug": t.slug, "name": t.name, "description": t.description,
                "presets": list(t.presets) or sorted(SIZE_PRESETS), "builtin": True} for t in layouts.TEMPLATES.values()]
    with get_session() as session:  # type: ignore[misc]
        rows = session.execute(
            select(DesignTemplate).where(DesignTemplate.user_id == user_id, DesignTemplate.is_active.is_(True))
            .order_by(DesignTemplate.created_at.desc()).limit(100)
        ).scalars().all()
        saved = [{"id": r.id, "slug": r.slug, "name": r.name, "description": "", "presets": [r.size_preset],
                  "category": r.category, "builtin": False} for r in rows]
    sizes = [{"id": k, "width": w, "height": h} for k, (w, h) in SIZE_PRESETS.items()]
    return {"sizes": sizes, "templates": builtin + saved}


def save_template(user_id: str, doc_id: str, *, name: str) -> dict:
    _require_ready()
    name = (name or "").strip()[:200]
    if not name:
        raise DesignError("name the template")
    with get_session() as session:  # type: ignore[misc]
        row = _get(session, user_id, doc_id)
        tpl = DesignTemplate(user_id=user_id, slug=f"u-{uuid.uuid4().hex[:20]}", name=name,
                             size_preset=row.size_preset, category="post", layout_json=dict(row.canvas_json or {}))
        session.add(tpl)
        session.flush()
        return {"id": tpl.id, "slug": tpl.slug, "name": tpl.name, "presets": [tpl.size_preset], "builtin": False}


def delete_template(user_id: str, template_id: str) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        tpl = session.get(DesignTemplate, template_id)
        if tpl is None or tpl.user_id != user_id:
            raise DesignError("template not found", status_code=404)
        tpl.is_active = False
    return {"deleted": True, "id": template_id}


def brand_kits(user_id: str) -> dict:
    """The caller's kits with the style each one produces (for the kit picker)."""
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        out = []
        for kit in _kits(session, user_id):
            block = (kit.config or {}).get("brand")
            brand = dict(block) if isinstance(block, dict) else {}
            style = style_from_brand(brand)
            out.append({"id": kit.id, "name": kit.name, "has_brand": bool(brand),
                        "logo_url": str(brand.get("logo_url") or "") or None,
                        **{k: v for k, v in _brand_summary(brand, style, kit.id).items() if k in ("colors", "fonts")}})
    return {"kits": out}


__all__ = [
    "DesignError",
    "ai_image",
    "brand_kits",
    "create_doc",
    "delete_doc",
    "delete_template",
    "duplicate_doc",
    "export",
    "generate",
    "get_doc",
    "list_docs",
    "list_templates",
    "media",
    "save_template",
    "schedule",
    "style_from_brand",
    "update_doc",
    "upload_image",
]
