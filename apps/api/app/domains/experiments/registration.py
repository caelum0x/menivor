"""Register a one-flow multi-variant run as a 1-body/N-hooks experiment.

A run is the 2..3 reels one create request produced for the same subject, each
opening with a different hook. Registering it:

1. links the jobs under one ``batch_id`` (topic runs already share one from the
   ``variants`` fan-out; link runs are created one job at a time and get one
   here), which is the unit the remake-winner loop works on;
2. persists an :class:`~app.models.db.experiments.Experiment` keyed
   ``run:<batch_id>`` with one variant per hook (``<hook_style>:<job_id>``);
3. opens the insights remake-winner loop on the batch in ``manual`` mode with no
   auto-publish platforms, so the beat tick starts tracking the run right away
   (it waits for posts, measures, ranks) without spending credits or posting
   anything on the creator's behalf. The creator can switch to auto-publish or
   auto-remake from the loop settings.

:func:`sync_run` mirrors the loop's measured numbers back onto the experiment
variants and re-evaluates the retention-weighted verdict.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import select

from .hook_styles import HookStyleError, normalize_hook_style

EXPERIMENT_KEY_PREFIX = "run:"
MIN_RUN_VARIANTS = 2
MAX_RUN_VARIANTS = 3
_REEL_JOB_KIND = "avatar_reel"
_MAX_HOOK_REF = 120


class RunRegistrationError(ValueError):
    """The run cannot be registered; ``status_code`` is the HTTP mapping."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class RunVariant:
    """One reel of the run and the hook angle it opens with."""

    job_id: str
    hook_style: str = ""


@dataclass(frozen=True)
class RunRegistration:
    """Outcome of :func:`register_run`."""

    batch_id: str
    experiment_key: str
    experiment_id: str
    created: bool


def experiment_key_for(batch_id: str) -> str:
    return f"{EXPERIMENT_KEY_PREFIX}{batch_id}"


def hook_ref_for(hook_style: str, job_id: str) -> str:
    return f"{hook_style or 'hook'}:{job_id}"[:_MAX_HOOK_REF]


def job_id_of_hook_ref(hook_ref: str) -> str:
    return str(hook_ref or "").rsplit(":", 1)[-1]


def _validated_variants(variants: list[RunVariant]) -> list[RunVariant]:
    if not MIN_RUN_VARIANTS <= len(variants) <= MAX_RUN_VARIANTS:
        raise RunRegistrationError(
            f"a run needs {MIN_RUN_VARIANTS}-{MAX_RUN_VARIANTS} variants, got {len(variants)}"
        )
    ids = [str(v.job_id or "").strip() for v in variants]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise RunRegistrationError("every variant needs a distinct job_id")
    out: list[RunVariant] = []
    for job_id, variant in zip(ids, variants):
        try:
            style = normalize_hook_style(variant.hook_style)
        except HookStyleError as exc:
            raise RunRegistrationError(str(exc)) from exc
        out.append(RunVariant(job_id=job_id, hook_style=style))
    return out


def _owned_jobs(session: Any, user_id: str, job_ids: list[str]) -> dict[str, Any]:
    from app.models.db.models import Job

    rows = session.execute(
        select(Job).where(
            Job.id.in_(job_ids),
            Job.user_id == user_id,
            Job.deleted_at.is_(None),
        )
    ).scalars().all()
    found = {row.id: row for row in rows}
    missing = [j for j in job_ids if j not in found]
    if missing:
        # Foreign and unknown ids look the same (no existence oracle).
        raise RunRegistrationError(f"jobs not found: {', '.join(missing)}", 404)
    wrong_kind = [j for j, row in found.items() if str(row.kind or _REEL_JOB_KIND) != _REEL_JOB_KIND]
    if wrong_kind:
        raise RunRegistrationError(f"only reel jobs can form a run: {', '.join(wrong_kind)}")
    return found


def _resolve_batch(session: Any, user_id: str, jobs: dict[str, Any]) -> str:
    """The run's shared batch id: the existing one, or a fresh one assigned now."""
    from app.models.db.repositories import JobRepository

    batches = {row.batch_id for row in jobs.values()}
    if batches == {None}:
        batch_id = uuid.uuid4().hex
        for row in jobs.values():
            row.batch_id = batch_id
        session.flush()
        return batch_id
    if len(batches) != 1 or None in batches:
        raise RunRegistrationError("the jobs already belong to different runs", 409)
    batch_id = str(next(iter(batches)))
    members = {row.id for row in JobRepository(session).list_by_batch(batch_id, user_id)}
    if members != set(jobs):
        raise RunRegistrationError("the run must list every reel of its batch", 409)
    return batch_id


def register_run(
    session: Any,
    *,
    user_id: str,
    variants: list[RunVariant],
    body_ref: str = "",
) -> RunRegistration:
    """Link the jobs into one batch and persist the experiment (idempotent).

    Re-registering the same jobs returns the existing experiment with
    ``created=False``. Runs inside the caller's transaction; the caller commits
    and then calls :func:`open_winner_loop`.
    """
    from app.domains.publishing.experiment_repo import ExperimentError, ExperimentRepository

    clean = _validated_variants(variants)
    jobs = _owned_jobs(session, user_id, [v.job_id for v in clean])
    batch_id = _resolve_batch(session, user_id, jobs)
    key = experiment_key_for(batch_id)
    repo = ExperimentRepository(session)
    existing = repo.get_by_key(key)
    if existing is not None:
        if str(existing.user_id) != str(user_id):
            raise RunRegistrationError("run not found", 404)
        return RunRegistration(batch_id, key, existing.id, created=False)
    try:
        experiment = repo.create(
            user_id=user_id,
            experiment_key=key,
            hook_refs=[hook_ref_for(v.hook_style, v.job_id) for v in clean],
            body_ref=str(body_ref or batch_id)[:120],
        )
    except ExperimentError as exc:
        raise RunRegistrationError(str(exc)) from exc
    return RunRegistration(batch_id, key, experiment.id, created=True)


def open_winner_loop(user_id: str, batch_id: str) -> dict:
    """Open the remake-winner loop on the batch unless one is already configured.

    ``manual`` mode with no platforms: the tick tracks the run and ranks it once
    the creator posts the variants, but nothing is published or remade (no
    credits spent) without the creator's action. Returns the loop state.
    """
    from app.domains.insights.winner_loop_service import configure, find_anchor
    from app.domains.insights.winner_loop_state import read_state
    from app.models.db.base import get_session

    with get_session() as session:
        anchor = find_anchor(session, batch_id, user_id)
        existing = read_state(anchor) if anchor is not None else {}
    if existing:
        return existing
    return configure(
        user_id,
        batch_id,
        mode="manual",
        platforms=[],
        spend_cap_credits=None,
        check_after_hours=None,
        min_views=None,
    )


def register_run_and_open_loop(
    *, user_id: str, variants: list[RunVariant], body_ref: str = ""
) -> RunRegistration:
    """Own-transaction convenience used right after a batch is created."""
    from app.models.db.base import get_session

    with get_session() as session:
        registration = register_run(session, user_id=user_id, variants=variants, body_ref=body_ref)
    try:
        open_winner_loop(user_id, registration.batch_id)
    except Exception as exc:  # noqa: BLE001 - the experiment row stands; the loop can be opened later
        logger.warning(f"could not open the winner loop for run {registration.batch_id}: {exc}")
    return registration


def _ratio(value: Any, stored: float | None) -> float | None:
    """A measured ratio clamped to [0, 1]; the stored value when none was measured.

    ``None`` means the platform did not report the metric, which must never be
    written as a measured 0. The stored value may itself be ``None`` (a nullable
    completion/rewatch rate that was never measured) and stays ``None``.
    """
    if value is None:
        return stored
    try:
        number = float(value)
    except (TypeError, ValueError):
        return stored
    if number != number:  # NaN
        return stored
    return max(0.0, min(1.0, number))


def sync_run(session: Any, *, user_id: str, batch_id: str) -> tuple[Any, list[Any], dict]:
    """Copy the loop's measured numbers onto the experiment and re-evaluate.

    Only metrics the loop actually measured are written: views and engagement
    rate always; average watch fraction, completion rate and rewatch rate only
    when a platform reported them (``None`` in the loop state keeps the stored
    value). The winner loop calls this on every tick that has measurements.
    Returns ``(experiment, variants, loop_state)``.
    """
    from app.domains.insights.winner_loop_service import find_anchor
    from app.domains.insights.winner_loop_state import read_state
    from app.domains.publishing.experiment_repo import ExperimentRepository

    repo = ExperimentRepository(session)
    experiment = repo.get_by_key(experiment_key_for(batch_id))
    if experiment is None or str(experiment.user_id) != str(user_id):
        raise RunRegistrationError("run not found", 404)
    anchor = find_anchor(session, batch_id, user_id)
    state = read_state(anchor) if anchor is not None else {}
    measured = {
        str(item.get("job_id")): item
        for item in (state.get("variants") or [])
        if isinstance(item, dict) and item.get("job_id")
    }
    changed = False
    for variant in repo.variants(experiment.id):
        numbers = measured.get(job_id_of_hook_ref(variant.hook_ref))
        if numbers is None:
            continue
        repo.ingest_metrics(
            experiment_key=experiment.experiment_key,
            variant_id=variant.id,
            views=max(0, int(numbers.get("views") or 0)),
            completion_rate=_ratio(numbers.get("completion_rate"), variant.completion_rate),
            avg_watch_frac=_ratio(numbers.get("avg_watch_frac"), variant.avg_watch_frac),
            rewatch_rate=_ratio(numbers.get("rewatch_rate"), variant.rewatch_rate),
            engagement_rate=_ratio(numbers.get("engagement_rate"), variant.engagement_rate),
        )
        changed = True
    if changed:
        experiment = repo.evaluate(experiment.experiment_key)
    return experiment, repo.variants(experiment.id), state


__all__ = [
    "EXPERIMENT_KEY_PREFIX",
    "MAX_RUN_VARIANTS",
    "MIN_RUN_VARIANTS",
    "RunRegistration",
    "RunRegistrationError",
    "RunVariant",
    "experiment_key_for",
    "hook_ref_for",
    "job_id_of_hook_ref",
    "open_winner_loop",
    "register_run",
    "register_run_and_open_loop",
    "sync_run",
]
