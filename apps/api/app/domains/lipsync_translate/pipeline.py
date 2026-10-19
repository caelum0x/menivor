"""Lip-sync translation: transcript -> translate (Relay) -> TTS with the actor's designed voice ->
lip-sync (Kling or InfiniteTalk) -> burned captions.

* :func:`plan` checks ownership and the voice rule, prices every language and stores
  one ``planned`` studio render ($0). Approval in the approvals feed spends.
* :func:`run_plan` is the worker body. Every external step is a field of
  :class:`PipelineDeps`, so tests run the whole chain with fakes.

Voice rule: the voice is always one of OUR designed voices (an AI actor's ElevenLabs
Voice Design id). A voice that is not a designed actor voice is refused, no reference
audio is ever accepted, and nothing here clones a real person's voice.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from app.domains.lipsync_translate import engines, languages

FORBIDDEN_KEYS = ("voice_sample", "reference_audio", "sample_url", "clone_from")
MAX_SECONDS = 120
_JSON_ARRAY = re.compile(r"\[[\s\S]*\]")


class TranslateError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# --------------------------------------------------------------------------- plan ($0)
def _owned_video(session: Any, user_id: str, url: str) -> bool:
    from sqlalchemy import select

    from app.domains.brand_agent.models import AgentLibraryItem
    from app.domains.studio_render.models import StudioRender

    if session.execute(select(AgentLibraryItem.id).where(AgentLibraryItem.user_id == user_id,
                                                         AgentLibraryItem.kind == "video",
                                                         AgentLibraryItem.url == url)).first():
        return True
    for row in session.execute(select(StudioRender).where(StudioRender.user_id == user_id,
                                                          StudioRender.status == "done")).scalars():
        result = row.result or {}
        if result.get("video_url") == url or any(o.get("video_url") == url for o in result.get("outputs") or []):
            return True
    return False


def plan(session: Any, user_id: str, *, video_url: str, actor_id: str, targets: list[str], seconds: float,
         source_language: str = "en", engine: str = "kling", captions: bool = True, transcript: str = "",
         options: Mapping[str, Any] | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    from app.domains.actors.service import ActorError, get as get_actor
    from app.domains.studio_render import service as renders
    from app.domains.studio_render.models import KIND_LIPSYNC

    if any(k in (options or {}) for k in FORBIDDEN_KEYS):
        raise TranslateError("Voices are never cloned from audio; pick one of your AI actors' designed voices.", 422)
    url = str(video_url or "").strip()
    if not url.startswith("https://") or not _owned_video(session, user_id, url):
        raise TranslateError("Pick one of your own Menivor videos to translate.", 422)
    try:
        actor = get_actor(session, user_id, actor_id)
    except ActorError as exc:
        raise TranslateError(exc.message, exc.status_code) from exc
    if not actor.voice_id or (actor.provenance or {}).get("voice") != "designed":
        raise TranslateError(f"Design and lock a voice for {actor.name} first (Actors > Voice).", 409)
    wanted = [t for t in dict.fromkeys(str(t).strip().lower() for t in targets) if t in languages.LANGUAGES]
    wanted = [t for t in wanted if t != source_language][:languages.MAX_TARGETS]
    if not wanted:
        raise TranslateError("Pick at least one target language.", 422)
    if engine not in engines.ENGINES:
        raise TranslateError("Pick Kling or InfiniteTalk for lip-sync.", 422)
    secs = max(1.0, min(float(seconds), MAX_SECONDS))
    chars = len(transcript) if transcript.strip() else int(secs * engines.CHARS_PER_SECOND)
    per_lang = round(engines.tts_usd(int(chars * 1.15), env) + engines.lipsync_usd(engine, secs), 4)
    usd = round(per_lang * len(wanted), 4)
    body = {"kind": KIND_LIPSYNC, "video_url": url, "seconds": secs, "source_language": source_language,
            "targets": [{"code": t, "label": languages.label(t)} for t in wanted], "actor_id": actor.id,
            "actor_name": actor.name, "voice_id": actor.voice_id, "engine": engine, "captions": bool(captions),
            "transcript": transcript.strip()[:8000], "usd": usd, "usd_per_language": per_lang,
            "output_prefix": f"studio/lipsync/{uuid.uuid4().hex}",
            "steps": ["transcript", "translate (Relay)", "designed-voice TTS", f"lip-sync ({engine})",
                      "burned captions" if captions else "no captions"],
            "engine_configured": engines.configured(engine, env)}
    title = f"Translate to {', '.join(languages.label(t) for t in wanted)} ({actor.name}'s voice)"
    return renders.create(session, user_id, kind=KIND_LIPSYNC, title=title[:300], plan=body, quote_usd=usd)


# --------------------------------------------------------------------------- run (after approval)
@dataclass
class PipelineDeps:
    fetch: Callable[[str, str], str]                       # (url, dest) -> local path
    transcribe: Callable[[str, str], list[dict]]           # (path, language) -> [{start, end, text}]
    translate: Callable[[list[str], str], list[str]]       # (lines, language label) -> lines
    tts: Callable[[str, str, str], str]                    # (voice_id, text, out_path) -> path
    lipsync: Callable[..., str]                            # (video_url=, audio=, seconds=) -> url
    burn: Callable[[str, list[dict], str], str]            # (video_path, cues, out_path) -> path
    upload: Callable[[str, str, str], None]                # (path, key, content_type)
    media_url: Callable[[str], str]                        # key -> url


def parse_lines(raw: str, expected: int) -> list[str]:
    match = _JSON_ARRAY.search(raw or "")
    if not match:
        raise TranslateError("The translation came back in the wrong shape.")
    try:
        lines = [str(x).strip() for x in json.loads(match.group(0))]
    except ValueError as exc:
        raise TranslateError("The translation came back in the wrong shape.") from exc
    if len(lines) != expected or not all(lines):
        raise TranslateError("The translation lost or merged lines.")
    return lines


def translate_prompt(lines: list[str], language: str) -> str:
    return (f"Translate each line of this ad voiceover into {language}. Keep the meaning, tone and a similar "
            "spoken length so it fits the same lip movements. Keep product and brand names unchanged. Return only "
            f"a JSON array of {len(lines)} strings, one per line, in order.\n\n" + json.dumps(lines, ensure_ascii=False))


def relay_translate(lines: list[str], language: str) -> list[str]:
    from app.domains.adclone.relay_writer import relay_llm

    llm = relay_llm()
    if llm is None:
        raise TranslateError("Translation runs through Relay, which is not configured on this server.", 409)
    return parse_lines(llm(translate_prompt(lines, language)), len(lines))


def cues_for(lines: list[str], duration: float) -> list[dict]:
    """Caption cues spread over the dubbed video by text length."""
    total = sum(max(len(t), 1) for t in lines) or 1
    out, t = [], 0.0
    for text in lines:
        span = duration * max(len(text), 1) / total
        out.append({"start": round(t, 2), "end": round(t + span, 2), "text": text})
        t += span
    return out


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(cues: list[dict], path: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            f.write(f"{i}\n{_srt_time(c['start'])} --> {_srt_time(c['end'])}\n{c['text']}\n\n")
    return path


def ffmpeg_burn(video: str, cues: list[dict], out: str) -> str:
    srt = write_srt(cues, os.path.splitext(out)[0] + ".srt")
    style = "FontName=Inter,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,Outline=2,MarginV=60"
    escaped = srt.replace("\\", "/").replace(":", r"\:")
    args = ["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", f"subtitles='{escaped}':force_style='{style}'",
            "-c:a", "copy", out]
    done = subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603 - fixed argv
    if done.returncode != 0:
        raise TranslateError("Could not burn the captions.")
    return out


def default_deps(plan_: Mapping[str, Any]) -> PipelineDeps:
    from app.domains.adclone.elevenlabs import ElevenLabs
    from app.domains.adclone.vision import transcribe as whisper
    from app.domains.film.story8_tasks import r2_upload
    from app.domains.gallery.service import media_url

    voice = ElevenLabs.from_env()
    lipsync = engines.make_lipsync(str(plan_["engine"]), cap_usd=round(float(plan_.get("usd") or 0) * 1.05 + 0.05, 4))

    def fetch(url: str, dest: str) -> str:
        from app.domains.adstudio.fetch import safe_get

        with open(dest, "wb") as f:
            f.write(safe_get(url, max_bytes=300 * 1024 * 1024, accept="video/*").body)
        return dest

    def transcribe(path: str, language: str) -> list[dict]:
        found = whisper(path, language=language or None)
        if found is None:
            raise TranslateError("No speech model on this worker; send the transcript with the plan.")
        segs, _lang = found
        return [{"start": s.start_s, "end": s.end_s, "text": s.text} for s in segs]

    return PipelineDeps(fetch=fetch, transcribe=transcribe, translate=relay_translate,
                        tts=lambda v, text, out: voice.tts(voice_id=v, text=text, out_path=out),
                        lipsync=lipsync, burn=ffmpeg_burn, upload=r2_upload, media_url=media_url)


def _lines(plan_: Mapping[str, Any], deps: PipelineDeps, video_path: str) -> list[str]:
    given = str(plan_.get("transcript") or "").strip()
    if given:
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", given) if s.strip()]
    lines = [str(s.get("text") or "").strip() for s in deps.transcribe(video_path, str(plan_.get("source_language")))]
    lines = [t for t in lines if t]
    if not lines:
        raise TranslateError("No speech was found in this video.")
    return lines


def run_plan(plan_: Mapping[str, Any], *, deps: PipelineDeps | None = None) -> dict[str, Any]:
    if any(k in plan_ for k in FORBIDDEN_KEYS):
        raise TranslateError("Voices are never cloned from audio.", 422)
    d = deps or default_deps(plan_)
    root = tempfile.mkdtemp(prefix="lipsync-")
    try:
        source = d.fetch(str(plan_["video_url"]), os.path.join(root, "source.mp4"))
        lines = _lines(plan_, d, source)
        outputs = []
        for target in plan_["targets"]:
            code, label = target["code"], target["label"]
            translated = d.translate(lines, label)
            audio_path = d.tts(str(plan_["voice_id"]), " ".join(translated), os.path.join(root, f"{code}.mp3"))
            with open(audio_path, "rb") as f:
                audio = f.read()
            synced_url = d.lipsync(video_url=str(plan_["video_url"]), audio=audio, seconds=float(plan_["seconds"]))
            synced = d.fetch(synced_url, os.path.join(root, f"{code}-synced.mp4"))
            final = synced
            if plan_.get("captions", True):
                final = d.burn(synced, cues_for(translated, float(plan_["seconds"])),
                               os.path.join(root, f"{code}-final.mp4"))
            key = f"{plan_['output_prefix']}/{code}.mp4"
            d.upload(final, key, "video/mp4")
            outputs.append({"code": code, "label": label, "video_url": d.media_url(key), "lines": translated,
                            "captions": bool(plan_.get("captions", True))})
        return {"outputs": outputs, "source_lines": lines, "voice": "designed actor voice", "engine": plan_["engine"]}
    finally:
        shutil.rmtree(root, ignore_errors=True)


__all__ = ["FORBIDDEN_KEYS", "PipelineDeps", "TranslateError", "cues_for", "parse_lines", "plan", "relay_translate",
           "run_plan", "translate_prompt", "write_srt"]
