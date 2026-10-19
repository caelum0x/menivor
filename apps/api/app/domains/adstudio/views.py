"""Response projections for Ad Studio (presigned media URLs, no secrets)."""

from __future__ import annotations

import re
from typing import Any

from app.domains.adstudio.angles import LABELS

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FORMAT_LABELS = {
    "en": {"showcase": "Product showcase", "before_after": "Before / after", "ugc_avatar": "UGC avatar"},
    "tr": {"showcase": "Ürün vitrini", "before_after": "Önce / sonra", "ugc_avatar": "UGC avatar"},
}


def _r2() -> Any:
    try:
        from app.platform.storage.r2 import get_r2_client

        return get_r2_client()
    except Exception:  # noqa: BLE001 - reads never fail on storage config
        return None


def _presign(r2: Any, key: str, download_name: str | None = None) -> str | None:
    if r2 is None or not key:
        return None
    try:
        return r2.presign_result_get(key, download_name=download_name)
    except Exception:  # noqa: BLE001 - a read never fails on one presign
        return None


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def slug(text: str) -> str:
    folded = (text or "").lower().translate(str.maketrans("çğıöşü", "cgiosu"))
    return (_SLUG_RE.sub("-", folded).strip("-") or "ad")[:48]


def project_summary(project: Any, counts: dict[str, int] | None = None, r2: Any = None) -> dict[str, Any]:
    first = (project.images or [{}])[0] if project.images else {}
    return {
        "id": project.id,
        "title": project.title,
        "source": project.source,
        "source_url": project.source_url or None,
        "language": project.language,
        "angle_count": len(project.angles or []),
        "variant_count": (counts or {}).get("total", 0),
        "done_count": (counts or {}).get("done", 0),
        "thumbnail_url": _presign(r2, str(first.get("key") or "")) if first else None,
        "created_at": _iso(project.created_at),
        "updated_at": _iso(project.updated_at),
    }


def _angle_label(project: Any, angle_id: str) -> str:
    for angle in project.angles or []:
        if angle.get("id") == angle_id:
            return str(angle.get("label") or angle.get("kind") or angle_id)
    return angle_id


def _test_fields(variant: Any) -> dict[str, Any]:
    """The ad's hook plus its "Publish and test" / remake lineage (from ``spec``)."""
    spec = variant.spec or {}
    angle = spec.get("angle") if isinstance(spec.get("angle"), dict) else {}
    test = spec.get("publish_test") if isinstance(spec.get("publish_test"), dict) else {}
    remake = spec.get("remake_of") if isinstance(spec.get("remake_of"), dict) else {}
    return {
        "hook": str(angle.get("hook") or ""),
        "test_batch_id": str(test.get("batch_id") or "") or None,
        "remake_of": str(remake.get("variant_id") or "") or None,
    }


def variant_view(project: Any, variant: Any, jobs: dict[str, Any], r2: Any) -> dict[str, Any]:
    language = project.language if project.language in _FORMAT_LABELS else "en"
    name = f"{slug(project.title)}-{variant.format}-{variant.aspect.replace(':', 'x')}-{variant.angle_id}"
    view: dict[str, Any] = {
        "id": variant.id,
        "angle_id": variant.angle_id,
        "angle_label": _angle_label(project, variant.angle_id),
        "format": variant.format,
        "format_label": _FORMAT_LABELS[language].get(variant.format, variant.format),
        "aspect": variant.aspect,
        "status": variant.status,
        "error": variant.error or None,
        "script": variant.script,
        "duration_s": round((variant.duration_ms or 0) / 1000, 2),
        "poster_url": _presign(r2, variant.poster_key),
        "video_url": None,
        "download_url": None,
        "filename": f"{name}.mp4",
        "job_id": variant.job_id or None,
        "job_request": None,
        "montage_url": None,
        "created_at": _iso(variant.created_at),
        **_test_fields(variant),
    }
    if variant.format == "ugc_avatar":
        view["montage_url"] = _presign(r2, variant.output_key)
        if variant.status == "ready":
            view["job_request"] = (variant.spec or {}).get("job_request")
        job = jobs.get(variant.job_id) if variant.job_id else None
        result_key = str(getattr(job, "result_key", "") or "") if job is not None else ""
        if variant.status == "done" and result_key:
            view["video_url"] = _presign(r2, result_key)
            view["download_url"] = _presign(r2, result_key, download_name=view["filename"])
    elif variant.status == "done":
        view["video_url"] = _presign(r2, variant.output_key)
        view["download_url"] = _presign(r2, variant.output_key, download_name=view["filename"])
    return view


def project_detail(project: Any, variants: list[Any], jobs: dict[str, Any]) -> dict[str, Any]:
    r2 = _r2()
    images = [
        {**{k: img.get(k) for k in ("key", "origin_url", "width", "height")}, "url": _presign(r2, str(img.get("key") or ""))}
        for img in project.images or []
        if isinstance(img, dict)
    ]
    counts = {"total": len(variants), "done": sum(1 for v in variants if v.status == "done")}
    return {
        **project_summary(project, counts, r2),
        "product": project.product or {},
        "angles": project.angles or [],
        "angle_labels": LABELS.get(project.language, LABELS["en"]),
        "images": images,
        "variants": [variant_view(project, v, jobs, r2) for v in variants],
    }


def post_caption(project: Any, angle: dict[str, Any]) -> str:
    parts = [angle.get("hook", ""), angle.get("offer", ""), angle.get("cta", "")]
    text = " ".join(p for p in parts if p)
    url = project.source_url or ""
    return f"{text}\n{url}".strip()


def export_manifest(project: Any, variants: list[Any], jobs: dict[str, Any]) -> dict[str, Any]:
    r2 = _r2()
    angles = {a.get("id"): a for a in project.angles or []}
    items = []
    for variant in variants:
        view = variant_view(project, variant, jobs, r2)
        if variant.status != "done" or not view["download_url"]:
            continue
        items.append({
            "variant_id": variant.id,
            "filename": view["filename"],
            "download_url": view["download_url"],
            "format": variant.format,
            "aspect": variant.aspect,
            "angle_label": view["angle_label"],
            "script": variant.script,
            "post_caption": post_caption(project, angles.get(variant.angle_id) or {}),
        })
    pending = sum(1 for v in variants if v.status in ("queued", "rendering", "ready", "submitted"))
    return {"project_id": project.id, "title": project.title, "items": items, "pending": pending}


__all__ = ["export_manifest", "project_detail", "project_summary", "slug", "variant_view"]
