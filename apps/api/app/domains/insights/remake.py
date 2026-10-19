"""Remake the winner: render N new variants from the winning hook + format.

The winning variant's *format* (layout, caption style, voice, avatar, aspect,
music, background, length …) and *body* (everything after the opening line of
its final narration script) are kept; only the **hook** — the opening line — is
rewritten three ways. That is the classic 1-body / N-hooks test, seeded with the
hook that just won, so the next round measures a real improvement instead of a
random reroll.

Hook rewrites come from the configured LLM (one call, three lines). If no LLM is
configured or the call fails, the deterministic cold-open templates from
:mod:`app.services.loops.hook_suggestions` are used instead — the remake never
depends on a paid provider.

Money path (mirrors ``POST /jobs``): jobs are created and the personal credit
balance debited in ONE locked transaction (insufficient balance rolls back
everything), the spend cap is checked against the lineage total inside the same
transaction, and only after commit are the pipelines enqueued. A failed enqueue
marks that job failed, refunds its debit and returns the credits to the cap.
"""

from __future__ import annotations

import dataclasses
import re
import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger

from .winner_loop_state import (
    LOOP_EVENT_STAGE,
    REMAKE_VARIANTS,
    new_state,
    read_state,
    write_state,
)

_SENTENCE = re.compile(r"^(.+?[.!?…])(?:\s+|$)(.*)$", re.DOTALL)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
_MAX_HOOK_CHARS = 200
_REMAKE_REFUND_REASON = "refund"


class RemakeError(RuntimeError):
    """A remake could not be started (``status_code`` maps to HTTP)."""

    def __init__(self, message: str, *, status_code: int = 409) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class RemakeResult:
    batch_id: str
    job_ids: tuple[str, ...]
    hooks: tuple[str, ...]
    credits: int
    enqueue_failures: tuple[str, ...] = ()
    replayed: bool = False

    def to_record(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "job_ids": list(self.job_ids),
            "hooks": list(self.hooks),
            "credits": self.credits,
            "enqueue_failures": list(self.enqueue_failures),
            "replayed": self.replayed,
        }


# --------------------------------------------------------------------------- #
# Hook + body extraction
# --------------------------------------------------------------------------- #
def split_hook(script: str) -> tuple[str, str]:
    """Split a narration script into (opening line, rest)."""
    text = str(script or "").strip()
    if not text:
        return "", ""
    first_line, _, rest_lines = text.partition("\n")
    match = _SENTENCE.match(first_line.strip())
    if match:
        hook = match.group(1).strip()
        rest = " ".join(p for p in (match.group(2).strip(), rest_lines.strip()) if p)
        return hook, rest
    return first_line.strip(), rest_lines.strip()


def winning_hook(job: Any) -> tuple[str, str]:
    """(hook, body) for a job: its final script, else the manual script, else the subject."""
    params = job.params if isinstance(job.params, dict) else {}
    for source in (getattr(job, "script", "") or "", str(params.get("video_script") or "")):
        hook, body = split_hook(source)
        if hook:
            return hook, body
    return str(params.get("video_subject") or "").strip(), ""


def _clean_line(line: str) -> str:
    text = _BULLET.sub("", str(line or "")).strip().strip("\"'“”").strip()
    return text[:_MAX_HOOK_CHARS]


def _key(text: str) -> str:
    return re.sub(r"[^\w\s]", "", str(text or "")).strip().lower()


def _template_rewrites(hook: str) -> list[str]:
    """Deterministic reframes of a declarative hook (no LLM needed)."""
    core = str(hook or "").strip().rstrip(".!?…").strip()
    if not core:
        return []
    # Lower-case the first letter mid-sentence unless it starts an acronym/name.
    inner = core[0].lower() + core[1:] if len(core) > 1 and core[1].islower() else core
    return [
        f"Most people get this wrong: {inner}.",
        f"{core[0].upper()}{core[1:]} — and here is why.",
        f"Nobody told me this sooner: {inner}.",
        f"Here is the truth: {inner}.",
    ]


def hook_variants(hook: str, *, topic: str, language: str, count: int = REMAKE_VARIANTS) -> list[str]:
    """Return ``count`` distinct rewrites of the winning hook (LLM, else templates)."""
    seen = {_key(hook)}
    out: list[str] = []

    def _take(candidate: str) -> None:
        cleaned = _clean_line(candidate)
        key = _key(cleaned)
        if len(key) >= 3 and key not in seen and len(out) < count:
            seen.add(key)
            out.append(cleaned)

    if hook.strip():
        try:
            from app.services.llm import _generate_response

            lang = language if language and language != "auto" else "the same language as the winning line"
            prompt = (
                f"You write opening lines for short vertical videos.\n"
                f"This opening line won an A/B test: {hook.strip()}\n"
                f"Topic: {topic or 'same as the winning line'}\n"
                f"Write {count} new opening lines in {lang} that keep the same angle and promise "
                f"but vary the wording and structure (for example a question, a bold claim, "
                f"a curiosity gap). Each under 20 words. No emojis, no hashtags, no quotes, "
                f"no numbering. Return exactly {count} lines, one per line, nothing else."
            )
            response = str(_generate_response(prompt) or "")
            if response and not response.startswith("Error:"):
                for line in response.splitlines():
                    _take(line)
            elif response:
                logger.info(f"remake hook LLM unavailable, using templates: {response[:160]}")
        except Exception as exc:  # noqa: BLE001 - the template fallback always works
            logger.info(f"remake hook LLM failed, using templates: {exc}")

    # The deterministic templates are English; for other languages only the LLM
    # rewrites are used (the caller reports a clear error if there are too few).
    lang = str(language or "auto").strip().lower()
    if lang == "auto" or lang.startswith("en"):
        for candidate in _template_rewrites(hook):
            _take(candidate)
        if len(out) < count:
            from app.services.loops.hook_suggestions import suggest_hooks

            for suggestion in suggest_hooks(hook or topic or "this", passes_gate=False, limit=5):
                _take(suggestion.text)
    return out[:count]


# --------------------------------------------------------------------------- #
# Params
# --------------------------------------------------------------------------- #
def remake_params(winner_params: dict, *, hook: str, body: str, parent: dict) -> dict:
    """Stored ``Job.params`` for one remake variant (format kept, hook swapped).

    Underscore-prefixed runtime markers (wallet holds, correlation ids,
    auto-publish requests, content-gate records) never carry over — the loop
    schedules publishing itself.
    """
    base = {k: v for k, v in dict(winner_params or {}).items() if not str(k).startswith("_")}
    base.pop("source_context", None)
    script = f"{hook} {body}".strip() if body else ""
    return {
        **base,
        "video_script": script,
        "video_subject": base.get("video_subject") or hook,
        "variants": 1,
        "platforms": [],
        "_winner_loop_parent": parent,
    }


def _build_render_params(stored: dict) -> Any:
    from app.services import reelforge

    allowed = {f.name for f in dataclasses.fields(reelforge.ReelForgeParams)}
    filtered = {k: v for k, v in stored.items() if k in allowed}
    filtered["platforms"] = ()
    if isinstance(filtered.get("effects"), list):
        filtered["effects"] = tuple(filtered["effects"])
    try:
        return reelforge.ReelForgeParams(**filtered)
    except (TypeError, ValueError) as exc:
        raise RemakeError(f"the winning variant's settings can no longer be rendered: {exc}", status_code=422) from exc


# --------------------------------------------------------------------------- #
# Remake
# --------------------------------------------------------------------------- #
def _anchor_locked(session: Any, batch_id: str, user_id: str) -> Any:
    from sqlalchemy import select

    from app.models.db.models import Job

    stmt = (
        select(Job)
        .where(Job.batch_id == batch_id, Job.user_id == user_id)
        .order_by(Job.created_at.asc(), Job.id.asc())
        .limit(1)
        .with_for_update()
    )
    return session.execute(stmt).scalars().first()


def _record(job_id: str, status: str, message: str, payload: dict | None = None) -> None:
    try:
        from app.telemetry import events as telemetry_events

        telemetry_events.record_event(job_id, LOOP_EVENT_STAGE, status, message=message, payload=payload or {})
    except Exception:  # pragma: no cover - telemetry is best-effort
        pass


def remake_winner(
    user_id: str,
    batch_id: str,
    *,
    source: str,
    accept_low_confidence: bool = False,
    generation_guard: Any = None,
) -> RemakeResult:
    """Render ``REMAKE_VARIANTS`` new variants from ``batch_id``'s winner.

    ``generation_guard(session, credits)`` is the caller's access check (the HTTP
    path passes the pilot allowlist/rate/spend gate bound to its request). The
    auto path passes ``None`` and is refused while the internal pilot is on.
    Idempotent: a batch that was already remade returns the existing remake.
    """
    from app.domains.reels.policy import JOB_DEBIT_REASON, job_cost, job_credits
    from app.models.db.base import get_session
    from app.models.db.models import Job
    from app.models.db.repositories import CreditRepository, JobRepository

    # 1) Read the winner (short transaction) and write the hooks OUTSIDE any lock.
    with get_session() as session:
        anchor = _anchor_locked(session, batch_id, user_id)
        if anchor is None:
            raise RemakeError("project not found", status_code=404)
        state = read_state(anchor)
        if state.get("remake_batch_id"):
            return RemakeResult(
                batch_id=str(state["remake_batch_id"]),
                job_ids=tuple(state.get("remake_job_ids") or ()),
                hooks=tuple(state.get("remake_hooks") or ()),
                credits=0,
                replayed=True,
            )
        winner_id = str(state.get("winner_job_id") or "")
        if not winner_id:
            raise RemakeError("there is no winner yet — the loop needs published variants with metrics first")
        if not state.get("conclusive") and not accept_low_confidence:
            raise RemakeError(
                "the winner is low-confidence; confirm to remake it anyway", status_code=409
            )
        winner = session.get(Job, winner_id)
        if winner is None or str(winner.user_id) != str(user_id):
            raise RemakeError("winning variant not found", status_code=404)
        hook, body = winning_hook(winner)
        winner_params = dict(winner.params or {})
    if not hook:
        raise RemakeError("the winning variant has no script or subject to build new hooks from", status_code=422)

    hooks = hook_variants(
        hook,
        topic=str(winner_params.get("video_subject") or ""),
        language=str(winner_params.get("language") or "auto"),
    )
    if len(hooks) < REMAKE_VARIANTS:
        raise RemakeError(
            "could not write 3 distinct hook variants; non-English remakes need an LLM provider configured",
            status_code=422,
        )

    parent = {"batch_id": batch_id, "winner_job_id": winner_id, "hook": hook}
    stored = [remake_params(winner_params, hook=h, body=body, parent=parent) for h in hooks]
    render_params = [_build_render_params(p) for p in stored]
    # M3.1 (MD8): a remake is priced like a create (by length, presenter floor),
    # never below the flat per-reel knob.
    cost = max([int(job_cost())] + [int(job_credits(p)) for p in render_params])
    total = cost * REMAKE_VARIANTS
    new_batch_id = uuid.uuid4().hex

    # 2) One locked transaction: cap check, job rows, debits, state links.
    with get_session() as session:
        anchor = _anchor_locked(session, batch_id, user_id)
        state = read_state(anchor) if anchor is not None else {}
        if anchor is None:
            raise RemakeError("project not found", status_code=404)
        if state.get("remake_batch_id"):  # a concurrent remake won the race
            return RemakeResult(
                batch_id=str(state["remake_batch_id"]),
                job_ids=tuple(state.get("remake_job_ids") or ()),
                hooks=tuple(state.get("remake_hooks") or ()),
                credits=0,
                replayed=True,
            )
        root_id = str(state.get("root_batch_id") or batch_id)
        root = anchor if root_id == batch_id else _anchor_locked(session, root_id, user_id)
        root_state = read_state(root) if root is not None else state
        cap = int(root_state.get("spend_cap_credits", state.get("spend_cap_credits", 0)) or 0)
        spent = int(root_state.get("spent_credits", 0) or 0)
        if spent + total > cap:
            write_state(anchor, {**state, "status": "cap_reached",
                                 "note": f"Spend cap reached: {spent} of {cap} credits used; a remake costs {total}."})
            session.commit()
            _record(anchor.id, "cap_reached", f"remake needs {total} credits; {cap - spent} left under the cap",
                    {"spent": spent, "cap": cap, "cost": total, "source": source})
            raise RemakeError(
                f"spend cap reached ({spent} of {cap} credits used; a remake costs {total})", status_code=402
            )
        if generation_guard is not None:
            generation_guard(session, total)
        else:
            from app.core.capabilities import pilot_enabled

            if pilot_enabled():
                raise RemakeError("automatic remakes are paused during the internal pilot; remake manually", status_code=403)

        # H3: a presenter remake is Pro and Agency only, under the monthly cap,
        # like a create (402 before any job row or debit).
        from app.domains.reels import pricing as _pricing
        from app.domains.reels.policy import require_presenter_allowed

        try:
            require_presenter_allowed(session, user_id, render_params[0], REMAKE_VARIANTS)
        except _pricing.PricingError as exc:
            raise RemakeError(str(exc.detail), status_code=exc.status_code) from exc

        repo = JobRepository(session)
        job_ids: list[str] = []
        for params in stored:
            job = repo.create(user_id=user_id, kind="avatar_reel", params=params, batch_id=new_batch_id)
            job_ids.append(job.id)
        try:
            for jid in job_ids:
                CreditRepository(session).debit(user_id, cost, jid, JOB_DEBIT_REASON)
        except ValueError as exc:
            raise RemakeError(f"insufficient credits: {exc}", status_code=402) from exc

        child_anchor = repo.get(job_ids[0])
        write_state(child_anchor, new_state(
            batch_id=new_batch_id,
            config={k: state.get(k) for k in ("mode", "spend_cap_credits", "check_after_hours", "min_views")},
            platforms=list(state.get("platforms") or []),
            root_batch_id=root_id,
            parent_batch_id=batch_id,
            generation=int(state.get("generation", 1) or 1) + 1,
        ))
        write_state(anchor, {
            **state,
            "status": "remade",
            "note": "",
            "remake_batch_id": new_batch_id,
            "remake_job_ids": job_ids,
            "remake_hooks": hooks,
            "remade_by": source,
            **({"spent_credits": spent + total, "children": [*root_state.get("children", []), new_batch_id]}
               if root is anchor else {}),
        })
        if root is not None and root is not anchor:
            write_state(root, {
                **root_state,
                "spent_credits": spent + total,
                "children": [*root_state.get("children", []), new_batch_id],
            })
        anchor_id = anchor.id
        root_anchor_id = root.id if root is not None else anchor.id

    _record(anchor_id, "remake_started",
            f"{source} remake: {REMAKE_VARIANTS} new variants from the winning hook ({total} credits)",
            {"remake_batch_id": new_batch_id, "job_ids": job_ids, "hooks": hooks, "source": source})

    # 3) Enqueue after commit; reconcile failures with a refund.
    failures: list[str] = []
    from app.workers.pipeline import start_pipeline

    for jid, params in zip(job_ids, render_params):
        try:
            task_id = start_pipeline(jid, params)
            with get_session() as session:
                JobRepository(session).set_celery_task_id(jid, task_id)
        except Exception as exc:  # noqa: BLE001 - enqueue failure must not orphan a debit
            logger.error(f"remake enqueue failed for {jid}: {exc}")
            failures.append(jid)
            _refund_failed_enqueue(user_id, jid, cost, str(exc), root_anchor_id)

    if failures:
        _record(anchor_id, "remake_failed",
                f"{len(failures)} remake variant(s) could not be queued and were refunded",
                {"job_ids": failures})
    return RemakeResult(
        batch_id=new_batch_id,
        job_ids=tuple(job_ids),
        hooks=tuple(hooks),
        credits=total - cost * len(failures),
        enqueue_failures=tuple(failures),
    )


def _refund_failed_enqueue(user_id: str, job_id: str, cost: int, error: str, root_anchor_id: str) -> None:
    """Fail + refund one un-enqueued remake job and give the credits back to the cap."""
    from app.models.db.base import get_session
    from app.models.db.models import Job
    from app.models.db.repositories import CreditRepository, JobRepository

    try:
        with get_session() as session:
            JobRepository(session).mark_failed(job_id, "enqueue", error)
        with get_session() as session:
            CreditRepository(session).grant(user_id, cost, _REMAKE_REFUND_REASON, job_id=job_id)
        with get_session() as session:
            root = session.get(Job, root_anchor_id, with_for_update=True)
            if root is not None:
                root_state = read_state(root)
                write_state(root, {**root_state,
                                   "spent_credits": max(0, int(root_state.get("spent_credits", 0) or 0) - cost)})
    except Exception as exc:  # noqa: BLE001 - reconcile is best-effort and logged
        logger.error(f"remake refund reconcile failed for {job_id}: {exc}")


__all__ = [
    "RemakeError",
    "RemakeResult",
    "hook_variants",
    "remake_params",
    "remake_winner",
    "split_hook",
    "winning_hook",
]
