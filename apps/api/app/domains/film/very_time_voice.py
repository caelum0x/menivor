"""Voice takes for the Very ___ Time payoff line: Eleven v3 with delivery tags, or the free chain.

* **eleven_v3** (premium): ``count`` takes of the line with the delivery's audio
  tags (``[deadpan] [flatly] ...``), seeds 1..count so each take differs and can
  be reproduced. With a reply line both voices are rendered in one Text to
  Dialogue call (host voice, then the reply voice).
  When ElevenLabs is not configured the premium engine runs on Replicate
  (MiniMax Speech 02 HD, :mod:`app.services.tts.replicate_speech`): takes differ
  by speed (0.96 / 1.0 / 1.03) and a reply is a second voice after 0.35 s.
  :func:`premium_backend` says which one is live.
* **free**: the existing free chain (Kokoro first when configured, edge-tts
  kept), one take per speaking rate (0.92 / 0.96 / 1.0). With a reply line a
  second, different free voice says it after 0.35 s of silence.

The take picker: :func:`flatness` scores each take (lower = flatter, the
deadpan we want) and :func:`pick` chooses the flattest one that is not too long.
``POST /film/very-time/takes`` lets the user listen and choose before paying;
it is house-paid and rate-limited, and it runs the template guard-rail before
any voice call. The worker uses :func:`take_for_job`: the chosen take when the
user picked one (ownership checked by its key), else fresh takes and the pick.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from fastapi import Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.services.tts import eleven_v3, replicate_speech
from app.services.tts.eleven_v3 import DELIVERY_TAGS
from app.utils import utils

from . import story8, story8_render as render, very_time

router = new_router()

ENGINE_FREE = "free"
ENGINE_ELEVEN = "eleven_v3"
ENGINES = (ENGINE_FREE, ENGINE_ELEVEN)
DELIVERIES = tuple(DELIVERY_TAGS)
MIN_TAKES, MAX_TAKES = 1, 3
MAX_REPLY = 140
TAKES_PREFIX = "vt-takes"
FREE_RATES = (0.92, 0.96, 1.0)
REPLY_GAP_S = 0.35
REPLICATE_SPEEDS = (0.96, 1.0, 1.03)
BACKEND_ELEVEN, BACKEND_REPLICATE = "elevenlabs", "replicate"
RATE_LIMIT, RATE_WINDOW_S = 12, 3600
SAMPLE_RATE = 16_000
FRAME_S = 0.05
# Free reply voices: a different edge-tts voice from the host's (formats.free_voice_for is female).
FREE_REPLY_VOICES = {
    "en": "en-US-GuyNeural-Male", "tr": "tr-TR-AhmetNeural-Male", "es": "es-ES-AlvaroNeural-Male",
    "de": "de-DE-ConradNeural-Male", "fr": "fr-FR-HenriNeural-Male", "pt": "pt-BR-AntonioNeural-Male",
}

_KEY = re.compile(r"^vt-takes/([A-Za-z0-9_-]{1,64})/([0-9a-f]{16,64})/take-([1-3])\.mp3$")


class VoiceError(story8.Story8Error):
    pass


@dataclass(frozen=True)
class Take:
    path: str
    seconds: float
    flatness: float


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #
def take_key(user_id: str, token: str, n: int) -> str:
    return f"{TAKES_PREFIX}/{user_id}/{token}/take-{int(n)}.mp3"


def owns_take(user_id: str, key: str) -> bool:
    text = str(key or "")
    if ".." in text or "//" in text:
        return False
    match = _KEY.match(text)
    return bool(match) and match.group(1) == str(user_id or "")


# --------------------------------------------------------------------------- #
# Flatness and the pick
# --------------------------------------------------------------------------- #
def _pcm(audio_path: str):
    import numpy as np

    done = subprocess.run([render.ffmpeg_bin(), "-v", "error", "-i", audio_path, "-ac", "1", "-ar", str(SAMPLE_RATE),
                           "-f", "s16le", "-"], capture_output=True, timeout=120, check=False)
    if done.returncode != 0:
        raise render.RenderError((done.stderr or b"").decode("utf-8", "replace")[-300:] or "could not decode audio")
    return np.frombuffer(done.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def flatness(audio_path: str) -> float:
    """How flat a take sounds; lower is flatter (more deadpan).

    The audio is decoded to mono 16 kHz and cut into 50 ms frames. Frames within
    30 dB of the loudest frame count as voiced. The score is the standard
    deviation of the voiced frames' RMS level in dB (loudness swing) plus 100x
    the standard deviation of their zero-crossing rate (a cheap proxy for pitch
    and brightness movement). A take with no voiced frames scores ``inf``.
    """
    import numpy as np

    samples = _pcm(audio_path)
    size = int(SAMPLE_RATE * FRAME_S)
    count = len(samples) // size
    if count < 2:
        return float("inf")
    frames = samples[: count * size].reshape(count, size)
    rms_db = 20.0 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9)
    voiced = rms_db > (rms_db.max() - 30.0)
    if voiced.sum() < 2:
        return float("inf")
    zcr = np.mean(np.abs(np.diff(np.signbit(frames).astype(np.int8), axis=1)), axis=1)
    return float(np.std(rms_db[voiced]) + 100.0 * np.std(zcr[voiced]))


def pick(takes: Sequence[Take], *, max_seconds: float | None = None) -> int:
    """Index of the flattest take; a take longer than ``max_seconds`` loses to any that fits."""
    if not takes:
        raise ValueError("no takes to pick from")

    def score(item: tuple[int, Take]) -> tuple[int, float, int]:
        index, take = item
        too_long = 1 if max_seconds is not None and take.seconds > float(max_seconds) else 0
        return too_long, take.flatness, index

    return min(enumerate(takes), key=score)[0]


# --------------------------------------------------------------------------- #
# Making takes
# --------------------------------------------------------------------------- #
def _free_narrate(text: str, language: str, out_path: str, *, rate: float = 1.0, voice: str = "") -> None:
    """The free chain (Kokoro when configured, edge-tts kept), as story8 narrates."""
    from app.core.launch.formats import free_voice_for
    from app.services.tts.narration import narrate, plan_chain

    lang = language or "en"
    edge = voice or free_voice_for(lang)
    narrate(text, plan_chain(edge, language=lang, free_voice=edge), out_path, voice_rate=rate)


def free_reply_voice(language: str) -> str:
    return FREE_REPLY_VOICES.get(str(language or "en").strip().lower()[:2], FREE_REPLY_VOICES["en"])


def _concat_with_gap(first: str, second: str, out_path: str, gap_s: float = REPLY_GAP_S) -> None:
    graph = (f"[0:a]aformat=sample_rates=44100:channel_layouts=mono[a];"
             f"anullsrc=r=44100:cl=mono,atrim=0:{gap_s:.3f}[g];"
             f"[1:a]aformat=sample_rates=44100:channel_layouts=mono[b];[a][g][b]concat=n=3:v=0:a=1[out]")
    render.run([render.ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", first, "-i", second,
                "-filter_complex", graph, "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "128k", out_path])


def _check_engine(engine: str, delivery: str) -> None:
    if engine not in ENGINES:
        raise VoiceError(400, "voice_engine", f"the voice is one of {', '.join(ENGINES)}")
    if delivery not in DELIVERIES:
        raise VoiceError(400, "voice_delivery", f"the delivery is one of {', '.join(DELIVERIES)}")


def premium_backend(eleven: Any = eleven_v3, replicate: Any = replicate_speech) -> str:
    """Which service renders the premium voice: ElevenLabs v3, Replicate MiniMax, or none ("")."""
    if eleven.is_enabled():
        return BACKEND_ELEVEN
    if replicate.is_enabled():
        return BACKEND_REPLICATE
    return ""


def _replicate_take(*, line: str, reply_line: str, delivery: str, language: str, n: int, out: str,
                    work_dir: str, replicate: Any) -> None:
    speed = REPLICATE_SPEEDS[(n - 1) % len(REPLICATE_SPEEDS)]
    if not reply_line:
        replicate.synthesize(line, voice_id=replicate.default_voice(), delivery=delivery, out_path=out,
                             speed=speed, language=language, seed=n)
        return
    host = os.path.join(work_dir, f"take-{n}-host.mp3")
    reply = os.path.join(work_dir, f"take-{n}-reply.mp3")
    replicate.synthesize(line, voice_id=replicate.default_voice(), delivery=delivery, out_path=host, speed=speed,
                         language=language, seed=n)
    replicate.synthesize(reply_line, voice_id=replicate.default_reply_voice(), delivery="deadpan", out_path=reply,
                         language=language, seed=n)
    _concat_with_gap(host, reply, out)


def make_takes(*, line: str, reply_line: str = "", engine: str, delivery: str, language: str, count: int,
               work_dir: str, eleven: Any = eleven_v3, free_narrate: Callable[..., None] | None = None,
               replicate: Any = replicate_speech) -> list[Take]:
    """``count`` takes of the line (and the reply) in ``work_dir``, each scored for flatness.

    The premium engine uses ElevenLabs v3 when it is configured, else Replicate.
    """
    _check_engine(engine, delivery)
    count = max(MIN_TAKES, min(MAX_TAKES, int(count)))
    tags = DELIVERY_TAGS[delivery]
    backend = premium_backend(eleven, replicate) if engine == ENGINE_ELEVEN else ""
    if engine == ENGINE_ELEVEN and not backend:
        raise VoiceError(503, "voice_unavailable", "the premium voice is not available right now; use the free voice")
    takes: list[Take] = []
    for n in range(1, count + 1):
        out = os.path.join(work_dir, f"take-{n}.mp3")
        if backend == BACKEND_REPLICATE:
            _replicate_take(line=line, reply_line=reply_line, delivery=delivery, language=language, n=n, out=out,
                            work_dir=work_dir, replicate=replicate)
            seconds = eleven.audio_seconds(out)
        elif engine == ENGINE_ELEVEN:
            if reply_line:
                seconds = eleven.dialogue([(line, eleven.default_voice(), tags),
                                           (reply_line, eleven.default_reply_voice(), ())], out_path=out, seed=n)
            else:
                seconds = eleven.synthesize(line, voice_id=eleven.default_voice(), tags=tags, out_path=out, seed=n)
        else:
            narrate_fn = free_narrate or _free_narrate
            rate = FREE_RATES[(n - 1) % len(FREE_RATES)]
            if reply_line:
                host = os.path.join(work_dir, f"take-{n}-host.mp3")
                reply = os.path.join(work_dir, f"take-{n}-reply.mp3")
                narrate_fn(line, language, host, rate=rate)
                narrate_fn(reply_line, language, reply, rate=rate, voice=free_reply_voice(language))
                _concat_with_gap(host, reply, out)
            else:
                narrate_fn(line, language, out, rate=rate)
            seconds = eleven.audio_seconds(out)
        takes.append(Take(path=out, seconds=float(seconds), flatness=flatness(out)))
    return takes


def take_for_job(*, take_key: str | None, user_id: str, line: str, reply_line: str = "", engine: str,
                 delivery: str, language: str, work_dir: str, fetch: Callable[[str], bytes],
                 eleven: Any = eleven_v3, free_narrate: Callable[..., None] | None = None,
                 max_seconds: float | None = None, replicate: Any = replicate_speech) -> tuple[str, float, str]:
    """The job's voice: ``(local path, seconds, key or "auto")``.

    The user's chosen take when ``take_key`` is theirs; otherwise fresh takes
    (three for Eleven v3, one for the free chain) and the flattest pick.
    """
    if take_key:
        if not owns_take(user_id, take_key):
            raise VoiceError(403, "take_not_yours", "that voice take is not yours")
        path = os.path.join(work_dir, "chosen-take.mp3")
        with open(path, "wb") as fh:
            fh.write(fetch(take_key))
        return path, float(eleven.audio_seconds(path)), take_key
    count = MAX_TAKES if engine == ENGINE_ELEVEN else 1
    takes = make_takes(line=line, reply_line=reply_line, engine=engine, delivery=delivery, language=language,
                       count=count, work_dir=work_dir, eleven=eleven, free_narrate=free_narrate,
                       replicate=replicate)
    best = takes[pick(takes, max_seconds=max_seconds)]
    return best.path, best.seconds, "auto"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class TakesRequest(BaseModel):
    place_word: str = Field(..., max_length=very_time.MAX_PLACE)
    line: str | None = Field(default=None, max_length=very_time.MAX_LINE)
    reply_line: str = Field("", max_length=MAX_REPLY)
    engine: str = Field(ENGINE_FREE, max_length=16)
    delivery: str = Field("deadpan", max_length=16)
    language: str = Field("", max_length=very_time.MAX_LANGUAGE)
    count: int = Field(MAX_TAKES, ge=MIN_TAKES, le=MAX_TAKES)


def clean_request(body: TakesRequest) -> tuple[str, str]:
    """The line and the reply, validated and guard-checked (no provider call)."""
    inputs = very_time.clean_inputs(place_word=body.place_word, ritual="voice takes", line=body.line,
                                    language=body.language)
    reply = " ".join(str(body.reply_line or "").split())
    if len(reply) > MAX_REPLY:
        raise VoiceError(400, "reply_line", f"the reply is {MAX_REPLY} characters at most")
    _check_engine(body.engine, body.delivery)
    terms = very_time.guard({"place_word": inputs.place_word, "line": f"{inputs.line} {reply}".strip()})
    if terms:
        raise very_time.GuardBlocked(terms)
    return inputs.line, reply


def upload(path: str, key: str) -> None:
    from app.domains.film.story8_tasks import r2_upload

    r2_upload(path, key, "audio/mpeg")


def media_url(key: str) -> str:
    from app.domains.gallery.service import media_url as gallery_url

    return gallery_url(key)


@router.post("/film/very-time/takes", summary="Hear 1 to 3 takes of the line and pick one (free to try)")
def voice_takes(request: Request, body: TakesRequest):
    from app.services.ratelimit import enforce_rate_limit

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user_id = str(_resolve_user(request, session, request_id).id)
    enforce_rate_limit(request, f"vt-takes:{user_id}", limit=RATE_LIMIT, window_s=RATE_WINDOW_S)
    try:
        line, reply = clean_request(body)
        if body.engine == ENGINE_ELEVEN and not premium_backend():
            raise VoiceError(503, "voice_unavailable", "the premium voice is not available right now; "
                                                       "use the free voice")
        token = secrets.token_hex(16)
        with tempfile.TemporaryDirectory(prefix="vt-takes-") as work:
            takes = make_takes(line=line, reply_line=reply, engine=body.engine, delivery=body.delivery,
                               language=body.language, count=body.count, work_dir=work)
            views = []
            for n, take in enumerate(takes, start=1):
                key = take_key(user_id, token, n)
                upload(take.path, key)
                views.append({"key": key, "url": media_url(key), "seconds": round(take.seconds, 2),
                              "flatness": round(take.flatness, 3)})
        recommended = views[pick(takes)]["key"]
    except story8.Story8Error as exc:
        raise very_time._http(exc, request_id) from exc
    except (eleven_v3.ElevenV3Error, replicate_speech.ReplicateSpeechError, render.RenderError) as exc:
        logger.warning(f"very-time takes failed: {exc}")
        raise HttpException(task_id=request_id, status_code=502, message=f"{request_id}: the voice did not render; "
                            "try again", data={"code": "voice_failed"}) from exc
    except Exception as exc:  # noqa: BLE001 - the free chain raises its own NarrationUnavailable
        from app.services.tts.narration import NarrationUnavailable

        if not isinstance(exc, NarrationUnavailable):
            raise
        raise HttpException(task_id=request_id, status_code=503, message=f"{request_id}: {exc}",
                            data={"code": "voice_unavailable"}) from exc
    return utils.get_response(200, {"takes": views, "recommended": recommended})


__all__ = ["DELIVERIES", "ENGINES", "ENGINE_ELEVEN", "ENGINE_FREE", "MAX_REPLY", "MAX_TAKES", "MIN_TAKES",
           "TAKES_PREFIX", "Take", "TakesRequest", "VoiceError", "flatness", "make_takes", "owns_take", "pick",
           "premium_backend",
           "router", "take_for_job", "take_key"]
