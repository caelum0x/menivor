"""AI-content marking for every final MP4 (MN5).

Each reel the pipeline composes gets container metadata that says it was made
with AI, by which product, and which content id to quote in a takedown report
(``/legal/report``). The tag is written with a metadata-only remux
(``-map 0 -c copy``): the audio and video streams are copied bit for bit and
nothing is re-encoded.

What this is and is not: plain MP4 metadata (``comment``, ``ai_generated``,
``generator``, ``menivor_content_id`` and the IPTC digital-source-type term
``trainedAlgorithmicMedia``). It is not a signed C2PA manifest; anyone can
strip container metadata. The signed C2PA manifest is added on top by
:mod:`app.services.compose.provenance` (M7.1). Native publishes also set each platform's own AI
disclosure field (:func:`ai_flag_extra`, the Upload-Post form fields).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from loguru import logger

GENERATOR: str = "Menivor"
REPORT_URL: str = "https://menivor.com/legal/report"
#: IPTC NewsCodes digital-source-type term for media made by a trained model.
IPTC_DIGITAL_SOURCE_TYPE: str = "trainedAlgorithmicMedia"
REMUX_TIMEOUT_S: int = 120
_FTYP_KEYS: tuple[str, ...] = ("major_brand", "minor_version", "compatible_brands")


class ProvenanceError(RuntimeError):
    """The provenance tag could not be written or read."""


def provenance_tags(content_id: str) -> dict[str, str]:
    """The metadata written into a final MP4 for ``content_id`` (the job id)."""
    return {
        "comment": f"AI-generated with {GENERATOR}. Report misuse: {REPORT_URL} (id {content_id})",
        "ai_generated": "true",
        "generator": GENERATOR,
        "digital_source_type": IPTC_DIGITAL_SOURCE_TYPE,
        "menivor_content_id": str(content_id),
    }


def _binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:  # noqa: BLE001 - no ffmpeg at all
            raise ProvenanceError("ffmpeg is not installed on this server") from exc
    raise ProvenanceError(f"{name} is not installed on this server")


def tag(path: str, content_id: str) -> None:
    """Write the provenance tags into the MP4 at ``path`` in place (no re-encode).

    Raises :class:`ProvenanceError` when the file is missing or ffmpeg fails, so
    a reel is never delivered unmarked.
    """
    if not path or not os.path.isfile(path):
        raise ProvenanceError(f"no final video to tag at {path!r}")
    tmp = f"{path}.provenance.mp4"
    cmd = [_binary("ffmpeg"), "-v", "error", "-y", "-i", path, "-map", "0", "-c", "copy",
           "-movflags", "+faststart+use_metadata_tags"]
    # The brand fields live in the ftyp box; with use_metadata_tags they would
    # also be copied as mdta keys and pile up on every pass, so clear them.
    for key in _FTYP_KEYS:
        cmd += ["-metadata", f"{key}="]
    for key, value in provenance_tags(content_id).items():
        cmd += ["-metadata", f"{key}={value}"]
    cmd.append(tmp)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=REMUX_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _discard(tmp)
        raise ProvenanceError(f"provenance remux did not run: {exc}") from exc
    if proc.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        _discard(tmp)
        detail = proc.stderr.decode("utf-8", "replace")[-400:]
        raise ProvenanceError(f"provenance remux failed: {detail}")
    os.replace(tmp, path)


def _discard(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:  # pragma: no cover - best-effort cleanup
        pass


def read_tags(path: str) -> dict[str, str]:
    """The container tags of ``path`` (lower-cased keys), via ffprobe."""
    cmd = [_binary("ffprobe"), "-v", "error", "-show_entries", "format_tags", "-of", "json", path]
    proc = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    if proc.returncode != 0:
        raise ProvenanceError(proc.stderr.decode("utf-8", "replace")[-400:])
    tags = (json.loads(proc.stdout or b"{}").get("format") or {}).get("tags") or {}
    return {str(k).lower(): str(v) for k, v in tags.items()}


def is_tagged(path: str) -> bool:
    try:
        return read_tags(path).get("ai_generated") == "true"
    except ProvenanceError:
        return False


def tag_final(job_id: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Tag the composed final MP4 and replace the stored copy.

    ``ctx`` is the compose stage output (``final_video`` local path and
    ``final_key``). The local file is tagged and gets its signed C2PA manifest
    (M7.1, :mod:`app.services.compose.provenance`), then it is uploaded over the same R2
    key, before the job is marked complete. Returns ``ctx`` unchanged.
    """
    final_video = str(ctx.get("final_video") or "")
    final_key = str(ctx.get("final_key") or "")
    tag(final_video, job_id)
    _sign_content_credentials(job_id, final_video)
    if final_key:
        from app.services.storage.r2 import get_r2_client

        get_r2_client().upload_file(final_video, final_key, "video/mp4")
    logger.info(f"[{job_id}] provenance tag written to {final_key or final_video}")
    return ctx


def _sign_content_credentials(job_id: str, final_video: str) -> None:
    """Embed the signed C2PA manifest (M7.1) after the metadata remux.

    Runs last because any later remux would drop the manifest. A signing
    failure raises (the stage fails and refunds) while the layer is on.
    """
    from app.services.compose import provenance as content_credentials

    if not content_credentials.c2pa_enabled():
        return
    try:
        summary = content_credentials.sign_mp4(final_video, job_id)
    except content_credentials.ContentCredentialsError as exc:
        raise ProvenanceError(str(exc)) from exc
    logger.info(
        f"[{job_id}] C2PA manifest {summary.get('manifest_label')} signed "
        f"({summary.get('validation_state')}, trusted={summary.get('trusted')})"
    )


#: The disclosure each native publish sends (read by the platform connectors).
AI_FLAG_EXTRA_KEY: str = "ai_generated"


def ai_flag_extra(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """``extra`` with the AI-generated disclosure switched on (a new dict)."""
    return {**dict(extra or {}), AI_FLAG_EXTRA_KEY: True}


__all__ = [
    "AI_FLAG_EXTRA_KEY",
    "GENERATOR",
    "IPTC_DIGITAL_SOURCE_TYPE",
    "ProvenanceError",
    "REPORT_URL",
    "ai_flag_extra",
    "is_tagged",
    "provenance_tags",
    "read_tags",
    "tag",
    "tag_final",
]
