"""Render output refs → durable R2 keys + browser-usable URLs.

Backends store whatever the provider handed back as ``output_refs``:

* RunPod workers may return a URL, a bare R2 key (``key`` / ``r2_key``) or — for
  ``worker-comfyui`` — inline base64 ``data`` items;
* the local ComfyUI backend returns its internal ``/view`` URL (only reachable on
  the render host's LAN);
* RocketRide returns receipt refs (URLs or keys).

This module provides two pieces:

* :func:`rehost_bytes` — upload a render artifact to a private R2 key so a durable
  key exists (used by the backends on completion; best-effort, returns ``None``
  when R2 is unavailable so the backend can fall back to its raw ref).
* :func:`output_urls` — classify every stored ref and produce the list of URLs a
  browser can actually play/download: bare keys are presigned, public ``https``
  URLs pass through, and loopback/LAN/garbage refs are dropped (reported via
  ``unusable`` so the UI can explain why a completed render has no preview).
"""

from __future__ import annotations

import ipaddress
import mimetypes
from typing import Any, Iterable
from urllib.parse import urlsplit

from loguru import logger

RENDER_OUTPUT_PREFIX = "renders"
_KEY_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./")


def rehost_bytes(job_id: str, data: bytes, filename: str, content_type: str | None = None) -> str | None:
    """Upload ``data`` to ``renders/<job_id>/<filename>`` and return the key.

    Returns ``None`` (never raises) when the payload is empty or R2 is not
    configured, so callers keep their raw ref instead of failing the render.
    """
    if not data:
        return None
    safe_job = "".join(c for c in str(job_id or "job") if c in _KEY_SAFE).strip("/.") or "job"
    safe_name = "".join(c for c in str(filename or "output.bin") if c in _KEY_SAFE).strip("/.")
    safe_name = safe_name.rsplit("/", 1)[-1] or "output.bin"
    key = f"{RENDER_OUTPUT_PREFIX}/{safe_job}/{safe_name}"
    resolved_type = content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    try:
        from app.platform.storage.r2 import get_r2_client

        return get_r2_client().upload_bytes(key, data, content_type=resolved_type)
    except Exception as exc:  # noqa: BLE001 - rehosting is best-effort
        logger.warning(f"render output rehost failed for job {job_id}: {exc}")
        return None


def _is_private_host(host: str) -> bool:
    host = (host or "").strip().lower()
    if not host or host in {"localhost", "comfyui", "host.docker.internal"}:
        return True
    if host.endswith((".local", ".internal", ".lan")):
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_unspecified


def classify_ref(ref: str) -> tuple[str, str]:
    """Return ``(kind, value)`` where kind is ``url`` | ``key`` | ``unusable``."""
    value = str(ref or "").strip()
    if not value:
        return "unusable", value
    lowered = value.lower()
    if lowered.startswith(("http://", "https://")):
        host = urlsplit(value).hostname or ""
        if _is_private_host(host):
            return "unusable", value
        return "url", value
    if lowered.startswith(("data:", "{", "[")) or "://" in value or " " in value:
        return "unusable", value
    if len(value) > 1024 or any(c not in _KEY_SAFE for c in value):
        return "unusable", value
    return "key", value.lstrip("/")


def output_urls(refs: Iterable[str], *, download_name: str | None = None) -> dict[str, Any]:
    """Resolve stored refs to presentation URLs.

    Returns ``{"output_urls": [...], "unusable_output_refs": n}``. Presign
    failures are logged and counted as unusable rather than failing the read.
    """
    urls: list[str] = []
    unusable = 0
    r2 = None
    r2_failed = False
    for ref in refs or ():
        kind, value = classify_ref(ref)
        if kind == "url":
            urls.append(value)
            continue
        if kind != "key":
            unusable += 1
            continue
        if r2 is None and not r2_failed:
            try:
                from app.platform.storage.r2 import get_r2_client

                r2 = get_r2_client()
            except Exception as exc:  # noqa: BLE001 - reads degrade without R2
                logger.warning(f"render output presign unavailable: {exc}")
                r2_failed = True
        if r2 is None:
            unusable += 1
            continue
        try:
            urls.append(r2.presign_result_get(value, download_name=download_name))
        except Exception as exc:  # noqa: BLE001 - individual URL is best-effort
            logger.warning(f"render output presign failed for {value!r}: {exc}")
            unusable += 1
    return {"output_urls": urls, "unusable_output_refs": unusable}


def first_usable_key_or_url(refs: Iterable[str]) -> tuple[str, str] | None:
    """Return the first ``(kind, value)`` that is a key or a public URL."""
    for ref in refs or ():
        kind, value = classify_ref(ref)
        if kind in ("key", "url"):
            return kind, value
    return None
