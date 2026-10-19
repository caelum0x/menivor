"""Built-in AI actors: original synthetic people written for Menivor (no real person's likeness).

Each preset carries its own look prompt (the face is generated from it, never from a
photo), a voice-design prompt (ElevenLabs Voice Design from text only) and a
product-holding shot template (``{product}`` is filled in; rendered as Kling
image-to-video from the actor's first frame). Names are invented and checked against
the real-person block-list in tests.
"""

from __future__ import annotations

from typing import Any

PROVENANCE_VERSION = "2026-10-06"
_SHOT = ("Vertical 9:16 UGC selfie video. {who} holds {product} at chest height with the label facing the camera, "
         "turns it slightly, then smiles and nods. Natural window light, handheld phone camera, real skin texture, "
         "steady hands, five fingers, no text on screen.")

_ACTORS: tuple[dict[str, str], ...] = (
    {"slug": "mira-soltane", "name": "Mira Soltane", "persona": "Late-20s product designer, calm and precise.",
     "look": "Original synthetic woman, late 20s, olive skin, dark shoulder-length wavy hair, small gold hoops, "
             "oatmeal knit sweater, bright apartment with plants",
     "voice": "Warm, clear female voice in her late twenties, relaxed pace, light smile in the tone, neutral "
              "international English accent"},
    {"slug": "dario-quell", "name": "Dario Quell", "persona": "Early-30s gym coach, upbeat and direct.",
     "look": "Original synthetic man, early 30s, tan skin, short dark beard, athletic build, grey hoodie, "
             "bright home gym background",
     "voice": "Energetic male voice in his early thirties, quick confident pace, friendly and direct"},
    {"slug": "noor-ellison", "name": "Noor Ellison", "persona": "Mid-30s parent of two, practical and funny.",
     "look": "Original synthetic woman, mid 30s, brown skin, curly black hair in a loose bun, denim shirt, "
             "sunny family kitchen",
     "voice": "Friendly female voice in her mid thirties, conversational, a little playful, everyday warmth"},
    {"slug": "tomas-vireo", "name": "Tomas Vireo", "persona": "Late-40s small business owner, trustworthy.",
     "look": "Original synthetic man, late 40s, light skin with freckles, salt-and-pepper short hair, navy "
             "overshirt, tidy workshop with wooden shelves",
     "voice": "Steady, reassuring male voice in his late forties, unhurried, plain-spoken"},
    {"slug": "aiko-brandt", "name": "Aiko Brandt", "persona": "Early-20s student, curious and quick.",
     "look": "Original synthetic woman, early 20s, East Asian features, straight black bob, oversized cream "
             "cardigan, dorm desk with a lamp",
     "voice": "Bright young female voice, early twenties, fast and curious, casual"},
    {"slug": "kofi-laraway", "name": "Kofi Laraway", "persona": "Late-20s software engineer, dry humor.",
     "look": "Original synthetic man, late 20s, dark skin, short twists, round glasses, olive t-shirt, "
             "home office with a monitor and a plant",
     "voice": "Smooth male voice in his late twenties, dry humor, measured pace"},
    {"slug": "elif-marrow", "name": "Elif Marrow", "persona": "Early-40s nurse, kind and matter-of-fact.",
     "look": "Original synthetic woman, early 40s, light olive skin, auburn hair in a ponytail, soft blue "
             "scrubs top, calm living room",
     "voice": "Kind, matter-of-fact female voice in her early forties, gentle and clear"},
    {"slug": "ren-halvorsen", "name": "Ren Halvorsen", "persona": "Mid-60s retired teacher, patient.",
     "look": "Original synthetic man, mid 60s, pale skin, white short hair, trimmed white beard, cardigan "
             "over a collared shirt, cozy reading corner",
     "voice": "Patient older male voice in his sixties, warm and slow, storyteller tone"},
)


def _view(a: dict[str, str]) -> dict[str, Any]:
    return {
        "id": f"preset:{a['slug']}", "slug": a["slug"], "name": a["name"], "persona": a["persona"],
        "look_prompt": a["look"] + ". Photorealistic portrait of an original, invented person.",
        "voice_design_prompt": a["voice"] + ". An original designed voice.",
        "product_shot_template": _SHOT.replace("{who}", a["name"].split()[0]),
        "face_image_url": "", "voice_id": "", "builtin": True, "status": "preset",
        "provenance": {"synthetic": True, "generator": "menivor-actor-presets", "version": PROVENANCE_VERSION,
                       "face": "generated from look_prompt on first use (no photo input)"},
        "consent": {"type": "synthetic_no_real_person", "attested_by": "menivor", "attested_at": PROVENANCE_VERSION},
    }


def all_presets() -> list[dict[str, Any]]:
    return [_view(a) for a in _ACTORS]


def get(slug: str) -> dict[str, Any] | None:
    return next((p for p in all_presets() if p["slug"] == slug), None)


__all__ = ["all_presets", "get"]
