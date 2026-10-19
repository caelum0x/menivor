"""Skills: reusable agent recipes. Built-ins live here; users can add their own."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.domains.adstudio.extract import clean_text
from app.domains.brand_agent import copy_rules
from app.domains.brand_agent.models import AgentSkill

MAX_CUSTOM = 50

BUILTIN: tuple[dict[str, Any], ...] = (
    {"id": "ugc_script", "name": "UGC script", "prompt": "Write a 30 second UGC script",
     "description": "A talking-head script in your brand voice, hook first.", "spends_credits": False},
    {"id": "hook_variations", "name": "Hook variations", "prompt": "Write 5 hooks for TikTok",
     "description": "Scroll-stopping first lines from your positioning and audience pains.",
     "spends_credits": False},
    {"id": "ad_clone", "name": "Ad clone", "prompt": "Clone this ad: ",
     "description": "Rebuild a winning ad from a TikTok or Meta link for your brand.", "spends_credits": True},
    {"id": "ad_variations", "name": "Ad variations", "prompt": "Make 3 new ad variations",
     "description": "New image ads that keep your colors and message.", "spends_credits": True},
    {"id": "image_ad", "name": "Image ad", "prompt": "Make an image ad",
     "description": "One static ad from your brand memory.", "spends_credits": True},
    {"id": "video_ad", "name": "Video ad", "prompt": "Make a 15s video ad",
     "description": "A short vertical video ad from your brand memory.", "spends_credits": True},
)
BUILTIN_IDS = frozenset(s["id"] for s in BUILTIN)


class SkillError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _custom_view(row: AgentSkill) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "prompt": row.instructions, "description": row.instructions[:160],
            "spends_credits": False, "builtin": False}


def list_skills(session: Any, user_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(AgentSkill).where(AgentSkill.user_id == user_id).order_by(AgentSkill.created_at)
    ).scalars().all()
    return [*({**s, "builtin": True} for s in BUILTIN), *(_custom_view(r) for r in rows)]


def create(session: Any, user_id: str, *, name: str, instructions: str) -> dict[str, Any]:
    title = clean_text(name, 120)
    body = copy_rules.scrub(clean_text(instructions, 4000))
    if not title or not body:
        raise SkillError("A skill needs a name and instructions.", 422)
    count = len(list_skills(session, user_id)) - len(BUILTIN)
    if count >= MAX_CUSTOM:
        raise SkillError(f"You can have up to {MAX_CUSTOM} custom skills.")
    row = AgentSkill(user_id=user_id, name=title, instructions=body)
    session.add(row)
    session.flush()
    return _custom_view(row)


__all__ = ["BUILTIN", "BUILTIN_IDS", "SkillError", "create", "list_skills"]
