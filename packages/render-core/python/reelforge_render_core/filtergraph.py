"""RenderSpec → FFmpeg ``filter_complex`` builder (mirror of ``src/filtergraph.ts``).

Pure, deterministic string assembly with stable pad labels — no process spawning,
no storage (that stays in ``compose_ffmpeg.py``). Byte-identical to the TypeScript
port so the client preview and the burned output agree (golden fixtures).

WHY THIS MIRRORS ``compose_ffmpeg.py`` EXACTLY
----------------------------------------------
The executor (``apps/api/app/services/compose/compose_ffmpeg.py``) is the only
process that spawns FFmpeg. Its layout builders (``_layout_pip`` / ``_layout_split``
/ ``_layout_hook_intro`` / ``_fill_node``) all terminate at the ``[comp]`` sink,
and its ``_build_audio_graph`` terminates at ``[aout]``. Those two fragments are
pure, deterministic, and environment-independent, so this library reproduces them
**byte-for-byte** — that is the "preview == output" contract.

The nodes the executor appends AFTER ``[comp]`` (the libass caption burn and the
brand watermark) are intentionally NOT modelled here: they escape an absolute
filesystem path and embed ``utils.font_dir()``, which are resolved at render time
and cannot be reproduced in a portable TS client. ``video_out_label`` returns the
composition sink (``[comp]``); the executor takes over from there.

Chroma / PiP diameter / margin / loudnorm targets are always the executor's
defaults in the shipping call path (``reelforge.py`` never overrides them), so
they are baked here as constants that match ``_chroma_filter`` /
``_build_audio_graph`` output exactly — keeping the TS port free of locale-
sensitive ``%g`` float formatting.

A ``RenderSpec`` is a plain dict::

    {
      "output": {"width": 1080, "height": 1920, "fps": 30},
      "layout": "captions_only" | "pip" | "split" | "hook_intro",
      "avatar": {"input": 1, "diameter": 480, "margin": 48},   # pip/split/hook_intro
      "caption_ass": "captions.ass",                            # signal only
      "audio":  {"narration": 2, "bgm": 3},                     # bgm => duck + loudnorm
    }
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------- #
# Constants — every one mirrors a compose_ffmpeg default so the executor's
# byte output is reproduced without any float formatting.
# --------------------------------------------------------------------------- #
# ``_chroma_filter({"color":"0x00FF00","similarity":0.18,"blend":0.10})``.
_CHROMA = "chromakey=0x00FF00:0.18:0.1"
# ``_PIP_DIAMETER`` / ``_PIP_MARGIN``.
_PIP_DIAMETER = 480
_PIP_MARGIN = 48
# ``_HOOK_DURATION`` formatted with ``:g``.
_HOOK = "3"
# ``sidechaincompress`` ducking curve (``_DUCK_*`` constants).
_DUCK = "sidechaincompress=threshold=0.03:ratio=8:attack=5:release=250"
# ``_build_audio_graph``'s default loudnorm node: the -14 LUFS / -1 dBTP social
# target, formatted with ``:g`` (``-14`` / ``-1`` / ``11``). A deploy that overrides
# ``MENIVOR_LOUDNORM_I`` / ``_TP`` changes only loudness, not the graph shape.
_LOUDNORM = "loudnorm=I=-14:TP=-1:LRA=11"

_AVATAR_LAYOUTS = frozenset({"pip", "split", "hook_intro"})
_LAYOUTS = frozenset({"captions_only"}) | _AVATAR_LAYOUTS


def _dims(spec: dict[str, Any]) -> tuple[int, int]:
    out = spec.get("output") or {}
    return int(out.get("width", 1080)), int(out.get("height", 1920))


def _avatar(spec: dict[str, Any]) -> dict[str, Any]:
    av = spec.get("avatar") or {}
    return {
        "input": int(av.get("input", 1)),
        "diameter": int(av.get("diameter", _PIP_DIAMETER)),
        "margin": int(av.get("margin", _PIP_MARGIN)),
    }


def _circle_geq(radius: int) -> str:
    """The ``geq`` circular-alpha mask (mirror of ``_circular_avatar_node``)."""
    return (
        "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        f"a='if(lte(hypot(X-{radius},Y-{radius}),{radius}),alpha(X,Y),0)'"
    )


# --------------------------------------------------------------------------- #
# Layout builders — each returns a filtergraph string terminating in ``[comp]``.
# Input 0 = screen video, input ``avatar.input`` = green-screen avatar video.
# Byte-identical to compose_ffmpeg's ``_LAYOUTS`` entries + ``_fill_node``.
# --------------------------------------------------------------------------- #
def _layout_base(w: int, h: int) -> str:
    """Screen cover-cropped to fill WxH (mirror of ``_fill_node('0:v','comp')``)."""
    return (
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1[comp]"
    )


def _layout_pip(w: int, h: int, av: dict[str, Any]) -> str:
    """Full-screen recording with a circular avatar badge bottom-right."""
    d = av["diameter"]
    radius = d // 2
    ai = av["input"]
    x = max(0, w - d - av["margin"])
    y = max(0, h - d - av["margin"])
    return ";".join(
        [
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1[bg]",
            f"[{ai}:v]{_CHROMA},"
            f"scale={d}:{d}:force_original_aspect_ratio=increase,"
            f"crop={d}:{d},format=rgba,{_circle_geq(radius)}[av]",
            f"[bg][av]overlay=x={x}:y={y}:format=auto[comp]",
        ]
    )


def _layout_split(w: int, h: int, av: dict[str, Any]) -> str:
    """Top half = screen recording, bottom half = chroma-keyed avatar."""
    half = h // 2
    ai = av["input"]
    return ";".join(
        [
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,split=2[s_top][s_bot]",
            f"[s_top]crop={w}:{half}:0:0[top]",
            f"[s_bot]crop={w}:{half}:0:{half}[botbg]",
            f"[{ai}:v]{_CHROMA},"
            f"scale={w}:{half}:force_original_aspect_ratio=increase,"
            f"crop={w}:{half},setsar=1,format=rgba[botfg]",
            "[botbg][botfg]overlay=0:0:format=auto[bot]",
            "[top][bot]vstack=inputs=2[comp]",
        ]
    )


def _layout_hook_intro(w: int, h: int, av: dict[str, Any]) -> str:
    """Avatar full-frame for the first ``_HOOK`` seconds, then a PiP badge."""
    d = av["diameter"]
    radius = d // 2
    ai = av["input"]
    x = max(0, w - d - av["margin"])
    y = max(0, h - d - av["margin"])
    return ";".join(
        [
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1[bg]",
            f"[{ai}:v]{_CHROMA},format=rgba,split=2[a_raw][b_raw]",
            f"[a_raw]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1[a_full]",
            f"[b_raw]scale={d}:{d}:force_original_aspect_ratio=increase,"
            f"crop={d}:{d},{_circle_geq(radius)}[a_pip]",
            f"[bg][a_full]overlay=0:0:format=auto:enable='lt(t,{_HOOK})'[tmp]",
            f"[tmp][a_pip]overlay=x={x}:y={y}:format=auto:enable='gte(t,{_HOOK})'[comp]",
        ]
    )


def build_video_graph(spec: dict[str, Any]) -> str:
    """Build the composition graph (video only, terminating in ``[comp]``)."""
    w, h = _dims(spec)
    layout = spec.get("layout", "captions_only")
    if layout == "pip":
        return _layout_pip(w, h, _avatar(spec))
    if layout == "split":
        return _layout_split(w, h, _avatar(spec))
    if layout == "hook_intro":
        return _layout_hook_intro(w, h, _avatar(spec))
    return _layout_base(w, h)


def build_audio_graph(spec: dict[str, Any]) -> str:
    """Build the ducked-music + loudnorm audio graph (or ``""`` when no bgm).

    Mirror of ``compose_ffmpeg._build_audio_graph(voice_input=narration,
    music_input=bgm)`` — present only when the spec carries a ``bgm`` input, which
    is exactly when the executor is invoked with a ``music_path``.
    """
    audio = spec.get("audio")
    if not audio:
        return ""
    bgm = audio.get("bgm")
    if bgm is None:
        return ""
    nar = int(audio["narration"])
    bgm = int(bgm)
    return ";".join(
        [
            f"[{nar}:a]asplit=2[vo][vo_key]",
            f"[{bgm}:a][vo_key]{_DUCK}[duck]",
            "[vo][duck]amix=inputs=2:duration=first:dropout_transition=0[premix]",
            f"[premix]{_LOUDNORM}[aout]",
        ]
    )


def build_filtergraph(spec: dict[str, Any]) -> str:
    """Build the FFmpeg ``filter_complex`` string for a spec (deterministic).

    Composition graph (``[comp]``) followed, when background music is present, by
    the ducked-and-loudness-normalised audio graph (``[aout]``) — joined exactly
    as the executor joins them (``video + ';' + audio``).
    """
    parts = [build_video_graph(spec)]
    audio = build_audio_graph(spec)
    if audio:
        parts.append(audio)
    return ";".join(parts)


def video_out_label(spec: dict[str, Any]) -> str:  # noqa: ARG001 - stable contract
    """The composition video sink to continue from (always ``[comp]``).

    The executor appends its environment-specific caption-burn and watermark nodes
    after this label; those are not part of the byte-identical shared contract.
    """
    return "[comp]"


def has_audio_out(spec: dict[str, Any]) -> bool:
    audio = spec.get("audio")
    return bool(audio and audio.get("bgm") is not None)
