"""Default runners per render kind (real engines; tests pass their own runners)."""

from __future__ import annotations

from app.domains.studio_render import service
from app.domains.studio_render.models import KIND_ACTOR_SHOT, KIND_LIPSYNC


def register_defaults() -> None:
    from app.domains.actors.render import run_product_shot
    from app.domains.lipsync_translate.pipeline import run_plan

    service.RUNNERS.setdefault(KIND_ACTOR_SHOT, run_product_shot)
    service.RUNNERS.setdefault(KIND_LIPSYNC, run_plan)


__all__ = ["register_defaults"]
