"""Trend-pull delegate service — scrape → score via the EXISTING scorer.

Additive to the trends domain: this is the service the ``trends_pull`` Celery task
calls (mirroring how ``broll.service.run_broll_generation`` is the delegate for
``broll_gen``). It NEVER touches ``trends/scoring.py`` or the persistence logic in
``trends/repository.py`` — it only wires the new providers into them:

    Job(kind='trends_pull')
        -> consent + allowlist gate (providers.consent, MANDATORY ToS)
        -> provider.pull_hashtag_posts / pull_sound_posts / pull_trending
        -> hashtag_analysis.bucket_daily_counts  (raw posts -> daily counts)
        -> TrendSignal(trend_id, kind, counts)
        -> TrendRepository.record(...)           (scores + persists, UNCHANGED)

It also surfaces the dominant native sound id + the co-occurring hashtags for the
compose/captions/publishing handoff (edit muted, attach the exact native audio on
upload). Spend follows the B-roll shape: the credit debit happens at ENQUEUE (in
the router), and :func:`refund_trends_pull` idempotently refunds on failure.
"""

from __future__ import annotations

import asyncio
from datetime import timezone
from typing import Any

from loguru import logger

_TREND_PULL_KIND: str = "trends_pull"
_DEFAULT_MAX_POSTS: int = 50


class TrendPullError(RuntimeError):
    """Raised for a hard trend-pull failure (gate refusal, provider disabled)."""


class TrendsPullService:
    """Run one ``trends_pull`` job end to end (gate → pull → score → persist)."""

    def run_pull(self, job_id: str) -> dict[str, Any]:
        """Execute the ``trends_pull`` job ``job_id``.

        Raises :class:`TrendPullError` on any hard failure (consent/allowlist
        refusal, provider disabled) so the Celery task's ``on_failure`` marks the
        job failed and refunds the debit. Returns a summary dict on success.
        """
        job_id = (job_id or "").strip()
        if not job_id:
            raise TrendPullError("trends_pull: run called without a job_id")

        ctx = self._load_job_context(job_id)
        if ctx is None:
            raise TrendPullError(f"trends_pull: job {job_id!r} not found")
        user_id, params = ctx

        target = str(params.get("target") or "").strip()
        kind = str(params.get("kind") or "hashtag").strip().lower()
        max_posts = int(params.get("max_posts") or _DEFAULT_MAX_POSTS)
        if not target:
            raise TrendPullError("trends_pull: job has no target")

        self._gate_or_raise(user_id, target)
        self._set_progress(job_id, 10)

        from app.domains.trends.providers import get_trend_pull_provider

        provider = get_trend_pull_provider()
        if not provider.is_enabled():
            raise TrendPullError("trends_pull: provider is not configured/enabled")

        self._set_progress(job_id, 30)
        posts = self._pull(provider, kind, target, max_posts)

        from app.domains.trends.providers import hashtag_analysis as ha

        counts = ha.bucket_daily_counts(posts, tz=timezone.utc)
        cooccurring = ha.cooccurring_hashtags(posts).most_common(20)
        sound_id = ha.native_sound_id(posts)

        self._set_progress(job_id, 80)
        observation = self._record(
            job_id=job_id,
            trend_id=target,
            kind=kind if kind in ("hashtag", "sound") else "format",
            counts=counts,
            label=target,
        )

        summary = {
            "job_id": job_id,
            "trend_id": target,
            "kind": kind,
            "post_count": len(posts),
            "counts": list(counts),
            "native_sound_id": sound_id,
            "cooccurring_hashtags": [{"tag": t, "count": c} for t, c in cooccurring],
            "observation_id": getattr(observation, "id", None),
            "recommend": bool(getattr(observation, "recommend", False)),
        }
        logger.success(
            f"trends_pull: completed job={job_id!r} target={target!r} "
            f"({len(posts)} posts -> {len(counts)}-day series)"
        )
        return summary

    # ------------------------------------------------------------------ #
    # Steps
    # ------------------------------------------------------------------ #
    def _gate_or_raise(self, user_id: str, target: str) -> None:
        """Enforce the MANDATORY ToS gate (consent + allowlist) before pulling."""
        from app.domains.trends.providers import consent

        with _session() as session:
            if not consent.is_pull_allowed(session, user_id, target):
                raise TrendPullError(
                    f"trends_pull: pull not allowed for target {target!r} "
                    "(consent not granted or target off-allowlist)"
                )

    def _pull(self, provider: Any, kind: str, target: str, max_posts: int) -> list[dict]:
        """Dispatch to the right provider pull method by ``kind`` (async → sync)."""
        async def _run() -> list[dict]:
            if kind == "sound":
                return await provider.pull_sound_posts(target, max_posts=max_posts)
            if kind in ("trending", "format", "fyp"):
                return await provider.pull_trending(max_posts=max_posts)
            return await provider.pull_hashtag_posts(target, max_posts=max_posts)

        try:
            return asyncio.run(_run()) or []
        except Exception as exc:  # noqa: BLE001 - a scrape failure yields no posts
            logger.warning(f"trends_pull: provider pull failed for {target!r}: {exc}")
            return []

    def _record(self, *, job_id: str, trend_id: str, kind: str, counts, label: str):
        """Score + persist via the UNCHANGED repository/scorer."""
        from app.domains.trends.repository import TrendRepository
        from app.domains.trends.scoring import TrendSignal

        with _session() as session:
            repo = TrendRepository(session)
            return repo.record(
                TrendSignal(trend_id=trend_id, kind=kind, counts=tuple(counts), label=label)
            )

    # ------------------------------------------------------------------ #
    # Job helpers (mirror broll.service)
    # ------------------------------------------------------------------ #
    def _load_job_context(self, job_id: str) -> tuple[str, dict] | None:
        try:
            from app.models.db.repositories import JobRepository

            with _session() as session:
                job = JobRepository(session).get(job_id)
                if job is None:
                    return None
                return job.user_id, dict(job.params or {})
        except Exception as exc:  # noqa: BLE001
            logger.error(f"trends_pull: could not load job {job_id!r}: {exc}")
            return None

    def _set_progress(self, job_id: str, progress: int) -> None:
        try:
            from app.models.db.repositories import JobRepository

            with _session() as session:
                JobRepository(session).set_progress(job_id, progress)
        except Exception as exc:  # noqa: BLE001 - progress is cosmetic
            logger.debug(f"trends_pull: progress update failed for {job_id!r}: {exc}")


def refund_trends_pull(job_id: str) -> None:
    """Idempotently refund a failed pull's credit debit (best-effort).

    Copies the shape of ``broll.service.refund_broll_generation``: reads
    ``credits_cost`` / ``workspace_id`` from the job params and grants the credits
    back to the pool they were debited from, setting a ``refunded`` flag so a
    duplicate failure hook cannot double-refund. Never raises.
    """
    job_id = (job_id or "").strip()
    if not job_id:
        return
    try:
        from app.models.db.repositories import CreditRepository, JobRepository

        with _session() as session:
            job_repo = JobRepository(session)
            job = getattr(job_repo, "_locked_job", job_repo.get)(job_id)
            if job is None:
                return
            params = dict(job.params or {})
            if params.get("refunded"):
                return
            cost = int(params.get("credits_cost") or 0)
            if cost <= 0:
                return
            workspace_id = params.get("workspace_id") or None
            user_id = job.user_id

            credits = CreditRepository(session)
            if workspace_id:
                credits.workspace_grant(workspace_id, cost, "trends_pull_refund", user_id)
            else:
                credits.grant(user_id, cost, "trends_pull_refund")

            job.params = {**params, "refunded": True}
            session.flush()
        logger.info(f"trends_pull: refunded {cost} credit(s) for failed job={job_id!r}")
    except Exception as exc:  # noqa: BLE001 - refund is best-effort
        logger.error(f"trends_pull: refund failed for job={job_id!r}: {exc}")


def run_trends_pull(job_id: str) -> dict[str, Any]:
    """Module-level entry point the Celery task delegates to."""
    return TrendsPullService().run_pull(job_id)


#: Operator-configured targets the scheduled feed refresh pulls, e.g.
#: ``trending,sound:7234567890,booktok`` (a ``sound:`` prefix pulls a sound;
#: ``trending`` pulls the For-You feed; anything else is a hashtag). Every target
#: must ALSO be on ``TREND_PULL_ALLOWLIST`` — setting both is the operator's
#: explicit ToS decision for the shared feed (no per-user consent involved, and
#: no user is charged).
AUTOPULL_TARGETS_ENV = "TREND_AUTOPULL_TARGETS"


def _autopull_targets() -> list[tuple[str, str]]:
    import os

    targets: list[tuple[str, str]] = []
    for part in (os.getenv(AUTOPULL_TARGETS_ENV) or "").split(","):
        raw = part.strip()
        if not raw:
            continue
        if raw.lower().startswith("sound:"):
            targets.append(("sound", raw[6:].strip()))
        elif raw.lower() in ("trending", "fyp"):
            targets.append(("trending", "trending"))
        else:
            targets.append(("hashtag", raw.lstrip("#")))
    return [(k, t) for k, t in targets if t]


def autopull_trends(max_posts: int = _DEFAULT_MAX_POSTS) -> dict[str, int]:
    """Refresh the shared recommended feed from the operator's configured targets.

    Beat entrypoint body. A no-op when no targets are configured or the pull
    provider is disabled. Each target is allowlist-checked, pulled, scored and
    recorded exactly like a user pull. Never raises.
    """
    summary = {"targets": 0, "recorded": 0, "skipped": 0}
    targets = _autopull_targets()
    if not targets:
        return summary
    try:
        from app.domains.trends.providers import consent, get_trend_pull_provider
        from app.domains.trends.providers import hashtag_analysis as ha

        provider = get_trend_pull_provider()
        if not provider.is_enabled():
            logger.info("trends autopull: provider disabled; skipping")
            return summary
    except Exception as exc:  # noqa: BLE001 - provider layer optional
        logger.warning(f"trends autopull unavailable: {exc}")
        return summary

    service = TrendsPullService()
    for kind, target in targets:
        summary["targets"] += 1
        allow_key = consent.TRENDING_TARGET if kind == "trending" else target
        if not consent.is_target_allowed(allow_key):
            summary["skipped"] += 1
            logger.warning(f"trends autopull: {target!r} is not on the allowlist; skipped")
            continue
        try:
            posts = service._pull(provider, kind, target, max_posts)  # noqa: SLF001
            counts = ha.bucket_daily_counts(posts, tz=timezone.utc)
            if not posts:
                summary["skipped"] += 1
                continue
            service._record(  # noqa: SLF001 - same scorer/repository as user pulls
                job_id="",
                trend_id=target,
                kind=kind if kind in ("hashtag", "sound") else "format",
                counts=counts,
                label=target,
            )
            summary["recorded"] += 1
        except Exception as exc:  # noqa: BLE001 - one target must not stop the rest
            summary["skipped"] += 1
            logger.warning(f"trends autopull failed for {target!r}: {exc}")
    logger.info(f"trends autopull: {summary}")
    return summary


def _session():
    from app.models.db.base import get_session

    return get_session()


__all__ = [
    "TrendsPullService",
    "TrendPullError",
    "autopull_trends",
    "run_trends_pull",
    "refund_trends_pull",
]
