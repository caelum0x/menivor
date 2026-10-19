"""Unattended channel runner — the orchestration layer over the pure planner.

A faceless operator points the runner at a channel: a source list (an inline
list, a CSV, or a subreddit) is turned into narration scripts, expanded by the
PURE :mod:`app.domains.series.fanout` planner into de-duplicated render+publish
specs, rendered as normal ReelForge avatar jobs, and later cross-posted with
per-account pacing. This module is pure orchestration — every impure seam
(script/param derivation, job creation, render enqueue, publish scheduling,
persistence) is injected via :class:`RunnerDeps`, so the whole flow is
unit-testable with in-memory fakes and no Celery/DB/network.

Contract obligations (enforced by tests, not by editing ``domains/stories``):

* Script + params come EXCLUSIVELY from ``app.domains.stories.contract`` (the
  shared seam) — the runner never duplicates the template/param mapping and
  never imports the reels router.
* Every render is enqueued with ``platforms=()`` so the Celery DAG SKIPS
  ``stage_upload``; publishing happens separately through
  ``scheduling_policy.decide`` -> ``scheduler.schedule_publish`` -> the existing
  ``process_due_publishes`` beat, with pacing.
* Dedupe authority is ``fanout.spec_hash`` (account-scoped, 16-hex); it is
  persisted via :class:`ChannelClipRepository` and fed back through
  ``seen_hashes(channel_id)`` into ``plan_fanout`` for cross-run dedupe.
* Platform-name bridge: ``schedule_publish`` speaks ``youtube_shorts`` while
  ``scheduling_policy`` speaks ``youtube`` — the runner maps
  ``youtube_shorts -> youtube`` when calling ``platform_config`` / ``decide``.
* ``pace_by_account`` caps each account at that platform's ``daily_cap`` (or a
  channel override) so a clip the scheduler could only defer to a FUTURE day is
  never rendered.
* Every render pays (MN1): each job is debited its per-SKU price (H3:
  ``reels/pricing.py`` by length and presenter floor, like a create) before it is
  enqueued. The first render the balance cannot cover stops the run, pauses
  the channel with reason ``credits`` and emits a ``channel_paused`` signal on
  :data:`channel_signals`. A paused channel resumes by itself on the next run
  that can pay. A run that renders nothing for lack of credits raises a 402
  (:class:`app.domains.reels.charge.CreditsRequired`) after the pause is saved.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from loguru import logger

from app.domains.publishing import scheduling_policy
from app.events.bus import Event, EventBus
from app.domains.series.fanout import (
    ClipSpec,
    FanoutMatrix,
    plan_fanout,
)

# The shared story contract owns these; imported READ-ONLY (and lazily, in the
# default seam, so merely importing the runner never requires the stories layer
# to exist yet). Tests inject a fake contract seam instead.
MINECRAFT_SLUG = "minecraft-reddit-split"
DEFAULT_MAX_WORDS = 130

#: Minimum lead before the earliest candidate publish time, so a decision that
#: is "allowed now" still lands strictly in the future (``schedule_publish``
#: rejects a non-future time).
_PUBLISH_LEAD = timedelta(minutes=1)

#: Signal emitted when a channel stops for lack of credits. Subscribers (the
#: lifecycle mail, MG5) get ``Event(type=CHANNEL_PAUSED, key=channel_id,
#: payload={"user_id", "reason", "run_id", "rendered"})``. Emitted once per
#: pause (not again while the channel stays paused).
CHANNEL_PAUSED = "channel_paused"
PAUSE_REASON_CREDITS = "credits"
channel_signals = EventBus()


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ChannelRunConfig:
    """Immutable configuration for one unattended channel.

    ``platforms`` are the CROSS-POST targets used only at publish-scheduling time
    (schedule_publish names: ``tiktok`` | ``instagram`` | ``youtube_shorts``);
    renders ALWAYS go out with ``platforms=()`` so the DAG skips ``stage_upload``.
    """

    channel_id: str
    user_id: str
    hooks: tuple[str, ...] = ("",)
    aspects: tuple[str, ...] = ("9:16",)
    accounts: tuple[str, ...] = ("",)
    max_per_account: int | None = None            # override; else platform daily_cap
    platforms: tuple[str, ...] = ()               # cross-post targets (publish only)
    voice_id: str | None = None
    subject: str = ""
    template_slug: str = MINECRAFT_SLUG
    max_words: int = DEFAULT_MAX_WORDS

    def as_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "user_id": self.user_id,
            "hooks": list(self.hooks),
            "aspects": list(self.aspects),
            "accounts": list(self.accounts),
            "max_per_account": self.max_per_account,
            "platforms": list(self.platforms),
            "voice_id": self.voice_id,
            "subject": self.subject,
            "template_slug": self.template_slug,
            "max_words": self.max_words,
        }


# --------------------------------------------------------------------------- #
# Injectable seams (protocols) + dependency bundle
# --------------------------------------------------------------------------- #
class ContractSeam(Protocol):
    """The story-contract seam the runner drives (``domains.stories.contract``)."""

    def build_script(self, item: Mapping[str, Any], *, max_words: int) -> str: ...

    def build_params(
        self,
        script: str,
        *,
        subject: str,
        aspect: str,
        voice_id: str | None,
        platforms: tuple[str, ...],
    ) -> Any: ...


class JobRepoSeam(Protocol):
    def create(self, *, user_id: str, kind: str, params: dict, batch_id: str | None) -> Any: ...

    def mark_failed(self, job_id: str, stage: str, error: str) -> Any: ...


class ClipRepoSeam(Protocol):
    def seen_hashes(self, channel_id: str) -> set[str]: ...

    def create(self, *, channel_id: str, run_id: str, spec_hash: str, job_id: str, account: str, platform: str) -> Any: ...

    def list_pending_publish(self, channel_id: str) -> Sequence[Any]: ...

    def mark_scheduled(self, clip_id: str, scheduled_publish_id: str) -> Any: ...


@dataclass
class RunnerDeps:
    """Everything impure the runner needs — injectable for tests.

    ``job_repo`` / ``clip_repo`` are session-bound repositories; ``start_pipeline``
    and ``schedule_publish`` are the real Celery-enqueue and scheduler seams;
    ``contract`` defaults to the shared story contract (lazy import). ``session``
    is passed straight through to ``schedule_publish`` (which owns its own txn
    semantics) and is otherwise opaque to the runner.
    """

    job_repo: JobRepoSeam
    clip_repo: ClipRepoSeam
    start_pipeline: Callable[[str, Any], str]
    schedule_publish: Callable[..., Any]
    session: Any = None
    contract: ContractSeam | None = None
    #: ``charge(user_id, job) -> bool``: debit one render for ``job``. Default:
    #: the credit ledger on ``session``. Fails closed (no debit, no render).
    charge: Callable[[str, Any], bool] | None = None
    #: ``refund(job_id) -> int``: return a failed enqueue's debit once.
    refund: Callable[[str], int] | None = None
    #: ``pause(channel_id, reason) -> bool``: persist the pause; True when the
    #: channel was not already paused for ``reason`` (so the signal fires once).
    pause: Callable[[str, str], bool] | None = None
    #: ``resume(channel_id) -> bool``: clear a pause after a paid render; True
    #: when a pause was cleared (only then is the session committed).
    resume: Callable[[str], bool] | None = None
    #: Raise a 402 when a run renders nothing for lack of credits.
    raise_when_unfunded: bool = True

    def resolved_contract(self) -> ContractSeam:
        return self.contract if self.contract is not None else _default_contract()


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
@dataclass
class RunResult:
    """Outcome of one :func:`run_channel` pass."""

    run_id: str
    planned: int = 0                 # combinations expanded by plan_fanout (after dedupe)
    skipped_duplicates: int = 0      # combinations already seen (cross-run dedupe)
    paced_out: int = 0               # fresh specs deferred by the per-account cap
    rendered: int = 0                # jobs successfully created + enqueued
    enqueue_failures: int = 0        # specs whose enqueue was reconciled (refunded/failed)
    unfunded: int = 0                # specs left unrendered because credits ran out
    unfunded_needed: int = 0         # per-SKU credits the first unfunded render needed
    paused_reason: str = ""          # "credits" when the run stopped for lack of credits
    job_ids: list[str] = field(default_factory=list)
    clip_ids: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "planned": self.planned,
            "skipped_duplicates": self.skipped_duplicates,
            "paced_out": self.paced_out,
            "rendered": self.rendered,
            "enqueue_failures": self.enqueue_failures,
            "unfunded": self.unfunded,
            "paused_for_credits": int(self.paused_reason == PAUSE_REASON_CREDITS),
        }


@dataclass
class ScheduleResult:
    """Outcome of one :func:`schedule_due` pass."""

    scheduled: int = 0
    considered: int = 0
    clip_ids: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {"considered": self.considered, "scheduled": self.scheduled}


# --------------------------------------------------------------------------- #
# Source adapters — each yields ``{url|title, body, ...}`` dicts
# --------------------------------------------------------------------------- #
def items_from_list(rows: Iterable[Mapping[str, Any] | str]) -> list[dict]:
    """Normalize an inline source list into item dicts.

    Accepts already-shaped ``{title|url, body}`` mappings or bare strings (a bare
    string becomes the ``body``). Blank items are dropped.
    """
    items: list[dict] = []
    for row in rows or []:
        if isinstance(row, str):
            body = row.strip()
            if body:
                items.append({"title": "", "body": body})
            continue
        if not isinstance(row, Mapping):
            continue
        item = {str(k): v for k, v in row.items()}
        if (str(item.get("body") or "").strip() or str(item.get("url") or "").strip()
                or str(item.get("title") or "").strip()):
            items.append(item)
    return items


def items_from_csv(text: str) -> list[dict]:
    """Parse CSV text (header row) into item dicts, one per data row."""
    reader = csv.DictReader(io.StringIO(text or ""))
    return items_from_list(list(reader))


def items_from_reddit(threads: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Normalize pre-fetched reddit thread dicts into item dicts.

    Fetching itself is the stories domain's impure seam; this adapter only shapes
    already-fetched thread dicts (``title`` / ``subreddit`` / ``author`` / ``body``
    / ``top_comments`` / ``url``) into the runner's item form.
    """
    return items_from_list(threads)


# --------------------------------------------------------------------------- #
# Default contract seam (lazy — the stories layer may be built in parallel)
# --------------------------------------------------------------------------- #
class _StoriesContractAdapter:
    """Adapts the shared ``domains.stories.contract`` to :class:`ContractSeam`.

    Imports lazily so importing the runner never requires the stories layer to
    exist. Builds a :class:`RedditThread` from a runner item dict and delegates
    the narration + param fold to the contract (no duplicated mapping).
    """

    def build_script(self, item: Mapping[str, Any], *, max_words: int) -> str:
        from app.domains.stories import contract as stories_contract

        thread = self._to_thread(item, stories_contract)
        return stories_contract.build_story_script(thread, max_words=max_words)

    def build_params(
        self,
        script: str,
        *,
        subject: str,
        aspect: str,
        voice_id: str | None,
        platforms: tuple[str, ...],
    ) -> Any:
        from app.domains.stories import contract as stories_contract

        return stories_contract.story_params(
            script,
            subject=subject,
            aspect=aspect,
            voice_id=voice_id,
            platforms=platforms,
        )

    @staticmethod
    def _to_thread(item: Mapping[str, Any], stories_contract: Any) -> Any:
        raw_comments = item.get("top_comments") or ()
        return stories_contract.RedditThread(
            title=str(item.get("title") or item.get("url") or "").strip(),
            subreddit=str(item.get("subreddit") or "").strip(),
            author=str(item.get("author") or "").strip(),
            body=str(item.get("body") or "").strip(),
            top_comments=tuple(str(c) for c in raw_comments),
        )


def _default_contract() -> ContractSeam:
    return _StoriesContractAdapter()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _policy_platform(platform: str) -> str:
    """Bridge the publish name to the scheduling-policy name.

    ``schedule_publish`` uses ``youtube_shorts``; ``scheduling_policy`` uses
    ``youtube`` (else it silently falls to the ``daily_cap=3`` fallback).
    """
    name = str(platform or "").strip().lower()
    return "youtube" if name == "youtube_shorts" else name


def _pace_cap(config: ChannelRunConfig) -> int:
    """The per-account cap for this run: explicit override, else platform cap.

    Set to the target platform's ``daily_cap`` so a clip the scheduler could
    only defer to a future day is never even rendered. With no target platform
    the policy fallback (``daily_cap=3``) applies.
    """
    if config.max_per_account is not None:
        return int(config.max_per_account)
    platform = config.platforms[0] if config.platforms else ""
    cfg = scheduling_policy.platform_config(_policy_platform(platform))
    return int(cfg["daily_cap"])


def _rendered_today(config: ChannelRunConfig, *, deps: RunnerDeps) -> dict[str, int]:
    """Per-account count of clips already rendered TODAY (optional seam).

    Reads ``clip_repo.rendered_today_counts`` when available; without it returns
    an empty map (per-run pacing only), so in-memory fakes keep working.
    """
    getter = getattr(deps.clip_repo, "rendered_today_counts", None)
    if getter is None:
        return {}
    try:
        counts = getter(config.channel_id)
    except Exception as exc:  # noqa: BLE001 - a pacing read must never abort a run
        logger.error(f"channel {config.channel_id}: rendered_today_counts failed: {exc}")
        return {}
    return {str(k): int(v) for k, v in (counts or {}).items()}


def _pace_with_daily_budget(
    specs: list[ClipSpec], *, cap: int, already: Mapping[str, int]
) -> list[ClipSpec]:
    """Cap specs per account against the DAY's remaining budget.

    ``already`` is each account's clips already rendered earlier today; the input
    order is kept and overflow is left for a future window. ``cap <= 0`` means no
    cap (identical to ``pace_by_account``). Generalizes ``pace_by_account`` (empty
    ``already`` reproduces the per-run behavior exactly).
    """
    if cap <= 0:
        return list(specs)
    counts: dict[str, int] = {str(k): int(v) for k, v in (already or {}).items()}
    kept: list[ClipSpec] = []
    for spec in specs:
        n = counts.get(spec.account, 0)
        if n >= cap:
            continue
        counts[spec.account] = n + 1
        kept.append(spec)
    return kept


def _maybe_commit(deps: RunnerDeps) -> None:
    """Commit the runner's session when the seam supports it (best-effort).

    Persisting the job before enqueue (so an already-queued task never dangles
    on a rolled-back ``job_id``) and the clip's ``spec_hash`` right after a
    successful enqueue makes the dedupe key DURABLE per-clip — a crash later in
    the run can no longer roll back an already-enqueued clip and cause a
    double-render on the next tick. In-memory fakes pass a plain ``object()``
    session with no ``commit`` and are unaffected.
    """
    commit = getattr(deps.session, "commit", None)
    if callable(commit):
        try:
            commit()
        except Exception as exc:  # noqa: BLE001 - commit failure handled by caller txn
            logger.error(f"runner commit failed: {exc}")
            raise


def _params_dict(params: Any) -> dict:
    """JSON-safe params dict for ``Job.params`` (asdict for a dataclass)."""
    if dataclasses.is_dataclass(params) and not isinstance(params, type):
        return dataclasses.asdict(params)
    if isinstance(params, Mapping):
        return dict(params)
    return dict(getattr(params, "__dict__", {}))


def _run_id() -> str:
    return uuid.uuid4().hex


# --------------------------------------------------------------------------- #
# run_channel — source -> plan -> pace -> render (commit/enqueue/reconcile)
# --------------------------------------------------------------------------- #
def run_channel(
    config: ChannelRunConfig,
    *,
    source_items: Sequence[Mapping[str, Any]],
    deps: RunnerDeps,
) -> RunResult:
    """Render one unattended pass over ``config``'s source list.

    Flow: derive one narration script per source item (via the shared story
    contract) -> expand into a :class:`FanoutMatrix` -> ``plan_fanout`` (skipping
    ``clip_repo.seen_hashes`` for cross-run dedupe) -> ``pace_by_account`` (cap ==
    platform ``daily_cap`` or override) -> per surviving :class:`ClipSpec`,
    build ``platforms=()`` params, create the job, enqueue the pipeline, and only
    THEN persist the clip's ``spec_hash``. A failed enqueue is reconciled
    (job marked failed) and the ``spec_hash`` is NOT persisted, so the
    combination stays eligible for a later retry.
    """
    contract = deps.resolved_contract()
    run_id = _run_id()
    result = RunResult(run_id=run_id)

    items = list(source_items or [])
    scripts = tuple(
        contract.build_script(item, max_words=config.max_words) for item in items
    )
    scripts = tuple(s for s in scripts if str(s).strip())
    if not scripts:
        logger.info(f"channel {config.channel_id}: no scripts derived; nothing to render")
        return result

    matrix = FanoutMatrix(
        bodies=scripts,
        hooks=tuple(config.hooks) or ("",),
        templates=(config.template_slug,),
        aspects=tuple(config.aspects) or ("9:16",),
        accounts=tuple(config.accounts) or ("",),
    )

    seen = deps.clip_repo.seen_hashes(config.channel_id)
    plan = plan_fanout(matrix, seen_hashes=seen)
    result.skipped_duplicates = plan.skipped_duplicates

    cap = _pace_cap(config)
    # The pace-cap is a per-DAY budget: subtract clips already rendered for each
    # account earlier TODAY so 24 hourly ticks can't jointly exceed the cap.
    already = _rendered_today(config, deps=deps) if cap > 0 else {}
    paced = _pace_with_daily_budget(plan.specs, cap=cap, already=already)
    result.planned = len(plan.specs)
    result.paced_out = len(plan.specs) - len(paced)

    publish_platform = config.platforms[0] if config.platforms else ""

    for index, spec in enumerate(paced):
        funded = _render_one(
            spec,
            config=config,
            run_id=run_id,
            publish_platform=publish_platform,
            contract=contract,
            deps=deps,
            result=result,
        )
        if not funded:
            result.unfunded = len(paced) - index
            _pause_for_credits(config, run_id=run_id, deps=deps, result=result)
            break

    if result.rendered and not result.paused_reason:
        _resume(config, deps)

    logger.info(
        f"channel {config.channel_id} run {run_id}: rendered={result.rendered} "
        f"skipped_dupes={result.skipped_duplicates} paced_out={result.paced_out} "
        f"enqueue_failures={result.enqueue_failures} unfunded={result.unfunded}"
    )
    if result.paused_reason and result.rendered == 0 and deps.raise_when_unfunded:
        from app.domains.reels.charge import CreditsRequired, unit_cost

        needed = result.unfunded_needed or unit_cost()
        raise CreditsRequired(run_id, needed=needed, available=0, what="Autopilot render")
    return result


# --------------------------------------------------------------------------- #
# Charging seams (MN1: every render pays)
# --------------------------------------------------------------------------- #
def _charge(config: ChannelRunConfig, job: Any, deps: RunnerDeps) -> bool:
    """Debit one render for ``job``; any error fails closed (no render)."""
    try:
        if deps.charge is not None:
            return bool(deps.charge(config.user_id, job))
        from app.domains.reels import pricing
        from app.domains.reels.charge import debit_job
        from app.domains.reels.policy import (
            JOB_DEBIT_REASON,
            render_credits,
            require_presenter_allowed,
        )

        params = dict(getattr(job, "params", None) or {})
        premium_plan = None
        if pricing.wants_presenter(_as_params(params)):
            from app.domains.reels import premium

            # H3: presenter reels are Pro and Agency only, under the monthly
            # cap, and their AI-video credits are planned before any debit
            # (SkuLocked / PremiumCreditsRequired -> not funded, nothing debited).
            require_presenter_allowed(deps.session, config.user_id, _as_params(params), 1)
            premium_plan = premium.plan_job(deps.session, config.user_id, _as_params(params), 1)
        # Both debits land together or not at all: a premium debit that fails
        # after the standard debit (a concurrent spend drained the AI-video
        # balance) rolls the standard debit back with it.
        with _savepoint(deps.session):
            # H3: per-SKU price (by length, presenter floor), like a create.
            paid = debit_job(
                deps.session,
                user_id=config.user_id,
                job_id=job.id,
                reason=JOB_DEBIT_REASON,
                amount=render_credits(params),
            )
            if paid and premium_plan is not None:
                from app.domains.reels import premium

                if premium_plan.ai_video_credits > 0 or premium_plan.premium_credits > 0:
                    premium.debit_job(deps.session, config.user_id, job.id, premium_plan)
                # Write what was paid for back onto the job, like a create: the
                # avatar/TTS/music stage guards read the ``_premium`` marker from
                # ``Job.params`` and refuse a paid call without it.
                _store_funded_params(job, params, premium_plan, deps)
        return paid
    except Exception as exc:  # noqa: BLE001 - never render unpaid
        logger.error(f"channel {config.channel_id}: charge failed for job {job.id}: {exc}")
        return False


_FUNDED_FIELDS = ("voice_name", "music_prompt", "bgm_provider")


def _store_funded_params(job: Any, params: dict, plan: Any, deps: RunnerDeps) -> None:
    funded = {
        **params,
        **{k: getattr(plan.params, k) for k in _FUNDED_FIELDS if hasattr(plan.params, k)},
        **plan.marker,
    }
    job.params = funded
    flush = getattr(deps.session, "flush", None)
    if callable(flush):
        flush()


def _savepoint(session: Any) -> Any:
    from contextlib import nullcontext

    begin_nested = getattr(session, "begin_nested", None)
    return begin_nested() if callable(begin_nested) else nullcontext()


def _as_params(params: dict) -> Any:
    """Stored params as a ``ReelForgeParams`` (so premium downgrades can
    ``dataclasses.replace`` it), or a namespace when they no longer fit."""
    from types import SimpleNamespace

    try:
        from app.services.reelforge import ReelForgeParams

        allowed = {f.name for f in dataclasses.fields(ReelForgeParams)}
        data = {k: v for k, v in params.items() if k in allowed}
        for key in ("platforms", "effects"):
            if isinstance(data.get(key), list):
                data[key] = tuple(data[key])
        return ReelForgeParams(**data)
    except Exception:  # noqa: BLE001 - pricing only reads attributes
        return SimpleNamespace(**params)


def _funded_pipeline_params(params: Any, job: Any) -> Any:
    """The pipeline params with any premium downgrade the charge applied."""
    stored = getattr(job, "params", None)
    if not isinstance(stored, dict) or not dataclasses.is_dataclass(params):
        return params
    changes = {
        k: stored[k]
        for k in _FUNDED_FIELDS
        if k in stored and hasattr(params, k) and getattr(params, k) != stored[k]
    }
    return dataclasses.replace(params, **changes) if changes else params


def _discard_unfunded_job(job: Any, deps: RunnerDeps) -> None:
    """Remove the job row an unfunded render created (it never ran)."""
    discard = getattr(deps.job_repo, "discard", None)
    try:
        if callable(discard):
            discard(job.id)
            return
        delete = getattr(deps.session, "delete", None)
        if callable(delete):
            delete(job)
            deps.session.flush()
    except Exception as exc:  # noqa: BLE001 - the job is left un-enqueued either way
        logger.error(f"could not discard unfunded job {job.id}: {exc}")


def _refund(job_id: str, deps: RunnerDeps) -> int:
    try:
        if deps.refund is not None:
            return int(deps.refund(job_id) or 0)
        from app.domains.reels.charge import refund_job_once
        from app.domains.reels.policy import JOB_REFUND_REASON

        return refund_job_once(job_id, JOB_REFUND_REASON)
    except Exception as exc:  # noqa: BLE001 - reconcile is best-effort
        logger.error(f"refund of unqueued job {job_id} failed: {exc}")
        return 0


def _default_pause(session: Any, channel_id: str, reason: str) -> bool:
    """Record ``paused_reason`` on a defined channel. True on a new pause.

    ``autorun`` stays as the owner set it: the next beat tick that can pay
    renders again and clears the pause, so a top-up resumes Autopilot with no
    extra click. An ad-hoc channel (no definition) has nothing to persist.
    """
    from app.domains.series import channels as channel_store

    row = channel_store.get_definition(session, channel_id)
    if row is None:
        return True
    params = dict(row.params or {})
    if params.get("paused_reason") == reason:
        return False
    params["paused_reason"] = reason
    params["paused_at"] = datetime.now(timezone.utc).isoformat()
    row.params = params  # replace-on-edit so the JSON change is detected
    session.flush()
    return True


def _default_resume(session: Any, channel_id: str) -> bool:
    from app.domains.series import channels as channel_store

    row = channel_store.get_definition(session, channel_id)
    if row is None:
        return False
    params = dict(row.params or {})
    if not params.get("paused_reason"):
        return False
    params.pop("paused_reason", None)
    params.pop("paused_at", None)
    row.params = params
    session.flush()
    return True


def _pause_for_credits(
    config: ChannelRunConfig, *, run_id: str, deps: RunnerDeps, result: RunResult
) -> None:
    """Persist the pause, then emit ``channel_paused`` once per pause."""
    result.paused_reason = PAUSE_REASON_CREDITS
    try:
        if deps.pause is not None:
            fresh = bool(deps.pause(config.channel_id, PAUSE_REASON_CREDITS))
        else:
            fresh = _default_pause(deps.session, config.channel_id, PAUSE_REASON_CREDITS)
        _maybe_commit(deps)
    except Exception as exc:  # noqa: BLE001 - still stop and still signal
        logger.error(f"channel {config.channel_id}: could not persist pause: {exc}")
        fresh = True
    logger.info(
        f"channel {config.channel_id} run {run_id}: paused (credits), "
        f"rendered={result.rendered}, unfunded={result.unfunded}"
    )
    if not fresh:
        return
    failures = channel_signals.emit(
        Event(
            type=CHANNEL_PAUSED,
            key=config.channel_id,
            payload={
                "user_id": config.user_id,
                "reason": PAUSE_REASON_CREDITS,
                "run_id": run_id,
                "rendered": result.rendered,
            },
            idempotency_key=f"{CHANNEL_PAUSED}:{config.channel_id}:{run_id}",
        )
    )
    for failure in failures:
        logger.error(f"channel_paused handler {failure.handler} failed: {failure.error}")


def _resume(config: ChannelRunConfig, deps: RunnerDeps) -> None:
    try:
        if deps.resume is not None:
            cleared = bool(deps.resume(config.channel_id))
        else:
            cleared = _default_resume(deps.session, config.channel_id)
        if cleared:
            _maybe_commit(deps)
    except Exception as exc:  # noqa: BLE001 - a stale pause flag is harmless
        logger.warning(f"channel {config.channel_id}: could not clear pause: {exc}")


def _render_one(
    spec: ClipSpec,
    *,
    config: ChannelRunConfig,
    run_id: str,
    publish_platform: str,
    contract: ContractSeam,
    deps: RunnerDeps,
    result: RunResult,
) -> bool:
    """Create + charge + commit the job, enqueue, then persist + commit the clip.

    Returns False (and renders nothing) when the render cannot be paid for; the
    unfunded job row is discarded. The debit commits with the job, before the
    enqueue, so a queued render is always paid; a failed enqueue is refunded.

    Mirrors ``reels/router.create_job`` ordering: persist the job first, only
    then enqueue. Crucially the job is COMMITTED before enqueue (so an
    already-queued task can never reference a rolled-back ``job_id``) and the
    clip's ``spec_hash`` is committed immediately after a successful enqueue, so
    a crash later in the run cannot roll back an already-rendered clip and cause
    a double-render next tick. An enqueue failure is reconciled (job marked
    failed) and the clip's ``spec_hash`` is NOT recorded so the spec can be
    retried next run.
    """
    # platforms=() so the Celery DAG skips stage_upload (publishing is separate).
    params = contract.build_params(
        spec.body,
        subject=config.subject,
        aspect=spec.aspect,
        voice_id=config.voice_id,
        platforms=(),
    )
    params_dict = _params_dict(params)

    job = deps.job_repo.create(
        user_id=config.user_id,
        kind="avatar_reel",
        params=params_dict,
        batch_id=run_id,
    )
    job_id = job.id
    if not _charge(config, job, deps):
        if not result.unfunded_needed:
            try:
                from app.domains.reels.policy import render_credits

                result.unfunded_needed = render_credits(params_dict)
            except Exception:  # noqa: BLE001 - the 402 falls back to the flat unit
                result.unfunded_needed = 0
        _discard_unfunded_job(job, deps)
        return False
    params = _funded_pipeline_params(params, job)
    # Durably persist the job (and its debit) BEFORE enqueue: a task queued
    # against an uncommitted job_id would fail on lookup if the run rolls back.
    _maybe_commit(deps)

    try:
        deps.start_pipeline(job_id, params)
    except Exception as exc:  # noqa: BLE001 - enqueue failure must not orphan a job
        logger.error(f"channel {config.channel_id}: enqueue failed for job {job_id}: {exc}")
        _reconcile_failed_enqueue(job_id, str(exc), deps)
        result.enqueue_failures += 1
        return True

    clip = deps.clip_repo.create(
        channel_id=config.channel_id,
        run_id=run_id,
        spec_hash=spec.spec_hash,
        job_id=job_id,
        account=spec.account,
        platform=publish_platform,
    )
    clip_id = getattr(clip, "id", "")
    # Commit the spec_hash right after a successful enqueue so it is a durable
    # per-clip dedupe key even if a later spec in this run crashes the pass.
    _maybe_commit(deps)
    result.rendered += 1
    result.job_ids.append(job_id)
    result.clip_ids.append(clip_id)
    return True


def _reconcile_failed_enqueue(job_id: str, error: str, deps: RunnerDeps) -> None:
    """Best-effort: mark the job failed and refund its debit exactly once.

    Never raises — a reconcile hiccup must not abort the rest of the run.
    """
    try:
        deps.job_repo.mark_failed(job_id, "enqueue", error)
        _maybe_commit(deps)  # persist the reconciled (failed) job state
    except Exception as exc:  # noqa: BLE001 - reconcile is best-effort
        logger.error(f"failed to reconcile enqueue failure for job {job_id}: {exc}")
    _refund(job_id, deps)


# --------------------------------------------------------------------------- #
# schedule_due — pace COMPLETE clips onto the publish calendar
# --------------------------------------------------------------------------- #
def _seed_recent_history(
    config: ChannelRunConfig, *, now: datetime, deps: RunnerDeps
) -> dict[tuple[str, str], list[datetime]]:
    """Pre-populate per-account recent-post times from TODAY's scheduled posts.

    Reads the (optional) ``clip_repo.scheduled_run_ats`` seam; without it the
    history starts empty (single-pass behavior). Seeding these makes the daily
    cap / min-gap span the 5-minute beat ticks instead of resetting each pass.
    """
    recent: dict[tuple[str, str], list[datetime]] = {}
    getter = getattr(deps.clip_repo, "scheduled_run_ats", None)
    if getter is None:
        return recent
    try:
        rows = getter(config.channel_id, now=now)
    except TypeError:
        rows = getter(config.channel_id)  # seam without the optional ``now`` kwarg
    fallback_platform = config.platforms[0] if config.platforms else ""
    for account, platform, run_at in rows or ():
        if run_at is None:
            continue
        policy_platform = _policy_platform(platform or fallback_platform)
        if not policy_platform:
            continue
        key = (account or "", policy_platform)
        # A naive timestamp (some DB backends drop tzinfo) is treated as UTC so
        # ``astimezone`` never silently reinterprets it in the local zone.
        when = run_at if run_at.tzinfo is not None else run_at.replace(tzinfo=timezone.utc)
        recent.setdefault(key, []).append(when.astimezone(timezone.utc))
    return recent


def _publish_failure_counts(
    config: ChannelRunConfig, *, deps: RunnerDeps
) -> dict[tuple[str, str], int]:
    """Trailing consecutive publish failures keyed by (account, policy-platform).

    Reads the (optional) ``clip_repo.consecutive_publish_failures`` seam and
    bridges its publish platform names to scheduling-policy names. Absent seam
    -> no backoff (all zeros), preserving single-pass behavior.
    """
    getter = getattr(deps.clip_repo, "consecutive_publish_failures", None)
    if getter is None:
        return {}
    out: dict[tuple[str, str], int] = {}
    for (account, platform), count in (getter(config.channel_id) or {}).items():
        out[(account or "", _policy_platform(platform))] = int(count)
    return out


def schedule_due(
    config: ChannelRunConfig,
    *,
    now: datetime,
    deps: RunnerDeps,
) -> ScheduleResult:
    """Queue every COMPLETE-but-unpublished clip to auto-publish, with pacing.

    For each pending clip whose owning job is COMPLETE: map its publish platform
    to the scheduling-policy name, ask ``scheduling_policy.decide`` for the next
    legal slot (honoring daily-cap + min-gap against that account's already-
    scheduled posts — seeded from THIS UTC day's prior-tick schedules, then
    accumulated across this pass — plus exponential backoff after trailing
    publish failures), then ``schedule_publish`` at the decided future time and
    ``mark_scheduled`` the clip.
    """
    now = now.astimezone(timezone.utc)
    result = ScheduleResult()

    clips = list(deps.clip_repo.list_pending_publish(config.channel_id))
    result.considered = len(clips)
    if not clips:
        return result

    # Per (account, policy-platform) accumulated post times so successive clips
    # for the same account honor min-gap / daily-cap and spread across the window.
    # Seeded from THIS UTC day's already-scheduled publishes so the cap/min-gap
    # hold ACROSS beat ticks, not just within one pass.
    recent = _seed_recent_history(config, now=now, deps=deps)
    # Trailing consecutive publish failures per account -> exponential backoff.
    failures = _publish_failure_counts(config, deps=deps)

    for clip in clips:
        platform = getattr(clip, "platform", "") or (
            config.platforms[0] if config.platforms else ""
        )
        if not platform:
            # No cross-post target configured for this clip — cannot schedule.
            continue
        account = getattr(clip, "account", "") or ""
        policy_platform = _policy_platform(platform)
        key = (account, policy_platform)
        history = recent.setdefault(key, [])

        candidate = now + _PUBLISH_LEAD
        decision = scheduling_policy.decide(
            policy_platform,
            candidate,
            now=now,
            recent_posts=list(history),
            consecutive_failures=failures.get(key, 0),
        )
        run_at = decision.run_at.astimezone(timezone.utc)
        if run_at <= now:
            run_at = now + _PUBLISH_LEAD

        row = deps.schedule_publish(
            deps.session,
            config.user_id,
            clip.job_id,
            [platform],
            run_at,
        )
        deps.clip_repo.mark_scheduled(clip.id, getattr(row, "id", ""))
        history.append(run_at)
        result.scheduled += 1
        result.clip_ids.append(clip.id)

    logger.info(
        f"channel {config.channel_id}: scheduled {result.scheduled}/"
        f"{result.considered} pending clips"
    )
    return result


__all__ = [
    "CHANNEL_PAUSED",
    "PAUSE_REASON_CREDITS",
    "channel_signals",
    "ChannelRunConfig",
    "RunnerDeps",
    "RunResult",
    "ScheduleResult",
    "ContractSeam",
    "run_channel",
    "schedule_due",
    "items_from_list",
    "items_from_csv",
    "items_from_reddit",
    "MINECRAFT_SLUG",
    "DEFAULT_MAX_WORDS",
]
