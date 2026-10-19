"""Single-pass compose for faceless style reels (M1.2).

The two-pass path encoded the style scene to an intermediate MP4 (a full
1080x1920 encode) and then encoded again to burn captions, mix audio and
stamp the watermark. Here the scene's filtergraph and inputs are spliced in
front of the compose graph, so a faceless style reel is ONE full H.264 encode:

    scene inputs (0..k-1) -> [out] -> fill (only if the aspect differs)
        -> camera motion / VFX -> captions (libass) -> watermark -> encode
    narration (k) [+ music (k+1)] -> ducking + loudnorm -> AAC

The node builders are the same ones the captions-only compose uses, so the
burned result matches the two-pass output (golden-frame tests compare them).
``COMPOSE_SINGLE_PASS=off`` keeps the old two-pass path.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

from app.models.schema import VideoAspect
from app.services import video as video_service
from app.services.compose import encode_count
from app.services.compose.compose_ffmpeg import (
    _LIBX264,
    _WATERMARK_MARGIN,
    _WATERMARK_OPACITY,
    _WATERMARK_POSITION,
    _WATERMARK_POSITIONS,
    _WATERMARK_SCALE,
    _build_audio_graph,
    _build_final_node,
    _build_watermark_node,
    _fill_node,
    _run_ffmpeg,
    _shortest_args,
    ffmpeg_has_filter,
    live_encode_args,
)
from app.utils import utils

_OFF_VALUES = frozenset({"0", "off", "false", "no"})
SCENE_OUT = "out"


def single_pass_enabled() -> bool:
    """``COMPOSE_SINGLE_PASS`` (default on); ``off``/``0``/``false`` keeps two passes."""
    return os.environ.get("COMPOSE_SINGLE_PASS", "on").strip().lower() not in _OFF_VALUES


def build_filtergraph(
    scene_graph: str,
    scene_inputs: int,
    *,
    width: int,
    height: int,
    scene_size: tuple[int, int],
    ass_path: str | None,
    music: bool,
    watermark: bool,
    watermark_position: str = _WATERMARK_POSITION,
    watermark_opacity: float = _WATERMARK_OPACITY,
    watermark_scale: float = _WATERMARK_SCALE,
    watermark_margin: int = _WATERMARK_MARGIN,
    camera_motion: str = "none",
    effects: list[str] | None = None,
    vfx_intensity: int = 50,
    fps: int = 30,
) -> tuple[str, str, str]:
    """``(filtergraph, video_map, audio_map)`` for the one-pass compose (pure)."""
    from app.services.compose.vfx import build_vfx_node

    graph = scene_graph
    label = SCENE_OUT
    if scene_size != (width, height):
        graph += ";" + _fill_node(SCENE_OUT, "comp", width, height)
        label = "comp"
    vfx_node, fx_label = build_vfx_node(
        camera_motion,
        effects,
        in_label=label,
        out_label="cfx",
        intensity=vfx_intensity,
        fps=fps,
        width=width,
        height=height,
    )
    graph += vfx_node + _build_final_node(ass_path, in_label=fx_label)

    voice_input = scene_inputs
    music_input = scene_inputs + 1
    video_map = "[final]"
    if watermark:
        logo_input = scene_inputs + (2 if music else 1)
        graph += _build_watermark_node(
            "final",
            f"{logo_input}:v",
            "wm",
            position=watermark_position,
            scale=watermark_scale,
            opacity=watermark_opacity,
            margin=watermark_margin,
        )
        video_map = "[wm]"
    audio_map = f"{voice_input}:a"
    if music:
        audio_graph, audio_out = _build_audio_graph(voice_input=voice_input, music_input=music_input)
        graph += ";" + audio_graph
        audio_map = f"[{audio_out}]"
    return graph, video_map, audio_map


def build_command(
    ffmpeg: str,
    scene_input_args: list[str],
    audio_path: str,
    output_file: str,
    filtergraph: str,
    codec: str,
    *,
    video_map: str,
    audio_map: str,
    threads: int = 2,
    fps: int = 30,
    music_path: str | None = None,
    watermark_path: str | None = None,
) -> list[str]:
    """The full FFmpeg argv for the one-pass compose (pure)."""
    command: list[str] = [ffmpeg, "-y", *scene_input_args, "-i", audio_path]
    if music_path:
        command += ["-i", music_path]
    if watermark_path:
        command += ["-i", watermark_path]
    command += [
        "-filter_complex", filtergraph,
        "-map", video_map,
        "-map", audio_map,
        "-c:v", codec,
        *live_encode_args(codec, fps),
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-threads", str(threads or 2),
        *_shortest_args(ffmpeg),
        "-movflags", "+faststart",
        output_file,
    ]
    return command


def _check_inputs(
    audio_path: str,
    ass_path: str | None,
    music_path: str | None,
    watermark_path: str | None,
    watermark_position: str,
) -> None:
    if watermark_path is not None and watermark_position not in _WATERMARK_POSITIONS:
        allowed = ", ".join(sorted(_WATERMARK_POSITIONS))
        raise ValueError(f"unsupported watermark position: {watermark_position!r} (allowed: {allowed})")
    if not audio_path or not os.path.exists(audio_path):
        raise FileNotFoundError(f"compose audio input not found: {audio_path!r}")
    for label, path in (("caption", ass_path), ("music", music_path), ("watermark", watermark_path)):
        if path and not os.path.exists(path):
            raise FileNotFoundError(f"compose {label} input not found: {path!r}")


def compose_scene_with_captions(
    spec: Any,
    audio_path: str,
    output_file: str,
    *,
    ass_path: str | None = None,
    aspect: VideoAspect = VideoAspect.portrait,
    threads: int = 2,
    fps: int = 30,
    music_path: str | None = None,
    watermark_path: str | None = None,
    watermark_position: str = _WATERMARK_POSITION,
    watermark_opacity: float = _WATERMARK_OPACITY,
    watermark_scale: float = _WATERMARK_SCALE,
    watermark_margin: int = _WATERMARK_MARGIN,
    camera_motion: str = "none",
    effects: list[str] | None = None,
    vfx_intensity: int = 50,
) -> str:
    """Render a style ``SceneSpec`` with captions and narration in ONE encode.

    Same contract and errors as ``compose_captions_over_screen``: returns
    ``output_file``; raises ``FileNotFoundError`` / ``ValueError`` /
    ``RuntimeError``. A failing hardware codec is retried once with libx264.
    """
    from app.services.styles import scene as scene_mod

    _check_inputs(audio_path, ass_path, music_path, watermark_path, watermark_position)
    ffmpeg = utils.get_ffmpeg_binary()
    if ass_path and not ffmpeg_has_filter("ass", ffmpeg):
        raise RuntimeError(
            "caption burning requires an FFmpeg built with libass (--enable-libass), "
            "but the current binary lacks the 'ass' filter."
        )
    if music_path:
        for needed in ("sidechaincompress", "loudnorm"):
            if not ffmpeg_has_filter(needed, ffmpeg):
                raise RuntimeError(f"background-music ducking requires the {needed!r} filter.")

    width, height = VideoAspect(aspect).to_resolution()
    inputs = scene_mod.input_args(spec)
    filtergraph, video_map, audio_map = build_filtergraph(
        scene_mod.build_filtergraph(spec),
        inputs.count("-i"),
        width=width,
        height=height,
        scene_size=(scene_mod.WIDTH, scene_mod.HEIGHT),
        ass_path=ass_path,
        music=bool(music_path),
        watermark=bool(watermark_path),
        watermark_position=watermark_position,
        watermark_opacity=watermark_opacity,
        watermark_scale=watermark_scale,
        watermark_margin=watermark_margin,
        camera_motion=camera_motion,
        effects=effects,
        vfx_intensity=vfx_intensity,
        fps=fps,
    )
    codec = video_service._get_effective_video_codec()
    logger.info(
        f"single-pass compose: scene={spec.scene}, size={width}x{height}, codec={codec}, "
        f"captions={'yes' if ass_path else 'no'}, music={'yes' if music_path else 'no'}"
    )

    def _compose_with(codec_name: str) -> None:
        _run_ffmpeg(
            build_command(
                ffmpeg, inputs, audio_path, output_file, filtergraph, codec_name,
                video_map=video_map, audio_map=audio_map, threads=threads, fps=fps,
                music_path=music_path, watermark_path=watermark_path,
            )
        )
        encode_count.count("compose")

    try:
        _compose_with(codec)
    except RuntimeError as exc:
        if codec == _LIBX264:
            raise
        logger.warning(f"single-pass compose failed with {codec}, retrying with {_LIBX264}: {exc}")
        _compose_with(_LIBX264)
        video_service._disable_runtime_video_codec(codec, str(exc))
    return output_file


__all__ = [
    "build_command",
    "build_filtergraph",
    "compose_scene_with_captions",
    "single_pass_enabled",
]
