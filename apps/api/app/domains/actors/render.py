"""Product-holding shots: actor first frame + shot template -> Kling image-to-video (existing engine).

:func:`plan_shot` prices one shot and stores a ``planned`` studio render ($0).
:func:`run_product_shot` is the worker body, run only after the render was approved
in the approvals feed (credits held); the Kling client and the frame fetch are seams.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Callable, Mapping

from app.domains.actors import likeness_guard
from app.domains.actors.service import ActorError, get
from app.domains.adclone.kling import KlingClient, clip_cost, clip_seconds
from app.domains.adstudio.extract import clean_text

ASPECTS = ("9:16", "16:9", "1:1")
FRAME_MAX_BYTES = 10 * 1024 * 1024


def _library_urls(session: Any, user_id: str) -> set[str]:
    from sqlalchemy import select

    from app.domains.brand_agent.models import AgentLibraryItem

    return set(session.execute(select(AgentLibraryItem.url).where(AgentLibraryItem.user_id == user_id,
                                                                  AgentLibraryItem.kind == "image")).scalars())


def plan_shot(session: Any, user_id: str, actor_id: str, *, product: str, first_frame_url: str = "",
              seconds: float = 5, aspect: str = "9:16", env: Mapping[str, str] | None = None) -> dict[str, Any]:
    from app.domains.studio_render import service as renders
    from app.domains.studio_render.models import KIND_ACTOR_SHOT

    row = get(session, user_id, actor_id)
    name = clean_text(product, 200)
    if not name:
        raise ActorError("Name the product the actor holds.", 422)
    try:
        likeness_guard.enforce(product=name)
    except likeness_guard.LikenessError as exc:
        raise ActorError(exc.message, 422) from exc
    frame = (first_frame_url or row.face_image_url).strip()
    if not frame:
        raise ActorError("Make this actor's face first (it is the first frame of the shot).", 409)
    if frame != row.face_image_url and frame not in _library_urls(session, user_id):
        raise ActorError("The first frame must be the actor's face or an image Menivor generated for you.", 422)
    if aspect not in ASPECTS:
        raise ActorError("Pick 9:16, 16:9 or 1:1.", 422)
    e = os.environ if env is None else env
    model, res = e.get("KLING_MODEL") or "kling-v3", e.get("KLING_RESOLUTION") or "720p"
    dur = clip_seconds(float(seconds))
    usd = clip_cost(dur, model, res)
    plan = {"kind": KIND_ACTOR_SHOT, "actor_id": row.id, "actor_name": row.name, "product": name,
            "prompt": row.product_shot_template.replace("{product}", name), "first_frame_url": frame,
            "seconds": dur, "aspect": aspect, "engine": "kling", "model": model, "resolution": res, "usd": usd,
            "provenance": {"actor": dict(row.provenance or {}), "consent": dict(row.consent or {})}}
    return renders.create(session, user_id, kind=KIND_ACTOR_SHOT, title=f"{row.name} holding {name}"[:300],
                          plan=plan, quote_usd=usd)


def _fetch(url: str) -> bytes:
    from app.domains.adstudio.fetch import safe_get

    return safe_get(url, max_bytes=FRAME_MAX_BYTES, accept="image/*").body


def run_product_shot(plan: Mapping[str, Any], *, client: Any = None,
                     fetch: Callable[[str], bytes] | None = None) -> dict[str, Any]:
    image = base64.b64encode((fetch or _fetch)(str(plan["first_frame_url"]))).decode()
    kling = client or KlingClient.from_env(cap_usd=round(float(plan.get("usd") or 0) * 1.05 + 0.01, 4))
    task = kling.image_to_video(image=image, prompt=str(plan["prompt"]), seconds=float(plan["seconds"]),
                                aspect_ratio=str(plan.get("aspect") or "9:16"))
    video = kling.wait("i2v", task)
    return {"video_url": video.get("url"), "video_id": video.get("id"), "spent_usd": kling.spent_usd,
            "engine": "kling"}


__all__ = ["plan_shot", "run_product_shot"]
