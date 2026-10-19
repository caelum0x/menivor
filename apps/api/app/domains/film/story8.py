"""Story in 8 frames (MH5, Wave P PM2.1).

A topic or a script becomes eight consistent frames, then a voiced, captioned
vertical story. Two ways to make it, both priced before anything runs:

* **Frames** (Ken Burns): eight still frames with slow camera moves, a free
  voice and word-by-word captions. Paid in **standard credits** (the story's
  length plus ``frames_standard_credits`` for the eight frames).
* **Animated**: the same frames, each animated into a short shot. Adds
  **AI-video credits** (eight draft shots at 3x the provider cost), quoted
  before render and debited at start; a shot that fails falls back to its
  still frame and its credits come back.

Consistency: every frame prompt comes from the same locked character profile
(``characters.consistency.build_shot_prompt``), so the identity leads every
prompt and each frame has a stable seed. When the character has a reference
image, every frame is scored against it (the MH4 ``appearance-v1`` score) and
the scores are stored with the character.

Flow (fewest clicks): ``POST /film/story8/plan`` writes the eight lines (one
Relay LLM call for a topic, none for a script) and returns them with both
prices; ``POST /film/story8`` starts the render with those lines (edited or
not) and the price the user saw; ``GET /film/story8/{job_id}`` shows progress,
frames, scores and the finished video.

The camera moves come from ``storyboard.shotlist`` (unchanged) and the frame
plan mirrors ``film.orchestrator`` (unchanged): one locked prompt per shot.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from fastapi import Path as PathParam
from fastapi import Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.utils import utils

router = new_router()

PRESETS_DIR = Path(__file__).resolve().parents[3] / "assets" / "presets" / "story"
PRESET_FILE = PRESETS_DIR / "story8@v1.json"
DEFAULT_PRESET = "story8"
# Story presets a story8 job can run (``params.preset``); the file is ``<id>@v<version>.json``.
PRESET_FILES = {"story8": "story8@v1.json", "very-time": "very-time@v1.json"}
JOB_KIND = "story8"
MODE_FRAMES = "frames"
MODE_ANIMATED = "animated"
MODES = (MODE_FRAMES, MODE_ANIMATED)
MAX_TOPIC = 300
MAX_SCRIPT = 2400
MAX_LINE = 220
DEBIT_REASON = "story8"
REFUND_REASON = "story8_refund"
TASK_STATE_COMPLETE = 1
TASK_STATE_FAILED = -1
TASK_STATE_PROCESSING = 4

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_LINE_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.):])\s*")


class Story8Error(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def preset_id(name: str | None = None) -> str:
    """``"very-time@v1"`` or ``"very-time"`` -> ``"very-time"``; empty -> the story8 default."""
    base = str(name or DEFAULT_PRESET).strip().split("@", 1)[0]
    if base not in PRESET_FILES:
        raise Story8Error(400, "preset", "this story template does not exist")
    return base


def preset(name: str = DEFAULT_PRESET) -> dict[str, Any]:
    """The story preset (cached; ``"very-time@v1"`` and ``"very-time"`` are the same one)."""
    return _load_preset(preset_id(name))


@lru_cache(maxsize=8)
def _load_preset(pid: str) -> dict[str, Any]:
    data = json.loads((PRESETS_DIR / PRESET_FILES[pid]).read_text(encoding="utf-8"))
    if data.get("id") != pid or len(data.get("beats") or []) != int(data.get("frames", 0)):
        raise ValueError(f"{pid} preset: id or beat count is wrong")
    return data


def job_preset_id(job_or_params: Any) -> str:
    """The preset a story job runs (``params.preset``; old jobs have none and are story8)."""
    params = getattr(job_or_params, "params", job_or_params)
    return preset_id((params or {}).get("preset") if isinstance(params, Mapping) else None)


def job_preset(job_or_params: Any) -> dict[str, Any]:
    return preset(job_preset_id(job_or_params))


def frame_count(name: str = DEFAULT_PRESET) -> int:
    return int(preset(name)["frames"])


def beat_seconds(data: Mapping[str, Any], index: int) -> float:
    """Seconds of one beat: the beat's own ``seconds`` or the preset's ``frame_seconds``."""
    beat = data["beats"][index]
    return float(beat.get("seconds") or data["frame_seconds"])


# --------------------------------------------------------------------------- #
# Lines: a script is split, a topic is written through Relay
# --------------------------------------------------------------------------- #
def _clean(text: str, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def split_script(script: str, count: int | None = None) -> list[str]:
    """Split a script into exactly ``count`` lines, keeping sentence order.

    More sentences than frames: neighbouring sentences are joined evenly.
    Fewer: the longest line is split at its middle word until there are enough.
    """
    count = count or frame_count()
    text = _clean(script, MAX_SCRIPT)
    if not text:
        raise Story8Error(400, "script_required", "type a topic or a script first")
    sentences = [s for s in _SENTENCE.split(text) if s.strip()]
    if len(sentences) >= count:
        size, extra = divmod(len(sentences), count)
        lines, start = [], 0
        for index in range(count):
            end = start + size + (1 if index < extra else 0)
            lines.append(" ".join(sentences[start:end]))
            start = end
        return [_clean(line, MAX_LINE) for line in lines]
    lines = list(sentences)
    while len(lines) < count:
        longest = max(range(len(lines)), key=lambda i: len(lines[i].split()))
        words = lines[longest].split()
        if len(words) < 2:
            raise Story8Error(400, "script_too_short", f"write at least {count} words so each frame has a line")
        half = len(words) // 2
        lines[longest:longest + 1] = [" ".join(words[:half]), " ".join(words[half:])]
    return [_clean(line, MAX_LINE) for line in lines]


def _story_prompt(topic: str, language: str) -> str:
    beats = "; ".join(f"{i + 1}. {b['id']}: {b['direction']}" for i, b in enumerate(preset()["beats"]))
    lang = f" Write in {language}." if language and language != "auto" else ""
    return (
        f"Write a short vertical-video story about: {topic}.\n"
        f"It has exactly {frame_count()} narration lines, one per frame, in this order: {beats}.\n"
        "Each line is one spoken sentence of 6 to 18 words. No hashtags, no emoji, no stage directions, "
        f"no numbering, no brand or tool names.{lang}\n"
        f"Answer with the {frame_count()} lines only, one per line."
    )


def write_lines(topic: str, *, language: str = "", llm=None) -> list[str]:
    """Eight narration lines for a topic (one LLM call through Relay)."""
    text = _clean(topic, MAX_TOPIC)
    if not text:
        raise Story8Error(400, "topic_required", "type a topic or a script first")
    if llm is None:
        from app.services import llm as llm_service

        llm = llm_service._generate_response
    raw = str(llm(_story_prompt(text, language)) or "")
    if raw.startswith("Error: "):
        raise Story8Error(503, "writer_unavailable", "the story writer is busy; try again in a minute")
    lines = [_clean(_LINE_PREFIX.sub("", line), MAX_LINE) for line in raw.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) != frame_count():
        lines = split_script(" ".join(lines))
    return lines


# --------------------------------------------------------------------------- #
# Frame plan: locked prompts, camera moves, stable seeds
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Frame:
    index: int
    beat: str
    line: str
    prompt: str
    negative: str
    seed: int
    camera: str
    seconds: float


def _profile(character: Mapping[str, Any] | None, lines: Sequence[str]):
    from app.domains.characters.consistency import CharacterProfile

    data = preset()
    if character:
        return CharacterProfile(
            character_id=str(character.get("id") or ""), name=str(character.get("name") or ""),
            descriptors=tuple(character.get("descriptors") or ()),
            style=", ".join(p for p in (str(character.get("style") or ""), data["style"]) if p),
            reference_images=tuple(character.get("reference_images") or ()),
            lora_ref=str(character.get("lora_ref") or ""),
            negative=tuple([*(character.get("negative") or ()), *data["negative"]]),
        )
    # No character: the story's first line anchors one invented main character.
    anchor = _clean(lines[0], 80) if lines else "the main character"
    return CharacterProfile(character_id="", name="the same main character", descriptors=(f"from: {anchor}",),
                            style=data["style"], negative=tuple(data["negative"]))


def _camera_moves(lines: Sequence[str]) -> list[str]:
    """Camera per frame: the preset's beat camera, cross-checked with the storyboard cycle."""
    from app.domains.storyboard.shotlist import SceneBeat, build_shot_list

    beats = preset()["beats"]
    shots = build_shot_list([SceneBeat(scene_id=b["id"], summary=line) for b, line in zip(beats, lines)],
                            total_shots=len(lines))
    moves = []
    for beat, shot in zip(beats, shots):
        moves.append(str(beat.get("camera") or shot.camera_motion or "push_in"))
    return moves


def build_plan(lines: Sequence[str], character: Mapping[str, Any] | None = None) -> list[Frame]:
    from app.domains.characters.consistency import build_shot_prompt

    if len(lines) != frame_count():
        raise Story8Error(400, "lines_count", f"a story has exactly {frame_count()} lines")
    clean = [_clean(line, MAX_LINE) for line in lines]
    if any(not line for line in clean):
        raise Story8Error(400, "line_empty", "every frame needs a line")
    data = preset()
    profile = _profile(character, clean)
    frames = []
    for index, (beat, line, camera) in enumerate(zip(data["beats"], clean, _camera_moves(clean))):
        shot = build_shot_prompt(profile, line, shot_index=index, scene=beat["direction"])
        frames.append(Frame(index=index, beat=beat["id"], line=line, prompt=shot.prompt[:1200],
                            negative=shot.negative_prompt[:400], seed=shot.seed, camera=camera,
                            seconds=float(data["frame_seconds"])))
    return frames


def moderate(lines: Sequence[str]) -> None:
    from app.domains.broll.router import _PROMPT_DENYLIST

    joined = " ".join(lines).lower()
    if any(term in joined for term in _PROMPT_DENYLIST):
        raise Story8Error(400, "prompt_blocked", "this story cannot be made")


# --------------------------------------------------------------------------- #
# Price first
# --------------------------------------------------------------------------- #
def clip_credits() -> int:
    from app.domains.broll.router import _broll_ai_video_credits

    return int(_broll_ai_video_credits())


def _frame_seconds(frame: Frame | Mapping[str, Any]) -> float:
    return float(frame.seconds if isinstance(frame, Frame) else frame["seconds"])


def quote(frames: Sequence[Frame | Mapping[str, Any]] | None = None, preset_name: str = DEFAULT_PRESET
          ) -> dict[str, Any]:
    from app.domains.reels.pricing import standard_credits

    data = preset(preset_name)
    count = frame_count(preset_name)
    seconds = int(round(sum(_frame_seconds(f) for f in frames) if frames
                        else sum(beat_seconds(data, i) for i in range(count))))
    standard = int(standard_credits(seconds)) + int(data["frames_standard_credits"])
    return {
        "seconds": seconds,
        MODE_FRAMES: {"standard_credits": standard, "ai_video_credits": 0},
        MODE_ANIMATED: {"standard_credits": standard, "ai_video_credits": count * clip_credits()},
    }


def frame_view(frame: Frame | Mapping[str, Any]) -> dict[str, Any]:
    data = asdict(frame) if isinstance(frame, Frame) else dict(frame)
    return {"index": data["index"], "beat": data["beat"], "line": data["line"], "camera": data["camera"],
            "seconds": data["seconds"]}


def plan_view(lines: Sequence[str], character: Mapping[str, Any] | None) -> dict[str, Any]:
    frames = build_plan(lines, character)
    return {"lines": [f.line for f in frames], "frames": [frame_view(f) for f in frames], "quote": quote(frames)}


# --------------------------------------------------------------------------- #
# Start: debit, create the job, enqueue
# --------------------------------------------------------------------------- #
def _character(session: Session, user_id: str, character_id: str | None) -> dict[str, Any] | None:
    if not character_id:
        return None
    from app.domains.characters import hub

    try:
        return hub.character_for_user(session, user_id, character_id)
    except hub.HubError as exc:
        raise Story8Error(exc.status_code, exc.code, str(exc)) from exc


def enqueue(job_id: str) -> str:
    from app.domains.film.story8_tasks import run_story8_task

    return str(run_story8_task.apply_async(args=[job_id], queue="generation").id)


def _check_mode(mode: str) -> None:
    if mode not in MODES:
        raise Story8Error(400, "mode", f"mode is one of {', '.join(MODES)}")


def start(session: Session, user_id: str, *, lines: Sequence[str], mode: str, quoted: Mapping[str, int],
          character_id: str | None = None, language: str = "", request_id: str = "") -> Any:
    _check_mode(mode)
    character = _character(session, user_id, character_id)
    frames = build_plan(lines, character)
    moderate([f.line for f in frames])
    return start_frames(session, user_id, frames=[asdict(f) for f in frames], mode=mode, quoted=quoted,
                        character=character, language=language, request_id=request_id)


def start_frames(session: Session, user_id: str, *, frames: Sequence[Mapping[str, Any]], mode: str,
                 quoted: Mapping[str, int], preset_name: str = DEFAULT_PRESET,
                 character: Mapping[str, Any] | None = None, language: str = "", request_id: str = "",
                 extra: Mapping[str, Any] | None = None, price: Mapping[str, int] | None = None) -> Any:
    """Price check, then create the story job for any preset and debit it (the shared start path).

    ``price`` is the preset's own price for ``mode`` when it prices beyond the frame
    seconds (very-time: length, end card, premium voice, sound effects); default is
    :func:`quote` over the frames."""
    from app.models.db.repositories import CreditRepository, JobRepository
    from app.services.billing import premium_credits as pc

    _check_mode(mode)
    pid = preset_id(preset_name)
    price = dict(price) if price is not None else quote(frames, pid)[mode]
    if (int(quoted.get("standard_credits", -1)) != price["standard_credits"]
            or int(quoted.get("ai_video_credits", -1)) != price["ai_video_credits"]):
        raise Story8Error(409, "quote_changed", "the price changed; check the new price first")
    params = {
        "_correlation_id": request_id, "mode": mode, "language": _clean(language, 12),
        "character_id": (character or {}).get("id") or None,
        "frames": [dict(f) for f in frames], "credits_cost": price["standard_credits"],
        "ai_video_credits": price["ai_video_credits"], "clip_credits": clip_credits() if mode == MODE_ANIMATED else 0,
        "workspace_id": None, **dict(extra or {}), "preset": pid,
    }
    job = JobRepository(session).create(user_id=user_id, kind=JOB_KIND, params=params)
    try:
        CreditRepository(session).debit(user_id, price["standard_credits"], job.id, DEBIT_REASON)
    except ValueError as exc:
        raise Story8Error(402, "credits_required", "not enough credits for this story") from exc
    if price["ai_video_credits"]:
        try:
            pc.debit(session, user_id, pc.KIND_AI_VIDEO, price["ai_video_credits"],
                     f"{pc.DEBIT_REASON}:{job.id}", job.id)
        except pc.InsufficientPremiumCredits as exc:
            raise Story8Error(402, "ai_video_credits_required",
                              f"animating needs {exc.needed} AI-video credits; you have {exc.available}") from exc
    job.state = TASK_STATE_PROCESSING
    session.flush()
    return job


def refund(session: Session, job: Any, *, clips_failed: int | None = None,
           failed_credits: int | None = None) -> dict[str, int]:
    """Give back what a failed story (or failed shots) held; safe to call twice."""
    from app.domains.reels.refunds import refund_latest_debit_once_in_session
    from app.services.billing import premium_credits as pc

    params = dict(job.params or {})
    returned = {"standard_credits": 0, "ai_video_credits": 0}
    refunds = dict(params.get("_refunds") or {})
    if clips_failed is None:
        returned["standard_credits"] = int(refund_latest_debit_once_in_session(session, job.id, REFUND_REASON) or 0)
        ai_due = int(params.get("ai_video_credits") or 0) - int(refunds.get("ai_video_credits") or 0)
    elif failed_credits is not None:
        ai_due = int(failed_credits)  # shots priced per length (very-time): the failed shots' own credits
    else:
        ai_due = int(params.get("clip_credits") or 0) * int(clips_failed)
    if ai_due > 0:
        pc.grant(session, str(job.user_id), pc.KIND_AI_VIDEO, ai_due, f"{pc.REFUND_REASON}:{job.id}:{ai_due}",
                 job.id)
        refunds["ai_video_credits"] = int(refunds.get("ai_video_credits") or 0) + ai_due
        returned["ai_video_credits"] = ai_due
    job.params = {**params, "_refunds": refunds}
    session.flush()
    return returned


def job_view(job: Any) -> dict[str, Any]:
    from app.domains.gallery.service import media_url

    params = dict(job.params or {})
    frames = []
    for frame in params.get("frames") or []:
        view = frame_view(frame)
        view["image_url"] = media_url(str(frame.get("key") or ""))
        view["identity_score"] = frame.get("identity_score")
        view["animated"] = bool(frame.get("clip_key"))
        frames.append(view)
    scores = [f["identity_score"] for f in frames if isinstance(f.get("identity_score"), (int, float))]
    chest = [{"index": int(f.get("index", i)), **dict(f["chest_check"])}
             for i, f in enumerate(params.get("frames") or []) if isinstance(f.get("chest_check"), Mapping)]
    extra_view = {
        "duration_s": params.get("duration_s"), "sheet_url": media_url(str(params.get("_sheet_key") or "")) or None,
        "chest": chest, "payoff_used": params.get("_payoff_used"), "take_key": params.get("_take_key"),
    } if params.get("preset") == "very-time" else {}
    return {
        "job_id": job.id, "state": job.state, "mode": params.get("mode"), "stage": params.get("_stage", "queued"),
        "preset": params.get("preset") or DEFAULT_PRESET, "look": params.get("look"),
        "frames": frames, "identity_score_min": min(scores) if scores else None,
        "video_url": media_url(job.result_key or ""), "poster_url": media_url(job.poster_key or ""),
        "error": params.get("_error", ""), "refunded": params.get("_refunds") or {}, **extra_view,
    }


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class PlanRequest(BaseModel):
    topic: str = Field("", max_length=MAX_TOPIC)
    script: str = Field("", max_length=MAX_SCRIPT)
    character_id: str | None = Field(default=None, max_length=32)
    language: str = Field("", max_length=12)


class QuotedCredits(BaseModel):
    standard_credits: int = Field(..., ge=0)
    ai_video_credits: int = Field(0, ge=0)


class StartRequest(BaseModel):
    lines: list[str] = Field(..., min_length=1, max_length=16)
    mode: str = Field(MODE_FRAMES, max_length=16)
    quoted: QuotedCredits
    character_id: str | None = Field(default=None, max_length=32)
    language: str = Field("", max_length=12)


def _http(exc: Story8Error, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}",
                         data={"code": exc.code})


@router.post("/film/story8/plan", summary="Write the 8 lines of a story and price both versions")
def plan_story(request: Request, body: PlanRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            character = _character(session, str(user.id), body.character_id)
            if body.script.strip():
                lines = split_script(body.script)
            else:
                lines = write_lines(body.topic, language=body.language)
            moderate(lines)
            view = plan_view(lines, character)
        except Story8Error as exc:
            raise _http(exc, request_id) from exc
    return utils.get_response(200, view)


@router.post("/film/story8", summary="Make the story (price checked first)")
def start_story(request: Request, body: StartRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            job = start(session, str(user.id), lines=body.lines, mode=body.mode, quoted=body.quoted.model_dump(),
                        character_id=body.character_id, language=body.language, request_id=request_id)
        except Story8Error as exc:
            raise _http(exc, request_id) from exc
        job_id = job.id
    enqueue_or_refund(job_id, request_id)
    return utils.get_response(200, {"job_id": job_id, "state": TASK_STATE_PROCESSING})


def enqueue_or_refund(job_id: str, request_id: str) -> None:
    """Queue a started story; when the queue is down, fail it and give everything back (502)."""
    try:
        enqueue(job_id)
    except Exception as exc:  # noqa: BLE001 - an enqueue failure refunds everything
        logger.error(f"story8 {job_id} enqueue failed: {exc}")
        with get_session() as session:
            from app.models.db.models import Job

            job = session.get(Job, job_id)
            job.state = TASK_STATE_FAILED
            job.params = {**dict(job.params or {}), "_error": "could not start; nothing was charged"}
            refund(session, job)
        raise HttpException(task_id=request_id, status_code=502, message=f"{request_id}: could not start the story",
                            data={"code": "enqueue_failed"}) from exc


@router.get("/film/story8/{job_id}", summary="Story progress, frames, identity scores and the video")
def get_story(request: Request, job_id: str = PathParam(..., max_length=32)):
    from app.models.db.models import Job

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = session.get(Job, job_id)
        if job is None or job.kind != JOB_KIND or str(job.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: story not found")
        view = job_view(job)
    return utils.get_response(200, view)
