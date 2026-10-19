"""The AI panel run for one title (MV16): transcript, subtitles, chapters, metadata and dubs.

Runs on the worker (CPU tier 3). Speech to text is faster-whisper on CPU (the
existing BYOV stack); every LLM call goes through Relay; speech is edge-tts.
Files land next to the title's packaged HLS so the tokenized stream path
serves them, and the master playlist gains the new renditions. Media minutes
processed are metered as AI minutes (MV7).
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.ott.models import OttChannel, OttTitle

from . import audio_tracks, chapters, metadata, subtitles
from .models import DONE, FAILED, KINDS, QUEUED, OttAiOutput
from .subtitles import Cue

REQUESTABLE = ("subtitles", "chapters", "metadata", "dub")


class AiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class Store:
    """Read and write objects in the OTT bucket (the packaged title lives there)."""

    def __init__(self) -> None:
        from app.services.ott_transcode.uploads import R2Storage

        self._r2 = R2Storage()

    def read(self, key: str) -> bytes:
        return self._r2.read(key)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._r2._s3.put_object(Bucket=self._r2._bucket, Key=key, Body=data, ContentType=content_type)

    def source_url(self, source_key: str) -> str:
        from app.services.ott_transcode.router import storage

        return storage().presign_get(source_key, 6 * 3600)


@dataclass
class Deps:
    store: Any = None
    transcribe: Optional[Callable[[str, str], list]] = None
    llm: Optional[Callable[[str], str]] = None
    speak: Optional[Callable[[str, str, str], None]] = None
    download: Optional[Callable[[str, str], None]] = None
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    api_base: str = ""
    minutes_used: list = field(default_factory=list)


def _download(url: str, path: str) -> None:
    import urllib.request

    with urllib.request.urlopen(url, timeout=600) as response, open(path, "wb") as out:  # noqa: S310
        while chunk := response.read(1 << 20):
            out.write(chunk)


def _transcribe(audio_path: str, language: str) -> list:
    from app.services.transcribe import transcribe_to_words

    return transcribe_to_words(audio_path, language=language)


def _output(session: Session, title_id: str, kind: str, language: str = "") -> OttAiOutput:
    row = session.execute(select(OttAiOutput).where(OttAiOutput.title_id == title_id, OttAiOutput.kind == kind,
                                                    OttAiOutput.language == language)).scalar_one_or_none()
    if row is None:
        row = OttAiOutput(title_id=title_id, kind=kind, language=language, status=QUEUED, data={})
        session.add(row)
        session.flush()
    return row


def queue(session: Session, title: OttTitle, kinds: Sequence[str], languages: Sequence[str],
          source_language: str) -> list[OttAiOutput]:
    from app.services.ott_package.tracks import check_language

    wanted = [k for k in kinds if k in REQUESTABLE]
    if not wanted:
        raise AiError(400, "kinds", f"choose from {', '.join(REQUESTABLE)}")
    try:
        check_language(source_language)
        langs = [check_language(x) for x in dict.fromkeys(languages)]
    except ValueError as exc:
        raise AiError(400, "language", str(exc)) from exc
    if any(k in ("subtitles", "dub") for k in wanted) and not title.manifest_key:
        raise AiError(409, "not_packaged", "Package the title first; subtitles and dubs attach to its stream.")
    if "dub" in wanted:
        missing = [x for x in langs if x != source_language and x not in audio_tracks.EDGE_VOICES]
        if missing:
            raise AiError(400, "voice", f"no voice yet for {', '.join(missing)}")
    rows = [_output(session, title.id, "transcript", source_language)]
    for kind in wanted:
        if kind in ("subtitles", "dub"):
            targets = langs if kind == "dub" else [source_language, *[x for x in langs if x != source_language]]
            rows += [_output(session, title.id, kind, x) for x in targets if not (kind == "dub" and x == source_language)]
        else:
            rows.append(_output(session, title.id, kind, source_language if kind == "chapters" else ""))
    for row in rows:
        if row.status != DONE or row.kind != "transcript":
            row.status, row.error = QUEUED, ""
    session.flush()
    return rows


def _cues(row: OttAiOutput) -> list[Cue]:
    return [Cue(float(s), float(e), str(t)) for s, e, t in (row.data or {}).get("cues", [])]


def _prefix(title: OttTitle) -> str:
    return title.manifest_key.rsplit("/", 1)[0]


def _update_master(deps: Deps, title: OttTitle, edit: Callable[[str], str]) -> None:
    key = title.manifest_key
    master = deps.store.read(key).decode("utf-8")
    deps.store.put(key, edit(master).encode("utf-8"), "application/vnd.apple.mpegurl")


def transcript(session: Session, title: OttTitle, language: str, deps: Deps) -> list[Cue]:
    row = _output(session, title.id, "transcript", language)
    if row.status == DONE and (row.data or {}).get("cues"):
        return _cues(row)
    with tempfile.TemporaryDirectory(prefix="ott-ai-") as work:
        src = os.path.join(work, "source")
        (deps.download or _download)(deps.store.source_url(title.source_key), src)
        wav = os.path.join(work, "audio.wav")
        audio_tracks._run([deps.ffmpeg, "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", wav])
        words = (deps.transcribe or _transcribe)(wav, language)
    cues = subtitles.cues_from_words(words)
    if not cues:
        raise AiError(422, "no_speech", "There is no speech in this title.")
    row.data = {"cues": [[c.start, c.end, c.text] for c in cues]}
    row.status = DONE
    deps.minutes_used.append(float(title.duration_s or cues[-1].end) / 60)
    session.flush()
    return cues


def _subtitles(session: Session, title: OttTitle, cues: list[Cue], language: str, source: str, deps: Deps
               ) -> list[Cue]:
    lines = cues if language == source else subtitles.translate(cues, language, llm=deps.llm)
    prefix = _prefix(title)
    deps.store.put(f"{prefix}/subs/{language}.vtt", subtitles.to_vtt(lines).encode("utf-8"), "text/vtt")
    deps.store.put(f"{prefix}/subs/{language}.m3u8",
                   subtitles.media_playlist(f"{language}.vtt", float(title.duration_s or lines[-1].end)).encode(),
                   "application/vnd.apple.mpegurl")
    name = subtitles.LANGUAGE_NAMES.get(language, language)
    _update_master(deps, title, lambda m: subtitles.add_rendition(
        m, kind="SUBTITLES", group=subtitles.GROUP, language=language, name=name, uri=f"subs/{language}.m3u8"))
    row = _output(session, title.id, "subtitles", language)
    row.key, row.status, row.data = f"{prefix}/subs/{language}.vtt", DONE, {"cues": len(lines)}
    session.flush()
    return lines


def _dub(session: Session, title: OttTitle, lines: list[Cue], language: str, deps: Deps) -> None:
    from app.services.ott_transcode import service as transcode

    protection = transcode.protection_for(session, title, deps.api_base) if title.access_tier != "free" else None
    prefix = _prefix(title)
    with tempfile.TemporaryDirectory(prefix="ott-dub-") as work:
        track = audio_tracks.build(lines, language, total_s=float(title.duration_s or lines[-1].end),
                                   work=os.path.join(work, "clips"), ffmpeg=deps.ffmpeg, ffprobe=deps.ffprobe,
                                   speak=deps.speak)
        out = os.path.join(work, "hls")
        os.makedirs(out)
        playlist = audio_tracks.package(track, out, language=language, ffmpeg=deps.ffmpeg, protection=protection)
        for root, _dirs, files in os.walk(out):
            for name in files:
                path = os.path.join(root, name)
                rel = os.path.relpath(path, out)
                kind = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp4"
                with open(path, "rb") as handle:
                    deps.store.put(f"{prefix}/{rel}", handle.read(), kind)
    name = subtitles.LANGUAGE_NAMES.get(language, language)
    _update_master(deps, title, lambda m: subtitles.add_rendition(
        m, kind="AUDIO", group=audio_tracks.GROUP, language=language, name=name, uri=playlist))
    row = _output(session, title.id, "dub", language)
    row.key, row.status = f"{prefix}/{playlist}", DONE
    deps.minutes_used.append(float(title.duration_s or lines[-1].end) / 60)
    session.flush()


def run(session: Session, title: OttTitle, source_language: str, deps: Deps) -> dict[str, Any]:
    """Process every queued output of ``title``; each failure is recorded on its own row."""
    pending = session.execute(select(OttAiOutput).where(OttAiOutput.title_id == title.id,
                                                        OttAiOutput.status == QUEUED)).scalars().all()
    kinds = {(r.kind, r.language) for r in pending}
    try:
        cues = transcript(session, title, source_language, deps)
    except Exception as exc:  # noqa: BLE001 - recorded on every waiting row
        for row in pending:
            row.status, row.error = FAILED, str(exc)[:500]
        session.flush()
        return {"done": 0, "failed": len(pending)}
    translated: dict[str, list[Cue]] = {}
    for kind, language in sorted(kinds, key=lambda k: KINDS.index(k[0])):
        row = _output(session, title.id, kind, language)
        try:
            if kind == "subtitles":
                translated[language] = _subtitles(session, title, cues, language, source_language, deps)
            elif kind == "chapters":
                chosen = chapters.choose(subtitles.sentences(cues), llm=deps.llm)
                key = f"{_prefix(title)}/chapters.vtt" if title.manifest_key else ""
                if key:
                    deps.store.put(key, chapters.to_vtt(chosen).encode("utf-8"), "text/vtt")
                row.key, row.status, row.data = key, DONE, {"chapters": chosen}
            elif kind == "metadata":
                row.data, row.status = metadata.suggest(cues, current_title=title.title, llm=deps.llm), DONE
            elif kind == "dub":
                lines = translated.get(language) or subtitles.translate(cues, language, llm=deps.llm)
                _dub(session, title, lines, language, deps)
        except Exception as exc:  # noqa: BLE001 - one failed language never stops the others
            logger.warning(f"ott ai {title.id} {kind}/{language} failed: {exc}")
            row.status, row.error = FAILED, str(exc)[:500]
        session.flush()
    channel = session.get(OttChannel, title.channel_id)
    minutes = round(sum(deps.minutes_used), 2)
    if minutes and channel is not None:
        from app.services.billing import ott_usage

        ott_usage.count_ai_minutes(str(channel.user_id), minutes)
    rows = session.execute(select(OttAiOutput).where(OttAiOutput.title_id == title.id)).scalars().all()
    return {"done": sum(1 for r in rows if r.status == DONE), "failed": sum(1 for r in rows if r.status == FAILED),
            "ai_minutes": minutes}


def view(session: Session, title: OttTitle) -> dict[str, Any]:
    rows = session.execute(select(OttAiOutput).where(OttAiOutput.title_id == title.id)).scalars().all()
    out: dict[str, Any] = {"title_id": title.id, "outputs": []}
    for row in rows:
        entry = {"kind": row.kind, "language": row.language, "status": row.status, "error": row.error}
        if row.kind == "chapters":
            entry["chapters"] = (row.data or {}).get("chapters", [])
        if row.kind == "metadata":
            entry["suggestion"] = row.data or {}
        out["outputs"].append(entry)
    return out


__all__ = ["AiError", "Deps", "REQUESTABLE", "Store", "queue", "run", "transcript", "view"]
