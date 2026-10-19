"""AI actors HTTP surface (owner-scoped).

    GET    /actors                          presets + my actors + the rules
    POST   /actors                          create an original actor (attestation required)
    POST   /actors/presets/{slug}/use       copy a preset into my actors
    DELETE /actors/{id}
    POST   /actors/{id}/face                propose the face image (Brand Agent action, approval first)
    POST   /actors/{id}/face/use            set the face from an image generated for this actor
    POST   /actors/{id}/voice/design        ElevenLabs Voice Design previews from the voice prompt
    POST   /actors/{id}/voice/lock          keep one preview as the actor's designed voice
    POST   /actors/{id}/shots/plan          price a product-holding shot (planned studio render, $0)
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session
from app.domains._http import Call
from app.domains.actors import models as _models  # noqa: F401  (registers tables)
from app.domains.actors import render, service
from app.domains.brand_agent.gate import GateError
from app.domains.brand_agent.spaces import SpaceError
from app.domains.studio_render.service import RenderError
from app.utils import utils

router = new_router()
_ERRORS = (service.ActorError, GateError, SpaceError, RenderError)


def voice_client():
    from app.domains.adclone.elevenlabs import ElevenLabs

    return ElevenLabs.from_env()


def _id():
    return Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")


class ActorBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., min_length=1, max_length=80)
    persona: str = Field(default="", max_length=1000)
    look_prompt: str = Field(..., min_length=1, max_length=2000)
    voice_design_prompt: str = Field(..., min_length=1, max_length=1000)
    product_shot_template: str = Field(default="", max_length=2000)
    attest_synthetic: bool = False


class FaceBody(BaseModel):
    space_id: Optional[str] = Field(default=None, max_length=32)


class UseFaceBody(BaseModel):
    library_item_id: str = Field(..., min_length=1, max_length=32)


class VoiceDesignBody(BaseModel):
    description: str = Field(default="", max_length=1000)


class VoiceLockBody(BaseModel):
    generated_voice_id: str = Field(..., min_length=4, max_length=80)


class ShotBody(BaseModel):
    product: str = Field(..., min_length=1, max_length=200)
    first_frame_url: str = Field(default="", max_length=2000)
    seconds: float = Field(default=5, ge=1, le=10)
    aspect: Literal["9:16", "16:9", "1:1"] = "9:16"


def _call(request: Request, key: str = "") -> Call:
    return Call(request, _ERRORS, f"actors:{key}" if key else "", get_session)


@router.get("/actors", summary="AI actors: original synthetic presets and your own")
def list_actors(request: Request):
    with _call(request) as (session, user_id):
        return utils.get_response(200, service.list_actors(session, user_id))


@router.post("/actors", summary="Create an original synthetic actor (no real person's likeness)")
def create_actor(request: Request, body: ActorBody):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, {"actor": service.create(session, user_id, **body.model_dump())})


@router.post("/actors/presets/{slug}/use", summary="Add a preset actor to my actors")
def use_preset(request: Request, slug: str = Path(..., min_length=1, max_length=40, pattern=r"^[a-z0-9-]+$")):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, {"actor": service.use_preset(session, user_id, slug)})


@router.delete("/actors/{actor_id}", summary="Delete one of my actors")
def delete_actor(request: Request, actor_id: str = _id()):
    with _call(request, "write") as (session, user_id):
        service.delete(session, user_id, actor_id)
        return utils.get_response(200, {"deleted": actor_id})


@router.post("/actors/{actor_id}/face", summary="Generate the face from the look prompt (approval first)")
def propose_face(request: Request, body: Optional[FaceBody] = None, actor_id: str = _id()):
    with _call(request, "write") as (session, user_id):
        action = service.propose_face(session, user_id, actor_id, space_id=body.space_id if body else None)
        return utils.get_response(200, {"action": action})


@router.post("/actors/{actor_id}/face/use", summary="Use an image generated for this actor as its face")
def use_face(request: Request, body: UseFaceBody, actor_id: str = _id()):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, {"actor": service.use_face(session, user_id, actor_id, body.library_item_id)})


@router.post("/actors/{actor_id}/voice/design", summary="Design voice previews from the voice prompt (no cloning)")
def design_voice(request: Request, body: Optional[VoiceDesignBody] = None, actor_id: str = _id()):
    with _call(request, "voice") as (session, user_id):
        return utils.get_response(200, service.design_voice(session, user_id, actor_id, voice_client(),
                                                            body.description if body else ""))


@router.post("/actors/{actor_id}/voice/lock", summary="Keep a designed preview as the actor's voice")
def lock_voice(request: Request, body: VoiceLockBody, actor_id: str = _id()):
    with _call(request, "voice") as (session, user_id):
        return utils.get_response(200, {"actor": service.lock_voice(session, user_id, actor_id, voice_client(),
                                                                    body.generated_voice_id)})


@router.post("/actors/{actor_id}/shots/plan", summary="Price a product-holding shot (nothing is spent)")
def plan_shot(request: Request, body: ShotBody, actor_id: str = _id()):
    with _call(request, "write") as (session, user_id):
        return utils.get_response(200, {"render": render.plan_shot(session, user_id, actor_id, **body.model_dump())})


__all__ = ["router"]
