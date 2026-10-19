"""Pydantic DTOs + view builders for the shot-template HTTP surface."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .definitions import ShotTemplateDef


class CompileRequest(BaseModel):
    """Body for compile / instantiate — creator inputs + optional duration."""

    inputs: dict = Field(default_factory=dict)
    duration_s: Optional[float] = None
    surface: Optional[str] = Field(default=None, description="tiktok | reels | shorts")
    # Optional bound character (Wave 4 identity lock). When set, the caller's
    # OWNED character is loaded and each compiled segment carries a deterministic
    # IdentityLock (reference sheet + LoRA + per-shot seed) so the render worker
    # reproduces the same identity across every shot.
    character_id: Optional[str] = Field(default=None, max_length=64)


def slot_view(slot) -> dict:
    return {
        "role": slot.role,
        "order": slot.order,
        "label": slot.label,
        "t_start_frac": slot.t_start_frac,
        "t_end_frac": slot.t_end_frac,
        "track": slot.track,
        "audio": list(slot.audio),
        "caption": slot.caption,
        "hook_gate": slot.hook_gate,
        "notes": slot.notes,
    }


def input_view(inp) -> dict:
    return {
        "key": inp.key,
        "kind": inp.kind,
        "label": inp.label,
        "required": inp.required,
        "help": inp.help,
        "choices": list(inp.choices),
        "default": inp.default,
    }


def template_summary(t: ShotTemplateDef) -> dict:
    """Compact gallery card."""
    from .presets.aliases import public_slug

    return {
        "slug": public_slug(t.slug),
        "name": t.name,
        "genre": t.genre,
        "version": t.version,
        "description": t.description,
        "aspect": t.aspect,
        "layout": t.layout,
        "default_duration_s": t.default_duration_s,
        "min_duration_s": t.min_duration_s,
        "max_duration_s": t.max_duration_s,
        "caption_style": t.caption_style,
        "camera_motion": t.camera_motion,
        "effects": list(t.effects),
        "loopable": t.loopable,
        "tags": list(t.tags),
        "slot_count": len(t.slots),
    }


def template_detail(t: ShotTemplateDef) -> dict:
    """Full template with slots + inputs (the editor view)."""
    return {
        **template_summary(t),
        "vfx_intensity": t.vfx_intensity,
        "audio": {
            "foreground": t.audio.foreground,
            "bgm_prompt": t.audio.bgm_prompt,
            "duck": t.audio.duck,
            "trend_relink": t.audio.trend_relink,
        },
        "slots": [slot_view(s) for s in t.slots],
        "inputs": [input_view(i) for i in t.inputs],
    }
