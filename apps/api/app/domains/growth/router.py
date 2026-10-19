"""Growth HTTP facade — Jev-powered Winning Hook Ranker (P-growth).

DB-free router over :mod:`app.domains.growth.hook_ranker`: a creator submits N
candidate hooks/captions for one reel or campaign and gets them ranked by a
Jev-scored, code-combined composite, plus the winner, per-variant signals, and the
recommended angle. Persists nothing. MPT envelope + :class:`HttpException`.

Env-gated on ``TYPESAFE_API_KEY``: when unset the endpoint still responds 200 with
``degraded: true`` (input order preserved, no AI scoring) rather than failing.

Every call spends TypeSafe/Jev credits, so the route requires an authenticated
principal (Supabase/Clerk bearer or ``x-api-key`` via :func:`resolve_principal`)
and applies a per-user hourly rate limit. Auth runs as a dependency, so an
unauthenticated caller gets 401 before the body is even validated.
"""

from __future__ import annotations

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.growth.hook_ranker import (
    HookContext,
    HookRanking,
    HookSignals,
    HookVariant,
    rank_hooks,
)
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

# Each ranking fans out one Jev call per variant (up to 25), so cap per-user
# volume. 60 rankings/hour is far above a creator iterating on hooks by hand.
RANK_HOOKS_LIMIT_PER_HOUR = 60
_HOUR_S = 3600


class HookVariantIn(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)


class RankHooksBody(BaseModel):
    variants: list[HookVariantIn] = Field(min_length=1, max_length=25)
    topic: str = Field(default="", max_length=500)
    platform: str = Field(default="", max_length=60)
    audience: str = Field(default="", max_length=500)
    brand_voice: str = Field(default="", max_length=500)


def _signals_to_dict(s: HookSignals) -> dict:
    return {
        "id": s.id,
        "text": s.text,
        "primary_angle": s.primary_angle,
        "angle_confidence": round(s.angle_confidence, 4),
        "hook_strength": round(s.hook_strength, 4),
        "is_slop": round(s.is_slop, 4),
        "is_policy_risk": round(s.is_policy_risk, 4),
        "composite": round(s.composite, 4),
        "scored": s.scored,
        "angle_probabilities": {k: round(v, 4) for k, v in s.angle_probabilities.items()},
    }


def _ranking_to_dict(result: HookRanking) -> dict:
    return {
        "ranked": [_signals_to_dict(s) for s in result.ranked],
        "winner": _signals_to_dict(result.winner) if result.winner else None,
        "recommended_angle": result.recommended_angle,
        "degraded": result.degraded,
        "note": result.note,
    }


def rank_hooks_caller(request: Request) -> str:
    """Authenticate the caller and consume one unit of their rank-hooks budget.

    Raises 401 (no/invalid credential), 503 (persistence unavailable) or 429
    (hourly budget exhausted). Returns the principal's user id.
    """
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        user_id = str(resolve_principal(request, session, request_id).id)
    enforce_rate_limit(
        request,
        f"growth:rank-hooks:{user_id}",
        limit=RANK_HOOKS_LIMIT_PER_HOUR,
        window_s=_HOUR_S,
    )
    return user_id


@router.post("/growth/rank-hooks", summary="Rank reel hook variants with Jev")
async def rank_hooks_route(
    request: Request,
    body: RankHooksBody,
    _user_id: str = Depends(rank_hooks_caller),
):
    """Score + rank candidate hooks/captions for one reel by Jev composite.

    One batched Jev call per variant (choice + score + two nouls run in parallel);
    the composite is combined in code. Returns the ranked variants, the winner, the
    per-variant signals and the recommended angle. Degrades to pass-through (200,
    ``degraded: true``) when ``TYPESAFE_API_KEY`` is not configured. Requires an
    authenticated caller and is rate-limited per user (see :func:`rank_hooks_caller`).
    """
    request_id = base.get_task_id(request)

    # Duplicate ids would make the ranking ambiguous — fail fast at the boundary.
    seen: set[str] = set()
    for v in body.variants:
        if v.id in seen:
            raise HttpException(
                task_id=request_id,
                status_code=422,
                message=f"{request_id}: duplicate variant id {v.id!r}",
            )
        seen.add(v.id)

    variants = [HookVariant(id=v.id, text=v.text) for v in body.variants]
    context = HookContext(
        topic=body.topic,
        platform=body.platform,
        audience=body.audience,
        brand_voice=body.brand_voice,
    )
    result = await rank_hooks(variants, context)
    return utils.get_response(200, _ranking_to_dict(result))
