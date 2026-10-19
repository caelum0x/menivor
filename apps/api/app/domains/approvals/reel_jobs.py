"""Create reel-pipeline jobs from an approved item (no HTTP request involved).

Mirrors the ordering of ``POST /jobs`` and the insights remake: validate the
render params and the deployment's format availability first, then create the
job rows AND debit their credits in one transaction (402 when the balance is
short, nothing created), and only then enqueue each pipeline. A job whose
enqueue fails is marked failed and refunded.

The approval itself is the owner's consent to spend the credits; the approval
summary states the cost before the decision.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger

from app.domains.approvals.adapters import ApprovalExecError

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover - reported as a 503 by the caller
    get_session = None  # type: ignore[assignment]

_REFUND_REASON = "refund"


@dataclass(frozen=True)
class QueuedJobs:
    job_ids: tuple[str, ...]
    credits: int
    enqueue_failures: tuple[str, ...] = ()


def cost_per_job() -> int:
    from app.domains.reels.policy import job_cost

    return int(job_cost())


def job_credits(params: Any) -> int:
    """Standard credits for one reel (M3.1 table), never below the flat knob."""
    from app.domains.reels.policy import job_credits as _job_credits

    return max(cost_per_job(), int(_job_credits(params)))


def render_params(stored: dict) -> Any:
    """A validated ``ReelForgeParams`` from a job-request ``params`` dict."""
    from app.services import reelforge

    allowed = {f.name for f in dataclasses.fields(reelforge.ReelForgeParams)}
    filtered = {k: v for k, v in stored.items() if k in allowed}
    filtered["platforms"] = ()
    if isinstance(filtered.get("effects"), list):
        filtered["effects"] = tuple(filtered["effects"])
    try:
        return reelforge.ReelForgeParams(**filtered)
    except (TypeError, ValueError) as exc:
        raise ApprovalExecError(f"the reel settings are invalid: {exc}", status_code=422) from exc


def check_available(params: Any) -> None:
    """Refuse (402) a format this deployment cannot produce, before any debit."""
    from app.core.launch.formats import params_lock

    needs_llm = not str(getattr(params, "video_script", "") or "").strip()
    locked = params_lock(params, needs_script_llm=needs_llm)
    if locked is not None:
        raise ApprovalExecError(f"This format is not available yet ({locked[1]})", status_code=402)


def queue_reel_jobs(user_id: str, requests: list[dict], *, source_context: dict,
                    start: Callable[[str, Any], str] | None = None) -> QueuedJobs:
    """Create + debit + enqueue one reel job per ``POST /jobs`` body in ``requests``."""
    if get_session is None:
        raise ApprovalExecError("persistence is not available", status_code=503)
    if not requests:
        raise ApprovalExecError("nothing to render", status_code=422)
    from app.core.capabilities import pilot_enabled

    if pilot_enabled():
        raise ApprovalExecError("reels are not created from approvals during the internal pilot; "
                                "make them from the capture page", status_code=403)
    from app.domains.reels.policy import JOB_DEBIT_REASON
    from app.models.db.repositories import CreditRepository, JobRepository

    prepared: list[tuple[dict, Any]] = []
    for body in requests:
        stored = dict(body.get("params") or {})
        params = render_params(stored)
        if getattr(params, "layout", "") != "captions_only" and not str(getattr(params, "avatar_id", "") or ""):
            raise ApprovalExecError("avatar reels need an avatar; make them from the capture page", status_code=422)
        check_available(params)
        record = {**{k: v for k, v in params.__dict__.items()}, "tos_disclosure": bool(body.get("tos_disclosure")),
                  "source_context": dict(source_context), "_correlation_id": f"approval-{source_context.get('id', '')}"}
        record["platforms"] = []
        prepared.append((record, params))

    # M3.1 (MD8): each reel is priced like a create (by length, presenter floor).
    costs = [job_credits(params) for _record, params in prepared]
    job_ids: list[str] = []
    with get_session() as session:  # type: ignore[misc]
        repo = JobRepository(session)
        for record, _params in prepared:
            job_ids.append(repo.create(user_id=user_id, kind="avatar_reel", params=record).id)
        try:
            for jid, cost in zip(job_ids, costs):
                CreditRepository(session).debit(user_id, cost, jid, JOB_DEBIT_REASON)
        except ValueError as exc:
            raise ApprovalExecError(f"insufficient credits: {exc}", status_code=402) from exc

    if start is None:
        from app.workers.pipeline import start_pipeline as start

    failures: list[str] = []
    refunded = 0
    for jid, (_record, params), cost in zip(job_ids, prepared, costs):
        try:
            task_id = start(jid, params)
            with get_session() as session:  # type: ignore[misc]
                JobRepository(session).set_celery_task_id(jid, task_id)
        except Exception as exc:  # noqa: BLE001 - an enqueue failure must not keep the credits
            logger.error(f"approvals: reel enqueue failed for {jid}: {exc}")
            failures.append(jid)
            _refund(user_id, jid, cost, str(exc))
            refunded += cost
    return QueuedJobs(job_ids=tuple(job_ids), credits=sum(costs) - refunded,
                      enqueue_failures=tuple(failures))


def _refund(user_id: str, job_id: str, cost: int, error: str) -> None:
    from app.models.db.repositories import CreditRepository, JobRepository

    try:
        with get_session() as session:  # type: ignore[misc]
            JobRepository(session).mark_failed(job_id, "enqueue", error[:500])
        with get_session() as session:  # type: ignore[misc]
            CreditRepository(session).grant(user_id, cost, _REFUND_REASON, job_id=job_id)
    except Exception as exc:  # noqa: BLE001 - reconcile is best-effort and logged
        logger.error(f"approvals: refund reconcile failed for {job_id}: {exc}")


__all__ = ["QueuedJobs", "check_available", "cost_per_job", "queue_reel_jobs", "render_params"]
