"""RenderSpec helpers + invariant validation (mirror of ``src/spec.ts``).

The spec is transport JSON; these helpers build/validate it without pulling in a
schema dependency, so the executor and client agree on the same shape. The shape
mirrors ``compose_ffmpeg``: a ``layout`` (``captions_only`` needs no avatar; the
avatar overlays ``pip`` / ``split`` / ``hook_intro`` require an ``avatar`` input),
optional ``caption_ass`` signal, and optional ducked background ``audio``.
"""

from __future__ import annotations

from typing import Any

# Kept in lock-step with ``filtergraph._LAYOUTS`` / compose_ffmpeg's registry.
AVATAR_LAYOUTS: frozenset[str] = frozenset({"pip", "split", "hook_intro"})
LAYOUTS: frozenset[str] = frozenset({"captions_only"}) | AVATAR_LAYOUTS

_DEFAULT_DIAMETER = 480
_DEFAULT_MARGIN = 48


def make_spec(
    *,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    layout: str = "captions_only",
    avatar_input: int | None = None,
    diameter: int = _DEFAULT_DIAMETER,
    margin: int = _DEFAULT_MARGIN,
    caption_ass: str | None = None,
    narration: int | None = None,
    bgm: int | None = None,
) -> dict[str, Any]:
    """Assemble a RenderSpec dict.

    ``avatar_input`` defaults to ``1`` for the avatar overlay layouts (matching the
    executor's input ordering) and is omitted for ``captions_only``.
    """
    spec: dict[str, Any] = {
        "output": {"width": width, "height": height, "fps": fps},
        "layout": layout,
    }
    if layout in AVATAR_LAYOUTS:
        spec["avatar"] = {
            "input": 1 if avatar_input is None else avatar_input,
            "diameter": diameter,
            "margin": margin,
        }
    elif avatar_input is not None:
        spec["avatar"] = {"input": avatar_input, "diameter": diameter, "margin": margin}
    if caption_ass:
        spec["caption_ass"] = caption_ass
    if narration is not None:
        audio: dict[str, Any] = {"narration": narration}
        if bgm is not None:
            audio["bgm"] = bgm
        spec["audio"] = audio
    return spec


def validate_spec(spec: dict[str, Any]) -> list[str]:
    """Return a list of invariant violations (empty = valid)."""
    errors: list[str] = []
    out = spec.get("output") or {}
    for k in ("width", "height", "fps"):
        v = out.get(k)
        if not isinstance(v, int) or v <= 0:
            errors.append(f"output.{k} must be a positive int")

    layout = spec.get("layout", "captions_only")
    if layout not in LAYOUTS:
        errors.append(f"layout must be one of {sorted(LAYOUTS)}")

    avatar = spec.get("avatar")
    if layout in AVATAR_LAYOUTS:
        if not isinstance(avatar, dict) or not isinstance(avatar.get("input"), int):
            errors.append(f"layout {layout!r} requires avatar.input (an int)")
    if isinstance(avatar, dict):
        for k in ("diameter", "margin"):
            if k in avatar and (not isinstance(avatar[k], int) or avatar[k] < 0):
                errors.append(f"avatar.{k} must be a non-negative int")

    audio = spec.get("audio")
    if audio is not None:
        if not isinstance(audio.get("narration"), int):
            errors.append("audio.narration must be an int")
        if "bgm" in audio and not isinstance(audio["bgm"], int):
            errors.append("audio.bgm must be an int")
    return errors
