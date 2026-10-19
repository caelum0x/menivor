"""Film final export — stitch every rendered shot into one MP4 on R2.

``POST /film/projects/{id}/export`` validates that every shot is ``done`` with a
usable output ref, flips the project to ``export_state='queued'`` and enqueues
:func:`app.workers.tasks_film.export_film_task`, which calls
:func:`run_film_export` here:

1. load the ordered shots + their render jobs' output refs (one DB session);
2. download each shot clip to a temp dir (private R2 keys via the R2 client,
   public ``https`` URLs via a size-capped streamed GET — loopback / LAN hosts
   are rejected by :func:`app.services.render.outputs.classify_ref`);
3. probe every clip's audio stream. When all clips agree (same sample rate /
   channel count / codec, or all silent) concatenate with
   :func:`app.services.video.concat_video_clips_with_ffmpeg`; otherwise — or if
   the demuxer fails on mismatched geometry, or silently drops audio — use a
   normalising ``concat`` filtergraph: every clip is scaled+padded to the first
   clip's frame, every audio track is resampled to 48 kHz stereo, and clips with
   no audio get a generated silent track of their own length, so dialogue and
   sound from any shot survives into the final film;
4. upload the MP4 to ``films/<project_id>/final-<ts>.mp4`` (private) and record
   ``final_key`` + ``export_state='done'``; any failure records ``failed`` with
   the reason so the UI can offer a retry.

Exporting is free (local FFmpeg work) — shots were already paid for.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

from loguru import logger

from app.services.render.outputs import classify_ref, first_usable_key_or_url

#: Hard cap on a single downloaded shot (defence against a hostile/huge URL).
MAX_SHOT_BYTES = 512 * 1024 * 1024
_DOWNLOAD_TIMEOUT_S = 120


class FilmExportError(RuntimeError):
    """A user-presentable export failure."""


def shot_sources(session: Any, project_id: str) -> list[tuple[str, str, str]]:
    """Return ``[(shot_key, kind, value)]`` for every shot, in order.

    Raises :class:`FilmExportError` naming the first shot that is not done or
    has no usable output, so the route can answer 409 with a precise reason.
    """
    from app.domains.film.repository import FilmRepository
    from app.models.db.render_repo import RenderJobRepository, row_to_envelope

    shots = FilmRepository(session).shots(project_id)
    if not shots:
        raise FilmExportError("this film has no shots")
    renders = RenderJobRepository(session)
    sources: list[tuple[str, str, str]] = []
    for shot in shots:
        if shot.status != "done" or not shot.render_job_id:
            raise FilmExportError(f"shot {shot.shot_key} is not rendered yet ({shot.status})")
        row = renders.get(shot.render_job_id)
        if row is None or str(row.state) != "COMPLETED":
            raise FilmExportError(f"shot {shot.shot_key} has no completed render")
        usable = first_usable_key_or_url(row_to_envelope(row).output_refs)
        if usable is None:
            raise FilmExportError(
                f"shot {shot.shot_key} has no downloadable output; re-render it"
            )
        sources.append((shot.shot_key, usable[0], usable[1]))
    return sources


def _download_url(url: str, dest: str) -> None:
    kind, value = classify_ref(url)
    if kind != "url":
        raise FilmExportError("shot output URL is not publicly reachable")
    import requests

    total = 0
    with requests.get(value, stream=True, timeout=_DOWNLOAD_TIMEOUT_S, allow_redirects=False) as resp:
        if resp.status_code != 200:
            raise FilmExportError(f"shot download failed (HTTP {resp.status_code})")
        with open(dest, "wb") as fp:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_SHOT_BYTES:
                    raise FilmExportError("shot output is too large to export")
                fp.write(chunk)


def _download(kind: str, value: str, dest: str, r2: Any) -> None:
    if kind == "key":
        if r2 is None:
            raise FilmExportError("storage is not configured")
        r2.download_file(value, dest)
    else:
        _download_url(value, dest)
    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        raise FilmExportError("downloaded shot is empty")


#: Normalised audio format for the fallback concat (AAC-friendly, broadcast rate).
_AUDIO_RATE = 48000
_AUDIO_LAYOUT = "stereo"
_AUDIO_BITRATE = "192k"


def _probe_audio(path: str) -> tuple[str, int, int] | None:
    """Return ``(codec, sample_rate, channels)`` of the first audio stream.

    ``None`` means the clip has no audio stream. A probe failure raises
    :class:`RuntimeError` so the caller never mistakes "unknown" for "silent".
    """
    import json

    from app.services.compose.compose_ffmpeg import _get_ffprobe_binary

    result = subprocess.run(
        [
            _get_ffprobe_binary(),
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,sample_rate,channels",
            "-of", "json",
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed for shot audio: {(result.stderr or '').strip()[:200]}"
        )
    try:
        streams = (json.loads(result.stdout or "{}") or {}).get("streams") or []
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"could not parse ffprobe audio json: {exc}") from exc
    if not streams:
        return None
    stream = streams[0]
    try:
        rate = int(stream.get("sample_rate") or 0)
    except (TypeError, ValueError):
        rate = 0
    try:
        channels = int(stream.get("channels") or 0)
    except (TypeError, ValueError):
        channels = 0
    return (str(stream.get("codec_name") or ""), rate, channels)


def _probe_audio_safe(path: str) -> tuple[str, int, int] | None | bool:
    """Like :func:`_probe_audio` but returns ``False`` when probing failed."""
    try:
        return _probe_audio(path)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning(f"film export audio probe failed for {path!r}: {exc}")
        return False


def _concat_normalized(
    clips: list[str],
    out_path: str,
    audio: list[tuple[str, int, int] | None | bool] | None = None,
) -> None:
    """Fallback concat: normalise video geometry AND audio so both survive.

    Video: scale/pad every clip to the first clip's geometry, pin SAR/fps/pixfmt.
    Audio: resample every real track to 48 kHz stereo float; a clip with no audio
    (or whose probe failed) gets a generated ``anullsrc`` silent track sized to
    its own duration, so the ``concat`` filter sees ``v=1:a=1`` for every segment
    and later shots' audio stays in sync. If no clip has audio the output stays
    video-only (no pointless silent track).
    """
    from app.services.compose.compose_ffmpeg import _probe_video, _run_ffmpeg
    from app.utils import utils

    if audio is None:
        audio = [_probe_audio_safe(clip) for clip in clips]
    has_any_audio = any(isinstance(item, tuple) for item in audio)

    info = _probe_video(clips[0])
    width = (info.width if info and info.width else 1280) // 2 * 2
    height = (info.height if info and info.height else 720) // 2 * 2
    fps = int(round(info.fps)) if info and info.fps and info.fps > 0 else 24

    command = [utils.get_ffmpeg_binary(), "-y"]
    for clip in clips:
        command += ["-i", clip]

    nodes: list[str] = []
    joined: list[str] = []
    next_input = len(clips)
    for idx, clip in enumerate(clips):
        nodes.append(
            f"[{idx}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{idx}]"
        )
        joined.append(f"[v{idx}]")
        if not has_any_audio:
            continue
        clip_info = info if idx == 0 else _probe_video(clip)
        duration = clip_info.duration if clip_info and clip_info.duration > 0 else 0.0
        trim = f",atrim=0:{duration:.3f},asetpts=PTS-STARTPTS" if duration > 0 else ""
        if isinstance(audio[idx], tuple):
            source = f"[{idx}:a:0]"
        else:
            # Silent bed for a clip without audio, exactly as long as its video.
            command += [
                "-f", "lavfi",
                "-t", f"{duration if duration > 0 else 0.1:.3f}",
                "-i", f"anullsrc=r={_AUDIO_RATE}:cl={_AUDIO_LAYOUT}",
            ]
            source = f"[{next_input}:a]"
            next_input += 1
        nodes.append(
            f"{source}aresample={_AUDIO_RATE},"
            f"aformat=sample_fmts=fltp:sample_rates={_AUDIO_RATE}:channel_layouts={_AUDIO_LAYOUT}"
            f"{trim}[a{idx}]"
        )
        joined.append(f"[a{idx}]")

    count = len(clips)
    if has_any_audio:
        graph = ";".join(nodes) + f";{''.join(joined)}concat=n={count}:v=1:a=1[vout][aout]"
        maps = ["-map", "[vout]", "-map", "[aout]", "-c:a", "aac", "-b:a", _AUDIO_BITRATE]
    else:
        graph = ";".join(nodes) + f";{''.join(joined)}concat=n={count}:v=1:a=0[vout]"
        maps = ["-map", "[vout]"]
    command += ["-filter_complex", graph, *maps]
    command += [
        "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", out_path,
    ]
    _run_ffmpeg(command)


def _audio_uniform(audio: list[tuple[str, int, int] | None | bool]) -> bool:
    """True when the concat demuxer can carry audio losslessly across clips."""
    if any(item is False for item in audio):
        return False
    return len(set(audio)) == 1


def _geometry_uniform(clips: list[str]) -> bool:
    """True when every clip probes to the same frame size (demuxer-safe)."""
    from app.services.compose.compose_ffmpeg import _probe_video

    sizes = set()
    for clip in clips:
        info = _probe_video(clip)
        if info is None or not info.width or not info.height:
            return False
        sizes.add((info.width, info.height))
    return len(sizes) == 1


def _stitch(clips: list[str], out_path: str, work_dir: str) -> None:
    if len(clips) == 1:
        shutil.copy2(clips[0], out_path)
        return
    from app.services.video import concat_video_clips_with_ffmpeg

    audio = [_probe_audio_safe(clip) for clip in clips]
    expects_audio = any(isinstance(item, tuple) for item in audio)
    if _audio_uniform(audio) and _geometry_uniform(clips):
        # Same audio layout everywhere (or all silent): the demuxer keeps the
        # first file's stream layout, which is then correct for every clip.
        try:
            concat_video_clips_with_ffmpeg(clips, out_path, threads=2, output_dir=work_dir)
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                if not expects_audio or _probe_audio_safe(out_path):
                    return
                logger.warning("film export demuxer concat dropped audio, normalising")
        except Exception as exc:  # noqa: BLE001 - fall back to the normalising concat
            logger.warning(f"film export demuxer concat failed, normalising: {exc}")
    else:
        logger.info("film export: shot audio/geometry differs across clips, normalising")
    _concat_normalized(clips, out_path, audio)


def run_film_export(project_id: str) -> dict:
    """Worker body: stitch + upload + record. Never raises (records failure)."""
    from app.domains.film.repository import FilmRepository
    from app.models.db.base import get_session

    user_id = ""
    title = ""
    try:
        with get_session() as session:
            repo = FilmRepository(session)
            project = repo.get(project_id)
            if project is None:
                return {"ok": False, "error": "project not found"}
            user_id, title = str(project.user_id), str(project.title or "")
            sources = shot_sources(session, project_id)
            repo.set_export(project_id, state="running")
    except FilmExportError as exc:
        _record_failure(project_id, str(exc), user_id, title)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - never crash the worker
        logger.error(f"film export setup failed for {project_id}: {exc}")
        _record_failure(project_id, "export could not start", user_id, title)
        return {"ok": False, "error": "export could not start"}

    work_dir = tempfile.mkdtemp(prefix=f"film-{project_id[:12]}-")
    try:
        r2 = None
        if any(kind == "key" for _, kind, _ in sources):
            from app.platform.storage.r2 import get_r2_client

            r2 = get_r2_client()
        clips: list[str] = []
        for idx, (shot_key, kind, value) in enumerate(sources):
            dest = os.path.join(work_dir, f"shot_{idx:03d}.mp4")
            try:
                _download(kind, value, dest, r2)
            except FilmExportError as exc:
                raise FilmExportError(f"shot {shot_key}: {exc}") from exc
            clips.append(dest)
        out_path = os.path.join(work_dir, "final.mp4")
        _stitch(clips, out_path, work_dir)
        if r2 is None:
            from app.platform.storage.r2 import get_r2_client

            r2 = get_r2_client()
        key = f"films/{project_id}/final-{int(time.time())}.mp4"
        r2.put_file(out_path, key, content_type="video/mp4")
    except FilmExportError as exc:
        _record_failure(project_id, str(exc), user_id, title)
        return {"ok": False, "error": str(exc)}
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        logger.error(f"film export failed for {project_id}: {exc}")
        _record_failure(project_id, "video stitching failed", user_id, title)
        return {"ok": False, "error": "video stitching failed"}
    except Exception as exc:  # noqa: BLE001 - never crash the worker
        logger.error(f"film export failed for {project_id}: {exc}")
        _record_failure(project_id, "export failed", user_id, title)
        return {"ok": False, "error": "export failed"}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    previous_key = ""
    with get_session() as session:
        repo = FilmRepository(session)
        project = repo.get(project_id)
        if project is None:  # deleted while exporting — drop the orphan object
            _best_effort_delete(key)
            return {"ok": False, "error": "project deleted during export"}
        previous_key = str(project.final_key or "")
        repo.set_export(project_id, state="done", final_key=key)
    if previous_key and previous_key != key:
        _best_effort_delete(previous_key)
    _notify(user_id, project_id, ok=True, title=title)
    return {"ok": True, "final_key": key}


def _best_effort_delete(key: str) -> None:
    try:
        from app.platform.storage.r2 import get_r2_client

        get_r2_client().delete_object(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"film export cleanup failed for {key!r}: {exc}")


def _record_failure(project_id: str, error: str, user_id: str, title: str) -> None:
    try:
        from app.domains.film.repository import FilmRepository
        from app.models.db.base import get_session

        with get_session() as session:
            FilmRepository(session).set_export(project_id, state="failed", error=error)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"film export failure record failed for {project_id}: {exc}")
    if user_id:
        _notify(user_id, project_id, ok=False, title=title, error=error)


def _notify(user_id: str, project_id: str, *, ok: bool, title: str, error: str = "") -> None:
    try:
        from app.services.notifications import notify_film_export

        notify_film_export(user_id, project_id, ok=ok, title=title, error=error)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"film export notify failed for {project_id}: {exc}")
