"""AI actors: presets + the user's own synthetic actors, face and voice with provenance.

* A face is never uploaded. It is generated from the actor's look prompt by a Brand
  Agent image action (approval first, like every spend), and only an image made for
  this actor can become its face; provenance records which generation made it.
* A voice is designed from the voice prompt with ElevenLabs Voice Design (text only,
  no reference audio) and locked as the actor's voice id.
* Every write passes the likeness guard; creating an actor needs the synthetic-person
  attestation, stored as the consent record.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.domains.actors import likeness_guard, presets
from app.domains.actors.models import AiActor
from app.domains.adstudio.extract import clean_text

MAX_ACTORS = 50
CONSENT_TYPE = "synthetic_no_real_person"
STATUS_DRAFT, STATUS_READY = "draft", "ready"
FACE_SUFFIX = ", head and shoulders portrait, looking at the camera, neutral background"


class ActorError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def view(row: AiActor) -> dict[str, Any]:
    return {
        "id": row.id, "slug": (row.provenance or {}).get("preset", ""), "name": row.name, "persona": row.persona,
        "look_prompt": row.look_prompt, "voice_design_prompt": row.voice_design_prompt,
        "product_shot_template": row.product_shot_template, "face_image_url": row.face_image_url,
        "voice_id": row.voice_id, "builtin": False, "status": row.status, "provenance": dict(row.provenance or {}),
        "consent": dict(row.consent or {}), "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _template(text: str) -> str:
    value = clean_text(text, 2000)
    if not value:
        return "Vertical 9:16 UGC selfie video. The person holds {product} toward the camera and smiles."
    return value if "{product}" in value else f"{value} Holding {{product}} toward the camera."


def list_actors(session: Any, user_id: str) -> dict[str, Any]:
    rows = session.execute(select(AiActor).where(AiActor.user_id == user_id)
                           .order_by(AiActor.created_at.desc())).scalars().all()
    return {"presets": presets.all_presets(), "mine": [view(r) for r in rows],
            "rules": ["Original synthetic people only: no real person's face, name or voice.",
                      "Faces are generated from the look prompt, never uploaded.",
                      "Voices are designed from a text prompt, never cloned."]}


def _guard(**fields: str) -> None:
    try:
        likeness_guard.enforce(**fields)
    except likeness_guard.LikenessError as exc:
        raise ActorError(exc.message, 422) from exc


def _count(session: Any, user_id: str) -> int:
    return int(session.execute(select(func.count()).select_from(AiActor).where(AiActor.user_id == user_id)).scalar() or 0)


def create(session: Any, user_id: str, *, name: str, persona: str = "", look_prompt: str, voice_design_prompt: str,
           product_shot_template: str = "", attest_synthetic: bool = False,
           workspace_id: str | None = None) -> dict[str, Any]:
    if not attest_synthetic:
        raise ActorError("Confirm this actor is an original, synthetic person (no real person's likeness).", 422)
    title, look, voice = clean_text(name, 80), clean_text(look_prompt, 2000), clean_text(voice_design_prompt, 1000)
    if not title or not look or not voice:
        raise ActorError("Give the actor a name, a look and a voice.", 422)
    template = _template(product_shot_template)
    _guard(name=title, persona=clean_text(persona, 1000), look_prompt=look, voice_prompt=voice, shot_template=template)
    if _count(session, user_id) >= MAX_ACTORS:
        raise ActorError(f"You can keep up to {MAX_ACTORS} actors.")
    row = AiActor(user_id=user_id, workspace_id=workspace_id, name=title, persona=clean_text(persona, 1000),
                  look_prompt=look, voice_design_prompt=voice, product_shot_template=template, status=STATUS_DRAFT,
                  provenance={"synthetic": True, "generator": "user-defined", "face": "not generated yet"},
                  consent={"type": CONSENT_TYPE, "attested_by": user_id, "attested_at": _now()})
    session.add(row)
    session.flush()
    return view(row)


def use_preset(session: Any, user_id: str, slug: str) -> dict[str, Any]:
    preset = presets.get(slug)
    if preset is None:
        raise ActorError("actor preset not found", 404)
    for row in session.execute(select(AiActor).where(AiActor.user_id == user_id)).scalars():
        if (row.provenance or {}).get("preset") == slug:
            return view(row)
    if _count(session, user_id) >= MAX_ACTORS:
        raise ActorError(f"You can keep up to {MAX_ACTORS} actors.")
    row = AiActor(user_id=user_id, name=preset["name"], persona=preset["persona"], look_prompt=preset["look_prompt"],
                  voice_design_prompt=preset["voice_design_prompt"],
                  product_shot_template=preset["product_shot_template"], status=STATUS_DRAFT,
                  provenance={**preset["provenance"], "preset": slug}, consent=dict(preset["consent"]))
    session.add(row)
    session.flush()
    return view(row)


def get(session: Any, user_id: str, actor_id: str) -> AiActor:
    row = session.get(AiActor, actor_id) if actor_id else None
    if row is None or row.user_id != user_id:
        raise ActorError("actor not found", 404)
    return row


def delete(session: Any, user_id: str, actor_id: str) -> None:
    session.delete(get(session, user_id, actor_id))
    session.flush()


def propose_face(session: Any, user_id: str, actor_id: str, *, space_id: str | None = None) -> dict[str, Any]:
    """A pending Brand Agent image action that generates this actor's face from its look prompt."""
    from app.domains.brand_agent import gate, spaces

    row = get(session, user_id, actor_id)
    space = spaces.resolve(session, user_id, space_id)
    return gate.propose(session, user_id, space.id, None, kind=gate.KIND_IMAGE, title=f"Face for {row.name}",
                        payload={"prompt": row.look_prompt + FACE_SUFFIX, "actor_id": row.id,
                                 "options": {"aspect": "1:1"}})


def use_face(session: Any, user_id: str, actor_id: str, library_item_id: str) -> dict[str, Any]:
    """Set the face from an image generated for this actor (never an upload)."""
    from app.domains.brand_agent.models import AgentAction, AgentLibraryItem

    row = get(session, user_id, actor_id)
    item = session.get(AgentLibraryItem, library_item_id) if library_item_id else None
    if item is None or item.user_id != user_id or item.kind != "image" or not item.url.startswith("https://"):
        raise ActorError("Pick an image Menivor generated for this actor.", 422)
    action = session.get(AgentAction, item.action_id) if item.action_id else None
    if action is None or (action.payload or {}).get("actor_id") != row.id:
        raise ActorError("Only a face generated from this actor's look prompt can be used.", 422)
    row.face_image_url = item.url
    row.provenance = {**dict(row.provenance or {}), "synthetic": True, "face": "generated",
                      "face_generator": "menivor-media-gateway", "face_prompt": str(action.payload.get("prompt", "")),
                      "face_library_item_id": item.id, "face_action_id": action.id, "face_ref": item.ref,
                      "face_set_at": _now()}
    row.status = STATUS_READY
    session.flush()
    return view(row)


def design_voice(session: Any, user_id: str, actor_id: str, client: Any, description: str = "") -> dict[str, Any]:
    row = get(session, user_id, actor_id)
    prompt = clean_text(description, 1000) or row.voice_design_prompt
    _guard(voice_prompt=prompt)
    from app.domains.adclone.elevenlabs import ElevenLabsError

    try:
        previews = client.design(prompt)
    except ElevenLabsError as exc:
        raise ActorError(str(exc), getattr(exc, "status_code", 502)) from exc
    return {"actor_id": row.id, "prompt": prompt, "previews": previews}


def lock_voice(session: Any, user_id: str, actor_id: str, client: Any, generated_voice_id: str) -> dict[str, Any]:
    from app.domains.adclone.elevenlabs import ElevenLabsError

    row = get(session, user_id, actor_id)
    try:
        voice_id = client.save(name=f"Menivor actor {row.name}"[:60], description=row.voice_design_prompt,
                               generated_voice_id=generated_voice_id)
    except ElevenLabsError as exc:
        raise ActorError(str(exc), getattr(exc, "status_code", 502)) from exc
    row.voice_id = str(voice_id)[:80]
    row.provenance = {**dict(row.provenance or {}), "voice": "designed", "voice_generator": "elevenlabs-voice-design",
                      "voice_designed_from": "text prompt (no reference audio)", "voice_set_at": _now()}
    session.flush()
    return view(row)


def designed_voice_owner(session: Any, user_id: str, voice_id: str) -> AiActor | None:
    """The user's actor that owns this designed voice id (lip-sync translation uses only these)."""
    if not voice_id:
        return None
    return session.execute(select(AiActor).where(AiActor.user_id == user_id, AiActor.voice_id == voice_id)
                           ).scalars().first()


__all__ = ["ActorError", "create", "delete", "design_voice", "designed_voice_owner", "get", "list_actors",
           "lock_voice", "propose_face", "use_face", "use_preset", "view"]
