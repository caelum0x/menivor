"""Render-worker implementation for non-destructive editor exports."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.domains.canon.binding import stamp_asset_from_params
from app.models.db.base import get_session
from app.models.db.repositories import AssetRepository, JobRepository
from app.platform.storage.r2 import get_r2_client
from app.utils import utils

from .service import (
    EDITOR_EXPORT_KIND,
    EDITOR_EXPORT_STAGE,
    TIMELINE_EXPORT_KIND,
)


def _load_export(job_id: str) -> dict[str, Any]:
    with get_session() as session:
        repository = JobRepository(session)
        export = repository.get(job_id)
        if export is None or export.kind != EDITOR_EXPORT_KIND:
            raise ValueError(f"editor export job was not found: {job_id}")
        params = dict(export.params or {})
        source = repository.get(str(params.get("source_job_id") or ""))
        if source is None or str(source.user_id) != str(export.user_id):
            raise ValueError("editor export source is unavailable")
        source_key = str(source.result_key or "").strip()
        if not source_key:
            raise ValueError("editor export source has no media result")
        repository.update_stage(job_id, EDITOR_EXPORT_STAGE, "running")
        repository.set_progress(job_id, 10)
        return {
            "user_id": str(export.user_id),
            "source_job_id": str(source.id),
            "source_key": source_key,
            "in_point": float(params["in_point"]),
            "out_point": float(params["out_point"]),
            "correlation_id": str(params.get("_correlation_id") or ""),
            # Canon provenance carried forward from the SOURCE reel (if it was
            # bound to a canon) so the exported final asset stays verifiable.
            "source_params": dict(source.params or {}),
        }


def _render_cut(source_path: Path, output_path: Path, start: float, end: float) -> None:
    duration = end - start
    command = [
        utils.get_ffmpeg_binary(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source_path),
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if (
        completed.returncode != 0
        or not output_path.is_file()
        or output_path.stat().st_size == 0
    ):
        detail = (completed.stderr or "FFmpeg produced no output").strip()
        raise RuntimeError(f"editor export failed: {detail[-1200:]}")


# --------------------------------------------------------------------------- #
# Timeline / EDL export (multi-segment trims + reorder + per-segment speed +
# captions + time-anchored text overlays). The browser assembles the EDL; the
# server renders it authoritatively with a single pure-FFmpeg filter_complex.
# --------------------------------------------------------------------------- #
_DEFAULT_FRAME = (1080, 1920)
_DEFAULT_FPS = 30


def _pick_font() -> str | None:
    """Return a usable TTF path for drawtext, or ``None`` (skip text burn)."""
    try:
        font_root = utils.font_dir()
    except Exception:  # noqa: BLE001 - font resolution is best-effort
        return None
    for name in ("Inter-Bold.ttf", "Montserrat-ExtraBold.ttf", "BeVietnamPro-Bold.ttf"):
        candidate = os.path.join(font_root, name)
        if os.path.isfile(candidate):
            return candidate
    try:
        for entry in sorted(os.listdir(font_root)):
            if entry.lower().endswith(".ttf"):
                return os.path.join(font_root, entry)
    except Exception:  # noqa: BLE001
        return None
    return None


def _ffmpeg_has_drawtext() -> bool:
    """Whether the runtime FFmpeg build exposes the ``drawtext`` filter."""
    try:
        from app.services.compose.compose_ffmpeg import ffmpeg_has_filter

        return ffmpeg_has_filter("drawtext")
    except Exception:  # noqa: BLE001 - absence => skip text burn (best-effort)
        return False


def _atempo_chain(speed: float) -> str:
    """Return the ``,atempo=...`` audio-tempo chain for ``speed`` (0.25..4.0).

    A single ``atempo`` only accepts [0.5, 2.0], so out-of-range speeds are
    decomposed into a product of in-range factors (empty string for speed 1.0).
    """
    if abs(speed - 1.0) < 1e-6 or speed <= 0:
        return ""
    factors: list[float] = []
    remaining = speed
    while remaining > 2.0 + 1e-6:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5 - 1e-6:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return "".join(f",atempo={f:.6g}" for f in factors)


def _probe_frame(source_path: Path) -> tuple[int, int, int]:
    """Return ``(width, height, fps)`` for the source, with safe fallbacks."""
    try:
        from app.services.compose.compose_ffmpeg import _probe_video

        info = _probe_video(str(source_path))
        if info and int(info.width) > 0 and int(info.height) > 0:
            fps = int(round(info.fps)) if getattr(info, "fps", 0) else _DEFAULT_FPS
            return int(info.width), int(info.height), max(1, fps)
    except Exception:  # noqa: BLE001 - probing is best-effort
        pass
    return (*_DEFAULT_FRAME, _DEFAULT_FPS)


def _source_has_audio(source_path: Path) -> bool:
    """Best-effort check for an audio stream in the source media."""
    try:
        from app.services.compose.compose_ffmpeg import _get_ffprobe_binary

        probe = subprocess.run(
            [
                _get_ffprobe_binary(),
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                str(source_path),
            ],
            capture_output=True, text=True, check=False,
        )
        return bool((probe.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return False


def _drawtext_node(
    in_label: str,
    out_label: str,
    textfile: str,
    position: str,
    width: int,
    height: int,
    start: float,
    end: float,
) -> str:
    """A ``drawtext`` node reading text from a file (no in-graph escaping needed).

    Centred horizontally, vertically placed by ``position`` (top/center/bottom),
    boxed for legibility, and time-gated to ``[start, end]`` on the output.
    """
    font_size = max(24, height // 22)
    if position == "top":
        y = f"{int(height * 0.08)}"
    elif position == "center":
        y = "(h-text_h)/2"
    else:
        y = f"{int(height * 0.82)}"
    return (
        f"[{in_label}]drawtext=textfile={textfile}:fontfile={_FONT_ARG}:"
        f"fontcolor=white:fontsize={font_size}:box=1:boxcolor=black@0.5:"
        f"boxborderw=16:x=(w-text_w)/2:y={y}:"
        f"enable='between(t,{start:.3f},{end:.3f})'[{out_label}]"
    )


# Bound at render time by ``_render_timeline`` (module-level so ``_drawtext_node``
# can read it without threading it through every call).
_FONT_ARG = ""


def _write_textfile(work: Path, name: str, text: str) -> str:
    path = work / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _resolve_music(edl: dict) -> tuple[str | None, float]:
    """Resolve the optional EDL ``music`` block to ``(path, volume)``.

    Returns ``(None, 1.0)`` when no track is selected or the curated id cannot be
    resolved to a real file in the songs library — the render then degrades to no
    background music (best-effort, mirroring the text-burn fallback) rather than
    failing the export. ``get_music_path`` guarantees the path stays inside the
    songs directory, so an unknown/traversal id resolves to nothing.
    """
    music = edl.get("music")
    if not isinstance(music, dict):
        return None, 1.0
    music_id = str(music.get("music_id") or "").strip()
    if not music_id:
        return None, 1.0
    try:
        volume = float(music.get("volume", 1.0))
    except (TypeError, ValueError):
        volume = 1.0
    volume = max(0.0, min(2.0, volume))
    try:
        from app.services.music import get_music_path

        path = get_music_path(music_id)
    except Exception:  # noqa: BLE001 - music library is best-effort
        path = None
    return path, volume


def _render_timeline(source_path: Path, output_path: Path, edl: dict, work: Path) -> None:
    """Render a normalized EDL to a single MP4 via one FFmpeg filter_complex.

    Builds per-segment trim + speed (video ``setpts`` + audio ``atempo`` chain) +
    scale/pad to a common frame, concatenates the segments in order, then burns
    per-segment captions and time-anchored text overlays. Reorder is expressed by
    the segment order; b-roll repeats are allowed (segments may reuse ranges).
    """
    global _FONT_ARG

    segments = list(edl.get("segments") or [])
    overlays = list(edl.get("overlays") or [])
    if not segments:
        raise ValueError("timeline export has no segments")

    width, height, fps = _probe_frame(source_path)
    has_audio = _source_has_audio(source_path)
    # Text burn (captions/overlays) needs a resolvable font AND an FFmpeg built
    # with the ``drawtext`` filter (libfreetype). When either is missing we still
    # render the trims/reorder/speed concat — the text is simply omitted rather
    # than failing the export (best-effort, mirroring the compose stage).
    font = _pick_font()
    can_draw = bool(font) and _ffmpeg_has_drawtext()
    _FONT_ARG = font or ""

    graph_parts: list[str] = []
    concat_inputs: list[str] = []
    offset = 0.0
    seg_windows: list[tuple[float, float, str | None]] = []

    for i, seg in enumerate(segments):
        s_in = float(seg["source_in"])
        s_out = float(seg["source_out"])
        speed = float(seg.get("speed", 1.0)) or 1.0
        out_len = (s_out - s_in) / speed
        graph_parts.append(
            f"[0:v]trim=start={s_in:.3f}:end={s_out:.3f},"
            f"setpts=(PTS-STARTPTS)/{speed:.6g},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}]"
        )
        if has_audio:
            graph_parts.append(
                f"[0:a]atrim=start={s_in:.3f}:end={s_out:.3f},"
                f"asetpts=PTS-STARTPTS{_atempo_chain(speed)}[a{i}]"
            )
            concat_inputs.append(f"[v{i}][a{i}]")
        else:
            concat_inputs.append(f"[v{i}]")
        seg_windows.append((offset, offset + out_len, seg.get("caption")))
        offset += out_len

    n = len(segments)
    if has_audio:
        graph_parts.append(
            "".join(concat_inputs) + f"concat=n={n}:v=1:a=1[vc][ac]"
        )
    else:
        graph_parts.append("".join(concat_inputs) + f"concat=n={n}:v=1:a=0[vc]")

    # Burn per-segment captions + time-anchored overlays (best-effort: only when a
    # font resolved). Each drawtext reads its text from a file to avoid brittle
    # filtergraph escaping of arbitrary user text.
    video_label = "vc"
    text_idx = 0
    if can_draw:
        for i, (win_start, win_end, caption) in enumerate(seg_windows):
            if not caption or not str(caption).strip():
                continue
            tf = _write_textfile(work, f"cap_{i}.txt", str(caption))
            nxt = f"t{text_idx}"
            graph_parts.append(
                _drawtext_node(video_label, nxt, tf, "bottom", width, height, win_start, win_end)
            )
            video_label = nxt
            text_idx += 1
        for j, ov in enumerate(overlays):
            text = str(ov.get("text") or "")
            if not text.strip():
                continue
            tf = _write_textfile(work, f"ov_{j}.txt", text)
            nxt = f"t{text_idx}"
            graph_parts.append(
                _drawtext_node(
                    video_label, nxt, tf,
                    str(ov.get("position") or "bottom"),
                    width, height,
                    float(ov.get("start_s", 0.0)), float(ov.get("end_s", 0.0)),
                )
            )
            video_label = nxt
            text_idx += 1

    video_map = f"[{video_label}]"

    # Optional curated background music mixed under the program audio. Resolved to
    # a real file in the songs library; an unknown id degrades to no music.
    music_path, music_volume = _resolve_music(edl)

    command = [
        utils.get_ffmpeg_binary(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source_path),
    ]
    next_input = 1
    # The program audio is either the concat filter's [ac] pad (source had audio)
    # or a generated silence input we can still reference/mix against. Keep both
    # the in-graph reference (bracketed) and the direct -map stream spec.
    if has_audio:
        program_audio = "[ac]"
        direct_audio_map = "[ac]"
    else:
        command += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        program_audio = f"[{next_input}:a]"
        direct_audio_map = f"{next_input}:a"
        next_input += 1

    if music_path:
        # Loop the track so it always covers the output; amix duration=first ties
        # the mix to the program length, and normalize=0 preserves both gains.
        command += ["-stream_loop", "-1", "-i", str(music_path)]
        music_input = next_input
        next_input += 1
        graph_parts.append(f"[{music_input}:a]volume={music_volume:.6g}[bgm]")
        graph_parts.append(
            f"{program_audio}[bgm]amix=inputs=2:duration=first:"
            f"dropout_transition=0:normalize=0[aout]"
        )
        audio_map = "[aout]"
    else:
        audio_map = direct_audio_map

    filtergraph = ";".join(graph_parts)
    command += [
        "-filter_complex", filtergraph,
        "-map", video_map, "-map", audio_map,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-shortest", str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if (
        completed.returncode != 0
        or not output_path.is_file()
        or output_path.stat().st_size == 0
    ):
        detail = (completed.stderr or "FFmpeg produced no output").strip()
        raise RuntimeError(f"timeline export failed: {detail[-1200:]}")


def _load_timeline_export(job_id: str) -> dict[str, Any]:
    with get_session() as session:
        repository = JobRepository(session)
        export = repository.get(job_id)
        if export is None or export.kind != TIMELINE_EXPORT_KIND:
            raise ValueError(f"timeline export job was not found: {job_id}")
        params = dict(export.params or {})
        edl = params.get("edl")
        if not isinstance(edl, dict) or not edl.get("segments"):
            raise ValueError("timeline export has no EDL")
        source = repository.get(str(params.get("source_job_id") or ""))
        if source is None or str(source.user_id) != str(export.user_id):
            raise ValueError("timeline export source is unavailable")
        source_key = str(source.result_key or "").strip()
        if not source_key:
            raise ValueError("timeline export source has no media result")
        repository.update_stage(job_id, EDITOR_EXPORT_STAGE, "running")
        repository.set_progress(job_id, 10)
        return {
            "user_id": str(export.user_id),
            "source_job_id": str(source.id),
            "source_key": source_key,
            "edl": edl,
            "correlation_id": str(params.get("_correlation_id") or ""),
            "source_params": dict(source.params or {}),
        }


def run_editor_timeline_export(job_id: str) -> dict[str, Any]:
    """Download, render the multi-segment EDL, upload, and complete the job."""
    export = _load_timeline_export(job_id)
    storage = get_r2_client()
    with tempfile.TemporaryDirectory(prefix=f"reelforge_timeline_{job_id}_") as temp_dir:
        temp = Path(temp_dir)
        source_path = temp / "source.mp4"
        output_path = temp / "timeline.mp4"
        storage.download_file(export["source_key"], str(source_path))
        with get_session() as session:
            JobRepository(session).set_progress(job_id, 35)
        _render_timeline(source_path, output_path, export["edl"], temp)
        with get_session() as session:
            JobRepository(session).set_progress(job_id, 80)
        result_key = f"jobs/{job_id}/timeline-export.mp4"
        storage.upload_file(str(output_path), result_key, "video/mp4")
        size_bytes = os.path.getsize(output_path)

    duration = float(export["edl"].get("output_duration_s") or 0.0)
    with get_session() as session:
        repository = JobRepository(session)
        AssetRepository(session).create(
            user_id=export["user_id"],
            job_id=job_id,
            kind="final",
            r2_key=result_key,
            content_type="video/mp4",
            size_bytes=size_bytes,
            duration_s=duration,
            meta=stamp_asset_from_params(
                {
                    "correlation_id": export["correlation_id"],
                    "source_job_id": export["source_job_id"],
                    "segments": len(export["edl"].get("segments") or []),
                    "overlays": len(export["edl"].get("overlays") or []),
                    "output_duration_s": duration,
                },
                export.get("source_params"),
            ),
        )
        repository.update_stage(job_id, EDITOR_EXPORT_STAGE, "complete")
        repository.mark_complete(job_id, result_key)
    return {"job_id": job_id, "result_key": result_key}


def run_export(job_id: str) -> dict[str, Any]:
    """Dispatch an export job to the right renderer by its persisted kind.

    ``editor_export`` -> single-range trim; ``editor_timeline_export`` -> the
    multi-segment EDL render. Keeps one Celery task entrypoint for both.
    """
    with get_session() as session:
        job = JobRepository(session).get(job_id)
        kind = getattr(job, "kind", "") if job is not None else ""
    if kind == TIMELINE_EXPORT_KIND:
        return run_editor_timeline_export(job_id)
    return run_editor_export(job_id)


def run_editor_export(job_id: str) -> dict[str, Any]:
    """Download, cut, upload, and complete one ``editor_export`` job."""
    export = _load_export(job_id)
    storage = get_r2_client()
    with tempfile.TemporaryDirectory(prefix=f"reelforge_editor_{job_id}_") as temp_dir:
        source_path = Path(temp_dir) / "source.mp4"
        output_path = Path(temp_dir) / "export.mp4"
        storage.download_file(export["source_key"], str(source_path))
        with get_session() as session:
            JobRepository(session).set_progress(job_id, 35)
        _render_cut(
            source_path,
            output_path,
            export["in_point"],
            export["out_point"],
        )
        with get_session() as session:
            JobRepository(session).set_progress(job_id, 80)
        result_key = f"jobs/{job_id}/editor-export.mp4"
        storage.upload_file(str(output_path), result_key, "video/mp4")
        size_bytes = os.path.getsize(output_path)

    duration = export["out_point"] - export["in_point"]
    with get_session() as session:
        repository = JobRepository(session)
        AssetRepository(session).create(
            user_id=export["user_id"],
            job_id=job_id,
            kind="final",
            r2_key=result_key,
            content_type="video/mp4",
            size_bytes=size_bytes,
            duration_s=duration,
            meta=stamp_asset_from_params(
                {
                    "correlation_id": export["correlation_id"],
                    "source_job_id": export["source_job_id"],
                    "in_point": export["in_point"],
                    "out_point": export["out_point"],
                },
                export.get("source_params"),
            ),
        )
        repository.update_stage(job_id, EDITOR_EXPORT_STAGE, "complete")
        repository.mark_complete(job_id, result_key)
    return {"job_id": job_id, "result_key": result_key}


__all__ = ["run_editor_export", "run_editor_timeline_export", "run_export"]
