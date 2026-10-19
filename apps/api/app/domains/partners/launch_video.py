"""Launch video for Scribase and Rally users (MR8), Menivor side of contract 5.1.

``POST /api/v1/partners/launch-video`` (signed in to Menivor). Body: the
partner ``token`` (from the Scribase connect page or a redirect, never pasted)
plus the ``app_url`` and ``app_name`` the redirect carried. A valid token
(``aud=menivor``, ``cap=launch-video``, not expired, not revoked) returns a
draft brief and the ``/create`` link that pre-fills it; the account's first
touch is recorded as ``source=scribase`` (or ``rally``) for the funnel
read-out (M-4).

Only what the user typed crosses products: their Menivor sign-up email is
their own, and the app URL and name are what they entered in the partner
product. The token's project and org ids are checked, never stored. The
first reel follows live pricing (the normal card check, then plans or packs);
nothing here grants credits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import Body, Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.partners import scribase_tokens
from app.models.exception import HttpException
from app.utils import utils

router = new_router()

AUDIENCE = "menivor"
CAPABILITY = "launch-video"
CAMPAIGN = "launch-video"
PARTNER_SOURCES = ("scribase", "rally")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class LaunchVideoRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=4096)
    app_url: str = Field("", max_length=500)
    app_name: str = Field("", max_length=80)
    source: str = Field("scribase", max_length=20)


@dataclass(frozen=True)
class DraftBrief:
    app_url: str
    app_name: str
    topic: str
    create_url: str
    source: str
    #: Wave P PM1.5 (contract 5.4): the Scribase add-on's monthly reel, when the token carries it.
    grant: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "app_url": self.app_url,
            "app_name": self.app_name,
            "topic": self.topic,
            "create_url": self.create_url,
            "source": self.source,
        }
        if self.grant is not None:
            data["grant"] = dict(self.grant)
        return data


def clean_app_url(raw: str) -> str:
    """An https (or http) URL with a host, or ``""``."""
    value = _CONTROL.sub("", str(raw or "")).strip()
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ValueError("app_url must be an http(s) link")
    return value[:500]


def clean_app_name(raw: str) -> str:
    return re.sub(r"\s+", " ", _CONTROL.sub("", str(raw or ""))).strip()[:80]


def draft_brief(app_url: str, app_name: str, source: str) -> DraftBrief:
    url = clean_app_url(app_url)
    name = clean_app_name(app_name)
    if not url and not name:
        raise ValueError("an app link or name is needed for the launch video")
    topic = f"Launch video for {name}" if name else "Launch video for my app"
    seed = url or topic
    return DraftBrief(
        app_url=url,
        app_name=name,
        topic=topic,
        create_url=f"/create?q={quote(seed, safe='')}",
        source=source,
    )


def _with_grant(session: Any, brief: DraftBrief, claims: Any, user_id: str) -> DraftBrief:
    """Redeem the Scribase add-on's monthly reel (contract 5.4); the brief says what happened."""
    from dataclasses import replace

    from app.integrations.railyard import grants

    try:
        redeemed = grants.redeem(session, claims, user_id=str(user_id))
    except grants.GrantExhausted as exc:
        return replace(brief, grant={"reels": 0, "message": exc.message, "upgrade_url": exc.upgrade_url})
    except grants.GrantInvalid:
        return brief
    if redeemed is None:
        return brief
    return replace(brief, grant={"reels": redeemed["reels"], "period": redeemed["period"],
                                 "message": "Your first reel is included with your Scribase add-on."})


def start_launch_video(
    session: Any,
    *,
    user_id: str,
    token: str,
    app_url: str,
    app_name: str,
    source: str = "scribase",
    verifier: scribase_tokens.ScribaseTokenVerifier | None = None,
) -> DraftBrief:
    """Verify the partner token, record the source once, return the draft brief."""
    from app.domains.funnel_readout.service import record_attribution
    from app.services import audit

    partner = str(source or "scribase").strip().lower()
    if partner not in PARTNER_SOURCES:
        raise ValueError("unknown partner")
    claims = (verifier or scribase_tokens.default_verifier()).verify(
        token, audience=AUDIENCE, capability=CAPABILITY
    )
    brief = draft_brief(app_url, app_name, partner)
    brief = _with_grant(session, brief, claims, user_id)
    record_attribution(session, user_id, source=partner, utm_source=partner, utm_campaign=CAMPAIGN)
    audit.record(
        session,
        actor_user_id=str(user_id),
        action="partner.launch_video_draft",
        target_type="partner_token",
        target_id=claims.jti[:64],
        metadata={"source": partner, "app_url": brief.app_url, "app_name": brief.app_name},
    )
    return brief


@router.post("/partners/launch-video", summary="Start a launch video from a partner link")
def partner_launch_video(request: Request, body: LaunchVideoRequest = Body(...)) -> Any:
    from app.services.ratelimit import enforce_rate_limit

    request_id = base.get_task_id(request)
    enforce_rate_limit(request, "partners:launch-video", 20, 3600)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            brief = start_launch_video(
                session,
                user_id=str(user.id),
                token=body.token,
                app_url=body.app_url,
                app_name=body.app_name,
                source=body.source,
            )
        except scribase_tokens.PartnerTokenError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=exc.status_code,
                message=f"{request_id}: {exc.message}",
                data={"code": exc.code},
            ) from exc
        except ValueError as exc:
            raise HttpException(task_id=request_id, status_code=422, message=f"{request_id}: {exc}") from exc
    return utils.get_response(200, brief.as_dict())


__all__ = ["router", "start_launch_video", "draft_brief"]
