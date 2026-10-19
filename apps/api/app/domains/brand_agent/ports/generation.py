"""Generation port: images and videos through Menivor's existing media gateway.

``generate(*, session, user_id, kind, prompt, options) -> dict`` with ``kind`` in
``{"image", "video"}``. The default :class:`GatewayGeneration` calls
``media_gateway.create_image`` / ``create_video``, which reserve the wallet and
refund on failure (success-only billing). The agent calls it only after the user
approved the action. Models: ``BRAND_AGENT_IMAGE_MODEL`` / ``BRAND_AGENT_VIDEO_MODEL``
or the first model in the gateway catalog.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from .base import PortUnavailable

KINDS = frozenset({"image", "video"})


class GenerationPort(Protocol):
    def generate(self, *, session: Any, user_id: str, kind: str, prompt: str,
                 options: dict[str, Any]) -> dict[str, Any]: ...


def _model(kind: str, requested: str = "") -> str:
    from app.domains.gateway.media_catalog import image_models, video_models

    wanted = requested or os.environ.get(f"BRAND_AGENT_{kind.upper()}_MODEL", "")
    models = image_models() if kind == "image" else video_models()
    ids = [m.id for m in models]
    if wanted and wanted in ids:
        return wanted
    if not ids:
        raise PortUnavailable(f"No {kind} model is set up on this server yet.")
    return ids[0]


class GatewayGeneration:
    def preflight(self, kind: str, options: dict[str, Any] | None = None) -> str:
        """"" when a model for ``kind`` is set up; else the plain reason (checked before Approve)."""
        try:
            _model(kind, str((options or {}).get("model") or ""))
        except PortUnavailable as exc:
            return exc.reason
        except Exception:  # noqa: BLE001 - catalog unreadable: let the run report it
            return ""
        return ""

    def generate(self, *, session: Any, user_id: str, kind: str, prompt: str,
                 options: dict[str, Any]) -> dict[str, Any]:
        from app.domains.gateway import media_gateway as gw

        if kind not in KINDS:
            raise PortUnavailable(f"Unknown generation kind: {kind}")
        model = _model(kind, str(options.get("model") or ""))
        try:
            if kind == "image":
                result = gw.create_image(session, user_id=user_id, model=model, prompt=prompt)
                return {"kind": kind, "ref": str(result.get("id") or result.get("job_id") or ""),
                        "url": str(result.get("url") or result.get("image_url") or ""), "status": "completed",
                        "model": model}
            row = gw.create_video(session, user_id=user_id, model=model, prompt=prompt,
                                  duration=int(options.get("duration") or 5),
                                  aspect_ratio=str(options.get("aspect_ratio") or "9:16"))
        except gw.GatewayError as exc:
            raise PortUnavailable(str(exc)) from exc
        return {"kind": kind, "ref": str(getattr(row, "id", "")), "url": "", "status": "submitted", "model": model}


def get_port() -> GenerationPort:
    return GatewayGeneration()


__all__ = ["GatewayGeneration", "GenerationPort", "KINDS", "get_port"]
