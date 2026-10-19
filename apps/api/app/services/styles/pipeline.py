"""Compose-stage glue: turn a style job into its visual ("screen") track.

Called by ``reelforge.stage_compose`` when a job carries a ``style`` whose recipe
has a scene and the creator uploaded no footage. Resolves the product visuals
(AI anime scenes, the pasted page's preview image, or a title card), the style's
looping companion clip, and the hook line, renders the 1080x1920 track with
:mod:`app.services.styles.scene`, and returns the local path. Returns ``""`` on
any failure so compose falls back to the classic background path (a style must
never fail a paid render on its own).
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
from typing import Any, Callable

from loguru import logger

from app.domains.styles.catalog import get_style


def hook_line(script: str) -> str:
    """The script's opening line (the hook): its first paragraph."""
    for part in re.split(r"\n\s*\n", str(script or "").strip()):
        clean = re.sub(r"\s+", " ", part).strip()
        if clean:
            return clean
    return ""


def _loop_path(background_id: str, job_id: str, duration_s: float, work_dir: str = "") -> str:
    """A loop track for this job, mixed from the clip's variants.

    Variants are ordered by a hash of the job id and cycled until the reel is
    covered, so two reels never share the same loop end to end. Falls back to
    the single clip when there is one variant or the mix fails.

    Each variant is the pre-encoded 1080x1920 copy (``services.loops.prepared``),
    so the mix is a stream copy with no encode. When a variant could not be
    prepared the mix is re-encoded once, as before.
    """
    from app.services.loops import prepared
    if not background_id:
        return ""
    from app.domains.content import background_library as bglib

    clips = [c for c in bglib.variants_of(background_id) if not c.needs_asset] or (
        [bglib.resolve(background_id)] if bglib.resolve(background_id) else []
    )
    paths: list[str] = []
    for clip in clips:
        try:
            got = bglib.materialize(clip, task_id=job_id, duration_s=duration_s)
        except Exception as exc:  # noqa: BLE001 - a missing variant is skipped
            logger.warning(f"[{job_id}] loop variant {clip.id} unavailable: {exc}")
            continue
        if got:
            paths.append(prepared.prepared_loop(str(got[0])))
    if not paths:
        return ""
    if len(paths) == 1 or not work_dir:
        return paths[0]
    order = mix_order(paths, job_id, duration_s)
    try:
        os.makedirs(work_dir, exist_ok=True)
        listing = os.path.join(work_dir, "loop-mix.txt")
        with open(listing, "w", encoding="utf-8") as handle:
            for path in order:
                handle.write(f"file '{path}'\n")
        out = os.path.join(work_dir, "loop-mix.mp4")
        if all(prepared.is_prepared(path) for path in order):
            # Same codec, size, fps and GOP: join by stream copy (no encode).
            subprocess.run(prepared.concat_copy_command(listing, out, ffmpeg=_ffmpeg()), check=True, timeout=120)
            return out
        subprocess.run(
            [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", listing, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
             "-pix_fmt", "yuv420p", out],
            check=True, timeout=300,
        )
        from app.services.compose import encode_count

        encode_count.count("loop_mix")
        return out
    except Exception as exc:  # noqa: BLE001 - fall back to one clip
        logger.warning(f"[{job_id}] loop mix failed: {exc}")
        return paths[0]


SEGMENT_S = 8.0


def mix_order(paths: list[str], job_id: str, duration_s: float) -> list[str]:
    """Variant segments covering ``duration_s``, ordered by the job id."""
    ranked = sorted(paths, key=lambda path: hashlib.sha256(f"{job_id}:{path}".encode()).hexdigest())
    count = max(1, int(math.ceil(float(duration_s) / SEGMENT_S)))
    return [ranked[index % len(ranked)] for index in range(count)]


def _record_page(url: str, dest: str, width: int, height: int, duration_s: float) -> str:
    from app.services.styles.page_recording import record_page
    from app.services.styles.recording_cache import cached_recording

    # One recording serves all of a reel's variants: the scene stream-loops the
    # clip to each variant's length, so the 2nd and 3rd variant skip Chromium.
    return cached_recording(
        url, width, height,
        lambda: record_page(url, dest, width=width, height=height, duration_s=duration_s),
    )


def _font_path() -> str:
    from app.utils import utils

    return os.path.join(utils.font_dir(), "Montserrat-ExtraBold.ttf")


def _ffmpeg() -> str:
    from app.utils import utils

    return utils.get_ffmpeg_binary() or "ffmpeg"


def _scene_inputs(
    job_id: str,
    params: Any,
    ctx: dict,
    work_dir: str,
    style: Any,
    *,
    anime: Callable[..., tuple[list[str], float]] | None = None,
    page: Callable[..., list[str]] | None = None,
    character: Callable[..., tuple[list[str], float]] | None = None,
    recorder: Callable[..., str] | None = None,
    loops: Callable[..., str] | None = None,
) -> dict | None:
    """Resolve a style's visuals, loop and hook: the scene keyword arguments.

    ``None`` when the style needs a loop clip that is unavailable.
    """
    from app.services.styles import scene as scene_mod
    from app.services.styles import visuals

    narration = float(ctx.get("audio_duration") or 0.0)
    duration = max(float(getattr(params, "target_duration_s", 0) or 0), narration + 0.4, 3.0)
    script = str(ctx.get("script") or getattr(params, "video_script", "") or "")
    subject = str(getattr(params, "video_subject", "") or "")
    visual_dir = os.path.join(work_dir, "style-visuals")

    images: list[str] = []
    if style.visual == "anime":
        images, spend = (anime or visuals.anime_images)(script, subject, visual_dir)
        ctx["style_provider_spend_usd"] = round(float(spend), 4)
    elif style.visual == "character":
        images, spend = (character or visuals.character_image)(visual_dir)
        ctx["style_provider_spend_usd"] = round(float(spend), 4)
    source_url = str(getattr(params, "source_url", "") or "")
    visual_video = ""
    if style.visual == "page" and source_url and style.scene not in ("story", "character"):
        width, height = scene_mod.panel_size(style.scene)
        visual_video = (recorder or _record_page)(
            source_url, os.path.join(visual_dir, "recording"), width, height, duration
        )
    if not images and not visual_video and style.visual in ("page", "anime"):
        images = (page or visuals.page_image)(source_url, visual_dir)

    loop_path = ""
    if style.scene in scene_mod.LOOP_SCENES:
        loop_path = (loops or _loop_path)(
            style.background_id or "block-runner", job_id, duration, os.path.join(work_dir, "style-loop")
        )
        if not loop_path:
            logger.warning(f"[{job_id}] style {style.id}: loop clip unavailable")
            return None

    return {
        "scene": style.scene,
        "images": images,
        "loop_path": loop_path,
        "hook": hook_line(script),
        "title": subject,
        "duration_s": duration,
        "font_path": _font_path(),
        "work_dir": os.path.join(work_dir, "style-scene"),
        "ffmpeg": _ffmpeg(),
        "visual_video": visual_video,
    }


def build_style_screen(
    job_id: str,
    params: Any,
    ctx: dict,
    work_dir: str,
    *,
    render: Callable[..., str] | None = None,
    anime: Callable[..., tuple[list[str], float]] | None = None,
    page: Callable[..., list[str]] | None = None,
    character: Callable[..., tuple[list[str], float]] | None = None,
    recorder: Callable[..., str] | None = None,
    loops: Callable[..., str] | None = None,
) -> str:
    """Render the style's screen track to ``work_dir``; ``""`` when not applicable.

    The two-pass path: the track is its own encode and compose encodes again.
    """
    style = get_style(str(getattr(params, "style", "") or ""))
    if style is None or not style.scene:
        return ""
    try:
        from app.services.styles import scene as scene_mod

        kwargs = _scene_inputs(
            job_id, params, ctx, work_dir, style,
            anime=anime, page=page, character=character, recorder=recorder, loops=loops,
        )
        if kwargs is None:
            return ""
        out_path = os.path.join(work_dir, "style-screen.mp4")
        (render or scene_mod.render_scene)(out_path=out_path, **kwargs)
        source = "page recording" if kwargs["visual_video"] else f"{len(kwargs['images'])} images"
        logger.info(f"[{job_id}] style {style.id}: scene {style.scene} rendered ({source})")
        return out_path
    except Exception as exc:  # noqa: BLE001 - degrade to the classic compose path
        logger.warning(f"[{job_id}] style scene failed (non-fatal): {type(exc).__name__}: {exc}")
        return ""


def plan_style_scene(
    job_id: str,
    params: Any,
    ctx: dict,
    work_dir: str,
    *,
    anime: Callable[..., tuple[list[str], float]] | None = None,
    page: Callable[..., list[str]] | None = None,
    character: Callable[..., tuple[list[str], float]] | None = None,
    recorder: Callable[..., str] | None = None,
    loops: Callable[..., str] | None = None,
) -> Any:
    """The style's ready ``SceneSpec`` for the single-pass compose, or ``None``.

    Same visuals, loop and hook as :func:`build_style_screen`, but nothing is
    encoded here: the compose draws the scene, captions and audio in one pass.
    ``None`` when the job has no scene style or any input fails (the caller
    then takes the classic path).
    """
    style = get_style(str(getattr(params, "style", "") or ""))
    if style is None or not style.scene:
        return None
    try:
        from app.services.styles import scene as scene_mod

        kwargs = _scene_inputs(
            job_id, params, ctx, work_dir, style,
            anime=anime, page=page, character=character, recorder=recorder, loops=loops,
        )
        if kwargs is None:
            return None
        spec = scene_mod.prepare_scene(**kwargs)
        scene_mod.build_filtergraph(spec)  # validate now, not inside FFmpeg
        logger.info(f"[{job_id}] style {style.id}: scene {spec.scene} planned for single-pass compose")
        return spec
    except Exception as exc:  # noqa: BLE001 - degrade to the classic compose path
        logger.warning(f"[{job_id}] style scene plan failed (non-fatal): {type(exc).__name__}: {exc}")
        return None


__all__ = ["build_style_screen", "hook_line", "plan_style_scene"]
