"""Safe uploads (Wave Q QM1.2: P-M5, U2, U44): every uploaded title is checked before it can publish.

An upload gets one ``ott_upload_checks`` row (``pending``) when it completes.
The worker then:

1. **Transcript**: faster-whisper (already in the render stack,
   ``services/transcribe.py``) turns the audio into text.
2. **Text gate**: the transcript and the title go through the existing
   pre-publish content gate (``publishing/content_gate.py``). ``block`` blocks;
   ``needs_edit`` or a gate that could not decide holds.
3. **Keyframes**: 8 frames spread over the video. On paid plans they go to
   Relay (Claude) with Menivor's moderation policy (``core/moderation_policy``);
   ``deny`` blocks, ``flag`` holds. With no keyframe checker (free plans, or
   Relay not configured) the upload is held for a person to look at: nothing
   unseen is published.

The strictest outcome wins: ``block`` (publish answers 409), ``hold`` (a staff
review queue, and the creator gets one email), or ``pass``. Staff approve or
reject held uploads.

Only permissively licensed code is used; the AGPL nudity detector the dispatch
named is rejected. :func:`gate_reason` is read by ``ott.service.gate``.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger
from sqlalchemy import JSON, BigInteger, DateTime, Float, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.db.base import Base

from .models import OttTitle

PENDING, PASS, HOLD, BLOCK = "pending", "pass", "hold", "block"
DECISIONS = (PENDING, PASS, HOLD, BLOCK)
_SEVERITY = {PASS: 0, HOLD: 1, BLOCK: 2}
UPLOAD_PREFIX = "ott:ott-uploads/"
FRAMES = 8
TRANSCRIPT_CHARS = 4000
VISION_MODEL_ENV = "MENIVOR_UPLOAD_VISION_MODEL"
DEFAULT_VISION_MODEL = "claude-haiku-4-5"


class OttUploadCheck(Base):
    """One content check per uploaded title (migration e2b4d6f8a0c3)."""

    __tablename__ = "ott_upload_checks"

    title_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    decision: Mapped[str] = mapped_column(String(8), nullable=False, default=PENDING)
    reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    frames_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transcript_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CheckError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class Verdict:
    decision: str
    reasons: tuple[str, ...] = ()
    frames_checked: int = 0
    transcript_chars: int = 0


@dataclass
class Checkers:
    """The three steps, injectable for tests (the defaults are the real ones)."""

    transcribe: Callable[[str], str]
    text_gate: Callable[[str, str], tuple[str, str]]
    frames: Callable[[str, float], list[bytes]]
    vision: Optional[Callable[[Sequence[bytes]], tuple[str, str]]] = None
    extra: dict[str, Any] = field(default_factory=dict)


def now() -> datetime:
    return datetime.now(timezone.utc)


def is_upload(title: OttTitle) -> bool:
    return str(title.source_key or "").startswith(UPLOAD_PREFIX) and not title.source_job_id


# --------------------------------------------------------------------------- #
# Rows, gate, review queue
# --------------------------------------------------------------------------- #
def record_upload(session: Session, title: OttTitle, *, user_id: str, size_bytes: int, seconds: float
                  ) -> OttUploadCheck:
    row = session.get(OttUploadCheck, title.id)
    if row is None:
        row = OttUploadCheck(title_id=title.id, user_id=str(user_id), source_key=title.source_key,
                             size_bytes=int(size_bytes or 0), seconds=float(seconds or 0), decision=PENDING,
                             reasons=[])
        session.add(row)
        session.flush()
    return row


def gate_reason(session: Session, title: OttTitle) -> Optional[str]:
    """Why an uploaded title may not publish yet (``None`` when it passed or is not an upload)."""
    row = session.get(OttUploadCheck, title.id)
    if row is None:
        return "the content check has not run on this upload yet" if is_upload(title) else None
    if row.decision == PASS:
        return None
    if row.decision == BLOCK:
        return "the content check blocked this video"
    if row.decision == HOLD:
        return "the content check is holding this video for a review"
    return "the content check is still running"


def review_queue(session: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = session.execute(select(OttUploadCheck).where(OttUploadCheck.decision == HOLD)
                           .order_by(OttUploadCheck.created_at).limit(limit)).scalars().all()
    return [check_view(r) for r in rows]


def review(session: Session, title_id: str, *, approve: bool, staff_id: str) -> OttUploadCheck:
    row = session.get(OttUploadCheck, title_id)
    if row is None:
        raise CheckError(404, "not_found", "no upload check for this title")
    if row.decision not in (HOLD, BLOCK):
        raise CheckError(409, "not_held", "only held or blocked uploads are reviewed")
    row.decision = PASS if approve else BLOCK
    row.reasons = [*list(row.reasons or []), f"reviewed: {'approved' if approve else 'rejected'}"]
    row.reviewed_by, row.reviewed_at = str(staff_id), now()
    session.flush()
    return row


def check_view(row: OttUploadCheck) -> dict[str, Any]:
    return {"title_id": row.title_id, "decision": row.decision, "reasons": list(row.reasons or []),
            "frames_checked": row.frames_checked, "seconds": row.seconds, "size_bytes": row.size_bytes,
            "checked_at": row.checked_at.isoformat() if row.checked_at else None,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None}


# --------------------------------------------------------------------------- #
# Deciding
# --------------------------------------------------------------------------- #
def _stricter(current: str, candidate: str) -> str:
    return candidate if _SEVERITY[candidate] > _SEVERITY[current] else current


def evaluate(title_text: str, media_path: str, seconds: float, *, paid: bool, checkers: Checkers) -> Verdict:
    """Run the three steps on a local copy of the upload; the strictest outcome wins."""
    decision, reasons = PASS, []
    transcript = ""
    try:
        transcript = " ".join(str(checkers.transcribe(media_path) or "").split())[:TRANSCRIPT_CHARS]
    except Exception as exc:  # noqa: BLE001 - a failed step holds, never passes
        decision, reasons = HOLD, [f"transcript failed: {type(exc).__name__}"]
    outcome, why = checkers.text_gate(transcript, title_text)
    decision = _stricter(decision, outcome)
    if outcome != PASS:
        reasons.append(f"text: {why}")
    frames: list[bytes] = []
    try:
        frames = list(checkers.frames(media_path, seconds))
    except Exception as exc:  # noqa: BLE001
        decision = _stricter(decision, HOLD)
        reasons.append(f"keyframes failed: {type(exc).__name__}")
    if frames:
        vision = checkers.vision if paid else None
        if vision is None:
            decision = _stricter(decision, HOLD)
            reasons.append("keyframes: no automatic image check on this plan; a person reviews it")
        else:
            outcome, why = vision(frames)
            decision = _stricter(decision, outcome)
            if outcome != PASS:
                reasons.append(f"keyframes: {why}")
    return Verdict(decision=decision, reasons=tuple(reasons), frames_checked=len(frames) if paid else 0,
                   transcript_chars=len(transcript))


def apply(session: Session, row: OttUploadCheck, verdict: Verdict, *, notify: Callable[[OttUploadCheck], bool]
          ) -> OttUploadCheck:
    row.decision, row.reasons = verdict.decision, list(verdict.reasons)
    row.frames_checked, row.transcript_chars = verdict.frames_checked, verdict.transcript_chars
    row.checked_at = now()
    if verdict.decision == HOLD and row.notified_at is None:
        try:
            if notify(row):
                row.notified_at = now()
        except Exception as exc:  # noqa: BLE001 - an email failure never loses the verdict
            logger.warning(f"upload hold email for {row.title_id} failed: {exc}")
    if verdict.decision == BLOCK:
        logger.warning(f"upload {row.title_id} blocked by the content check: {list(verdict.reasons)}")
    session.flush()
    return row


# --------------------------------------------------------------------------- #
# The real steps
# --------------------------------------------------------------------------- #
def transcribe_text(path: str) -> str:
    from app.services.transcribe import transcribe_to_words

    return " ".join(str(getattr(w, "text", "") or getattr(w, "word", "")) for w in transcribe_to_words(path))


def text_gate(transcript: str, title_text: str) -> tuple[str, str]:
    from app.domains.publishing import content_gate as cg

    if not transcript.strip():
        return PASS, "no speech"
    result = cg.evaluate_content_sync(transcript, title_text, cg.GateContext(platform="menivor-ott"))
    if result.decision == cg.BLOCK:
        return BLOCK, "the transcript breaks the content rules"
    if result.decision == cg.NEEDS_EDIT or result.degraded or result.decision == cg.PUBLISH_WITH_REVIEW:
        return HOLD, "the transcript needs a person to look at it"
    return PASS, ""


def extract_frames(path: str, seconds: float = 0.0, *, count: int = FRAMES, ffmpeg: str = "ffmpeg") -> list[bytes]:
    """``count`` JPEG frames spread over the video; none for an audio-only upload.

    The length comes from probing the file, never from the client's declared
    ``seconds``. A file with a video stream that yields no frame raises, so the
    caller holds it instead of treating it as audio-only.
    """
    from app.services.ott_transcode.pipeline import probe

    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe") if "ffmpeg" in os.path.basename(ffmpeg) else "ffprobe"
    source = probe(ffprobe, path)
    if not source.width:
        return []
    length = max(float(source.seconds or seconds or 0), 0.1)
    out: list[bytes] = []
    with tempfile.TemporaryDirectory(prefix="ott-frames-") as work:
        for n in range(count):
            at = length * (n + 0.5) / count
            target = Path(work, f"f{n}.jpg")
            done = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{at:.3f}", "-i", path, "-frames:v", "1",
                                   "-vf", "scale=512:-2", "-q:v", "5", "-y", str(target)],
                                  capture_output=True, timeout=60, check=False)
            if done.returncode == 0 and target.is_file() and target.stat().st_size:
                out.append(target.read_bytes())
    if not out:
        raise RuntimeError("the video has frames but none could be read")
    return out


def relay_vision(frames: Sequence[bytes], *, chat: Optional[Callable[..., Any]] = None) -> tuple[str, str]:
    """Ask Relay (Claude) to classify the frames with Menivor's policy; ``hold`` when it cannot answer."""
    from app.core.moderation_common import parse_decision
    from app.core.moderation_policy import POLICY_TEXT
    from app.core.moderation_types import ModerationUnavailable

    if chat is None:
        from app.domains.railyard.chat_payload import run_chat_payload as chat
    content: list[dict[str, Any]] = [{"type": "text", "text": (
        "These are keyframes from one uploaded video. Classify what the video shows. "
        "Answer only with the JSON the policy asks for.")}]
    for frame in frames[:FRAMES]:
        encoded = base64.b64encode(frame).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
    body = {"model": os.getenv(VISION_MODEL_ENV) or DEFAULT_VISION_MODEL, "temperature": 0, "max_tokens": 200,
            "messages": [{"role": "system", "content": POLICY_TEXT}, {"role": "user", "content": content}]}
    try:
        routed = chat(body, relay_provider="anthropic")
    except Exception as exc:  # noqa: BLE001 - a cap or outage holds for a person
        return HOLD, f"image check unavailable ({type(exc).__name__})"
    if routed is None:
        return HOLD, "image check is not configured"
    payload = getattr(routed, "payload", routed) or {}
    try:
        text = str(((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        decision, categories = parse_decision(text)
    except (ModerationUnavailable, AttributeError, IndexError, TypeError) as exc:
        return HOLD, f"image check gave no clear answer ({type(exc).__name__})"
    if decision == "deny":
        return BLOCK, "the frames break the content rules" + (f" ({', '.join(categories)})" if categories else "")
    if decision == "flag":
        return HOLD, "the frames need a person to look at them"
    return PASS, ""


def default_checkers() -> Checkers:
    return Checkers(transcribe=transcribe_text, text_gate=text_gate, frames=extract_frames, vision=relay_vision)


def notify_hold(row: OttUploadCheck) -> bool:
    """One email to the creator: the upload is held for a review (Rally Send, else SMTP)."""
    from app.models.db.models import User
    from app.models.db.base import get_session
    from app.services.lifecycle import rally_tx_client as rally

    with get_session() as session:
        user = session.get(User, row.user_id)
        title = session.get(OttTitle, row.title_id)
        email = str(getattr(user, "email", "") or "")
        name = str(getattr(title, "title", "") or "your video")
    if not email:
        return False
    subject = "Your upload is waiting for a quick review"
    text = (f"Thanks for uploading \"{name}\". Our content check wants a person to look at it before it can be "
            "published. This usually takes less than a day, and we will not charge anything for the wait.")
    import html as html_lib

    html = f"<p>{html_lib.escape(text)}</p>"  # the title is creator text (QM verify)
    if rally.configured():
        body = rally.build_body(to=email, subject=subject, html=html, text=text,
                                key=f"menivor:ott-upload-hold:{row.title_id}", tags=("ott", "upload_hold"))
        return rally.send(body).outcome == rally.SENT
    from app.services import mailer

    return bool(mailer.configured() and mailer.send_email(to=email, subject=subject, text=text, html=html))


def run_check(session: Session, title_id: str, *, fetch: Callable[[str, str], str], paid: bool,
              checkers: Optional[Checkers] = None, notify: Callable[[OttUploadCheck], bool] = notify_hold
              ) -> Optional[OttUploadCheck]:
    """Check one pending upload: ``fetch(source_key, dest_dir)`` returns a local path to the file."""
    row = session.get(OttUploadCheck, title_id)
    title = session.get(OttTitle, title_id)
    if row is None or title is None or row.decision != PENDING:
        return row
    with tempfile.TemporaryDirectory(prefix="ott-check-") as work:
        path = fetch(row.source_key, work)
        verdict = evaluate(" ".join([title.title, title.synopsis or ""]), path, row.seconds or title.duration_s,
                           paid=paid, checkers=checkers or default_checkers())
    return apply(session, row, verdict, notify=notify)


def summary(verdict: Verdict) -> str:
    return json.dumps({"decision": verdict.decision, "reasons": list(verdict.reasons)})


__all__ = ["BLOCK", "CheckError", "Checkers", "DECISIONS", "FRAMES", "HOLD", "OttUploadCheck", "PASS", "PENDING",
           "Verdict", "apply", "check_view", "default_checkers", "evaluate", "extract_frames", "gate_reason",
           "is_upload", "notify_hold", "record_upload", "relay_vision", "review", "review_queue", "run_check",
           "text_gate", "transcribe_text"]
