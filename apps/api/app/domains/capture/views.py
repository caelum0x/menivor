"""Response projections for captures (presigned media URLs, no secrets)."""

from __future__ import annotations

from typing import Any

from app.domains.capture.ads import draft_script
from app.domains.capture.models import STATUS_SUCCEEDED


def r2_client() -> Any:
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


def _title(job: Any) -> str:
    meta = job.meta or {}
    listing = meta.get("listing") or {}
    page = meta.get("page") or {}
    return str(listing.get("title") or page.get("title") or "")[:200]


def capture_summary(job: Any, r2: Any = None) -> dict[str, Any]:
    outputs = (job.meta or {}).get("outputs") or []
    poster = next((o.get("poster_key") for o in outputs if o.get("poster_key")), "")
    return {
        "id": job.id,
        "source_url": job.source_url,
        "source_kind": job.source_kind,
        "status": job.status,
        "progress": int(job.progress or 0),
        "title": _title(job),
        "formats": list((job.options or {}).get("formats") or []),
        "poster_url": _presign(r2, str(poster or "")),
        "error": job.error or None,
        "created_at": _iso(job.created_at),
        "finished_at": _iso(job.finished_at),
    }


def capture_detail(job: Any, r2: Any = None) -> dict[str, Any]:
    r2 = r2 if r2 is not None else r2_client()
    meta = job.meta or {}
    stem = f"capture-{job.id[:8]}"
    outputs = []
    for output in meta.get("outputs") or []:
        aspect = str(output.get("aspect") or "")
        key = str(output.get("key") or "")
        outputs.append({
            "aspect": aspect,
            "key": key,
            "duration_ms": int(output.get("duration_ms") or 0),
            "video_url": _presign(r2, key),
            "download_url": _presign(r2, key, download_name=f"{stem}-{aspect.replace(':', 'x')}.mp4"),
            "poster_url": _presign(r2, str(output.get("poster_key") or "")),
        })
    screenshots = [
        {**{k: s.get(k) for k in ("key", "width", "height", "label")}, "url": _presign(r2, str(s.get("key") or ""))}
        for s in (job.screenshots or [])
        if isinstance(s, dict)
    ]
    listing = dict(meta.get("listing") or {})
    view = {
        **capture_summary(job, r2),
        "options": {k: v for k, v in (job.options or {}).items() if k != "ref"},
        "outputs": outputs,
        "screenshots": screenshots,
        "listing": listing or None,
        "page": meta.get("page") or None,
        "capture_mode": meta.get("capture_mode") or None,
        "started_at": _iso(job.started_at),
    }
    if job.status == STATUS_SUCCEEDED:
        view["script_draft"] = draft_script(job)
    return view


__all__ = ["capture_detail", "capture_summary", "r2_client"]
