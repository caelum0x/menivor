"""Ad Studio "Publish and test": finished ads -> scheduled posts -> 48h winner loop.

One click turns 2-6 finished ads into a live test on the creator's own
TikTok / Instagram / YouTube accounts, reusing the existing machinery instead
of a parallel one:

1. **Carrier jobs.** The native publisher, the scheduler and the remake-winner
   loop all work on ``Job`` rows. Each tested ad gets one completed
   ``Job(kind="ad_variant")`` whose ``result_key`` is the ad's MP4 (the reel's
   MP4 for UGC avatar ads) and whose params carry the ad's own post caption
   (``social_metadata``), so what is posted is exactly the Ad Studio copy. All
   carriers of one test share a fresh ``batch_id``. No credits are debited.
2. **Experiment.** A 1-body/N-hooks ``Experiment`` keyed ``run:<batch_id>`` (one
   variant per ad, ``<angle kind>:<job id>``) so the loop tick mirrors the
   measured numbers onto it and re-evaluates the verdict.
3. **Winner loop.** The loop is configured on the batch in ``manual`` mode with
   the chosen platforms and a **zero credit spend cap**: it spaces the posts
   under each platform's daily cap, waits 48h after the last one went live,
   pulls real platform metrics, ranks, and parks at ``winner_ready``. Remaking
   an ad winner is Ad Studio's job (free local renders from the winning hook),
   so the reel-pipeline remake can never spend credits on an ad batch.

A *manual* test (publishing closed, e.g. the private-beta pilot, or no
connected account) runs the same loop with no platforms: the creator posts the
downloads and logs each ad's numbers, and the loop ranks those.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.domains.adstudio import angles as angle_lib
from app.domains.adstudio.publish_gate import launch_state, pro_state
from app.domains.adstudio.repository import AdStudioRepository
from app.domains.adstudio.service import MAX_ACTIVE_RENDERS_PER_USER, AdStudioError, sync_jobs
from app.domains.adstudio.views import post_caption

CARRIER_KIND = "ad_variant"
MIN_TEST_ADS = 2
MAX_TEST_ADS = 6
REMAKE_COUNT = 3
TEST_SPEC_KEY = "publish_test"
_TITLE_MAX = 100
_CAPTION_MAX = 2200


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #
def playable_key(variant: Any, jobs: dict[str, Any]) -> str:
    """The R2 key of the finished MP4 that would be posted ('' when none)."""
    if variant.status != "done":
        return ""
    if variant.format == "ugc_avatar":
        job = jobs.get(variant.job_id) if variant.job_id else None
        return str(getattr(job, "result_key", "") or "") if job is not None else ""
    return str(variant.output_key or "")


def test_of(variant: Any) -> dict[str, Any]:
    raw = (variant.spec or {}).get(TEST_SPEC_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def eligible_variants(variants: list[Any], jobs: dict[str, Any]) -> list[Any]:
    """Finished ads with a playable MP4 that are not already in a test."""
    return [v for v in variants if playable_key(v, jobs) and not test_of(v)]


def _pick(variants: list[Any], jobs: dict[str, Any], variant_ids: list[str]) -> list[Any]:
    by_id = {v.id: v for v in variants}
    if variant_ids:
        unknown = [i for i in variant_ids if i not in by_id]
        if unknown:
            raise AdStudioError(404, "one or more ads were not found in this project")
        chosen = [by_id[i] for i in dict.fromkeys(variant_ids)]
        if any(test_of(v) for v in chosen):
            raise AdStudioError(409, "one or more of these ads is already in a test")
        if any(not playable_key(v, jobs) for v in chosen):
            raise AdStudioError(409, "only finished ads can be published; wait for the renders to finish")
    else:
        chosen = eligible_variants(variants, jobs)
    if len(chosen) < MIN_TEST_ADS:
        raise AdStudioError(422, f"a test needs at least {MIN_TEST_ADS} finished ads that are not already in a test")
    if len(chosen) > MAX_TEST_ADS:
        raise AdStudioError(422, f"pick at most {MAX_TEST_ADS} ads per test so each gets a fair share of reach")
    return chosen


# --------------------------------------------------------------------------- #
# Gates (publish mode only)
# --------------------------------------------------------------------------- #
def _normalize(platforms: list[str]) -> list[str]:
    from app.domains.publishing.loop_autopublish import normalize_loop_platforms

    try:
        return normalize_loop_platforms(platforms)
    except ValueError as exc:
        raise AdStudioError(422, str(exc)) from exc


def check_publish_gates(user_id: str, platforms: list[str]) -> None:
    """Launch flag -> Pro -> every chosen account connected, else a clean error."""
    if not platforms:
        raise AdStudioError(422, "pick at least one platform to publish to")
    launch = launch_state()
    if not launch["enabled"]:
        raise AdStudioError(403, launch["reason"])
    pro = pro_state(user_id)
    if pro["status"] == "required":
        raise AdStudioError(402, pro["reason"])
    if pro["status"] != "active":
        raise AdStudioError(503, pro["reason"])
    try:
        from app.domains.publishing.native_service import NativePublishError, require_native_connections
    except Exception as exc:  # noqa: BLE001 - publishing layer missing
        raise AdStudioError(503, "publishing connections are unavailable right now") from exc
    try:
        require_native_connections(user_id, platforms)
    except NativePublishError as exc:
        raise AdStudioError(exc.status_code, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - token refresh / provider failure
        logger.warning(f"adstudio publish test: connection check failed: {type(exc).__name__}")
        raise AdStudioError(409, "a connected account needs to be reconnected; open Connections and try again") from exc


# --------------------------------------------------------------------------- #
# Start
# --------------------------------------------------------------------------- #
def _carrier(project: Any, variant: Any, *, user_id: str, batch_id: str, key: str, jobs: dict[str, Any]) -> Any:
    from app.models.const import TASK_STATE_COMPLETE
    from app.models.db.models import Job

    angle = dict((variant.spec or {}).get("angle") or {})
    hook = str(angle.get("hook") or "").strip()
    reel = jobs.get(variant.job_id) if variant.job_id else None
    poster = str(getattr(reel, "poster_key", "") or "") if reel is not None else ""
    return Job(
        id=uuid.uuid4().hex,
        user_id=user_id,
        batch_id=batch_id,
        kind=CARRIER_KIND,
        state=TASK_STATE_COMPLETE,
        progress=100,
        stages={},
        params={
            "video_subject": project.title,
            "video_script": variant.script,
            "language": project.language,
            "aspect": variant.aspect,
            "target_duration_s": round((variant.duration_ms or 0) / 1000, 2),
            "source": "adstudio",
            "adstudio": {
                "project_id": project.id,
                "variant_id": variant.id,
                "angle_id": variant.angle_id,
                "format": variant.format,
            },
            "social_metadata": {
                "title": (hook or project.title)[:_TITLE_MAX],
                "caption": post_caption(project, angle)[:_CAPTION_MAX],
                "hashtags": [],
            },
        },
        result_key=key,
        poster_key=poster or variant.poster_key or "",
        script=variant.script,
        title=f"Ad: {project.title}"[:200],
    )


def _create_test(session: Any, *, user_id: str, project: Any, variant_ids: list[str], mode: str, platforms: list[str]) -> str:
    from app.domains.experiments.registration import experiment_key_for, hook_ref_for
    from app.domains.publishing.experiment_repo import ExperimentRepository

    repo = AdStudioRepository(session)
    variants = repo.variants(project.id)
    jobs = sync_jobs(session, variants)
    chosen = _pick(variants, jobs, variant_ids)
    # Re-read each chosen ad under a row lock so a double click cannot put the
    # same ad into two tests.
    locked = [repo.lock_variant(v.id) for v in chosen]
    if any(v is None or test_of(v) for v in locked):
        raise AdStudioError(409, "one or more of these ads is already in a test")
    batch_id = uuid.uuid4().hex
    started = _now().isoformat()
    hook_refs: list[str] = []
    for variant in locked:
        carrier = _carrier(project, variant, user_id=user_id, batch_id=batch_id,
                           key=playable_key(variant, jobs), jobs=jobs)
        session.add(carrier)
        kind = str(((variant.spec or {}).get("angle") or {}).get("kind") or "ad")
        hook_refs.append(hook_ref_for(kind, carrier.id))
        variant.spec = {
            **dict(variant.spec or {}),
            TEST_SPEC_KEY: {"batch_id": batch_id, "job_id": carrier.id, "mode": mode,
                            "platforms": list(platforms), "started_at": started},
        }
    session.flush()
    ExperimentRepository(session).create(
        user_id=user_id, experiment_key=experiment_key_for(batch_id),
        hook_refs=hook_refs, body_ref=f"adstudio:{project.id}"[:120],
    )
    return batch_id


def start_test(
    user_id: str, project_id: str, *, variant_ids: list[str], mode: str, platforms: list[str],
) -> dict[str, Any]:
    """Create the test and open its loop. Returns ``{batch_id, loop_note}``."""
    from app.models.db.base import get_session

    if mode not in ("publish", "manual"):
        raise AdStudioError(422, "mode must be 'publish' or 'manual'")
    chosen_platforms = _normalize(platforms) if mode == "publish" else []
    if mode == "publish":
        check_publish_gates(user_id, chosen_platforms)

    with get_session() as session:
        project = AdStudioRepository(session).get_owned_project(user_id, project_id)
        if project is None:
            raise AdStudioError(404, "project not found")
        batch_id = _create_test(session, user_id=user_id, project=project, variant_ids=variant_ids,
                                mode=mode, platforms=chosen_platforms)
    return {"batch_id": batch_id, "loop_note": _open_loop(user_id, batch_id, chosen_platforms)}


def _open_loop(user_id: str, batch_id: str, platforms: list[str]) -> str:
    """Configure the loop and advance it once so posts are queued right away."""
    from app.domains.insights.winner_loop_service import advance, configure

    try:
        configure(user_id, batch_id, mode="manual", platforms=platforms,
                  spend_cap_credits=0, check_after_hours=None, min_views=None)
    except Exception as exc:  # noqa: BLE001 - the test stands; the page reports it
        logger.error(f"adstudio test {batch_id}: loop configure failed: {exc}")
        return "The test was saved but its results loop could not start. Use Check now to retry."
    try:
        advance(user_id, batch_id, allow_auto_remake=False)
    except Exception as exc:  # noqa: BLE001 - the beat tick retries within minutes
        logger.warning(f"adstudio test {batch_id}: first loop advance failed: {exc}")
        return "Posts will be queued on the next loop check (within a few minutes)."
    return ""


# --------------------------------------------------------------------------- #
# Ownership of a test batch
# --------------------------------------------------------------------------- #
def test_carriers(session: Any, user_id: str, project_id: str, batch_id: str) -> list[Any]:
    """The test's carrier jobs, only when every one belongs to this project."""
    from app.models.db.repositories import JobRepository

    carriers = JobRepository(session).list_by_batch(batch_id, user_id)
    if not carriers or any(
        c.kind != CARRIER_KIND or ((c.params or {}).get("adstudio") or {}).get("project_id") != project_id
        for c in carriers
    ):
        raise AdStudioError(404, "test not found")
    return carriers


def _owned_test(user_id: str, project_id: str, batch_id: str) -> None:
    from app.models.db.base import get_session

    with get_session() as session:
        test_carriers(session, user_id, project_id, batch_id)


def check_now(user_id: str, project_id: str, batch_id: str) -> None:
    """Advance the loop now; reads the numbers early when posts are live."""
    from app.domains.insights.winner_loop_service import LoopNotFound, advance

    _owned_test(user_id, project_id, batch_id)
    try:
        advance(user_id, batch_id, force_check=True, allow_auto_remake=False)
    except LoopNotFound as exc:
        raise AdStudioError(404, "test not found") from exc


def stop_test(user_id: str, project_id: str, batch_id: str) -> int:
    """Turn the loop off and cancel posts that have not gone out yet."""
    from app.domains.insights.winner_loop_service import configure, find_anchor
    from app.domains.insights.winner_loop_state import read_state
    from app.models.db.base import get_session
    from app.models.db.models import ScheduledPublish
    from app.models.db.repositories import ScheduledPublishRepository

    with get_session() as session:
        carriers = test_carriers(session, user_id, project_id, batch_id)
        anchor = find_anchor(session, batch_id, user_id)
        platforms = list(read_state(anchor).get("platforms") or []) if anchor is not None else []
        rows = (
            session.query(ScheduledPublish)
            .filter(ScheduledPublish.user_id == user_id,
                    ScheduledPublish.job_id.in_([c.id for c in carriers]),
                    ScheduledPublish.status == "pending")
            .all()
        )
        repo = ScheduledPublishRepository(session)
        canceled = sum(1 for row in rows if repo.cancel(row.id, user_id))
    configure(user_id, batch_id, mode="off", platforms=platforms,
              spend_cap_credits=0, check_after_hours=None, min_views=None)
    return canceled


def retire_project_tests(session: Any, user_id: str, variants: list[Any]) -> None:
    """Before a project is deleted: cancel its unposted test posts and stop its loops."""
    from app.domains.insights.winner_loop_service import find_anchor
    from app.domains.insights.winner_loop_state import read_state, write_state
    from app.models.db.models import ScheduledPublish
    from app.models.db.repositories import ScheduledPublishRepository

    tests = [test_of(v) for v in variants]
    job_ids = [str(t.get("job_id")) for t in tests if t.get("job_id")]
    if not job_ids:
        return
    repo = ScheduledPublishRepository(session)
    rows = (
        session.query(ScheduledPublish)
        .filter(ScheduledPublish.user_id == user_id, ScheduledPublish.job_id.in_(job_ids),
                ScheduledPublish.status == "pending")
        .all()
    )
    for row in rows:
        repo.cancel(row.id, user_id)
    for batch_id in {str(t.get("batch_id")) for t in tests if t.get("batch_id")}:
        anchor = find_anchor(session, batch_id, user_id, lock=True)
        state = read_state(anchor) if anchor is not None else {}
        if state:
            write_state(anchor, {**state, "mode": "off", "note": "The Ad Studio project was deleted."})


# --------------------------------------------------------------------------- #
# Remake the winner (free local renders from the winning hook)
# --------------------------------------------------------------------------- #
def _winner_context(session: Any, user_id: str, project: Any, batch_id: str, accept_low_confidence: bool):
    from app.domains.insights.winner_loop_service import find_anchor
    from app.domains.insights.winner_loop_state import read_state

    carriers = test_carriers(session, user_id, project.id, batch_id)
    anchor = find_anchor(session, batch_id, user_id, lock=True)
    state = read_state(anchor) if anchor is not None else {}
    replay = state.get("adstudio_remake")
    if isinstance(replay, dict) and replay.get("variant_ids"):
        return anchor, state, None, replay
    winner_job = str(state.get("winner_job_id") or "")
    if state.get("status") != "winner_ready" or not winner_job:
        raise AdStudioError(409, "there is no winner yet; the test needs live posts with numbers first")
    if not state.get("conclusive") and not accept_low_confidence:
        raise AdStudioError(409, "the winner is low-confidence; confirm to remake it anyway")
    carrier = next((c for c in carriers if c.id == winner_job), None)
    variant_id = ((carrier.params or {}).get("adstudio") or {}).get("variant_id") if carrier is not None else None
    winner = AdStudioRepository(session).get_owned_variant(user_id, project.id, str(variant_id or ""))
    if winner is None:
        raise AdStudioError(404, "the winning ad was deleted; it cannot be remade")
    return anchor, state, winner, None


def remake_winner(user_id: str, project_id: str, batch_id: str, *, accept_low_confidence: bool) -> dict[str, Any]:
    """Render up to 3 new ads that keep the winner's format and angle but rewrite its hook.

    Returns ``{variant_ids, hooks, replayed}``. The caller dispatches the renders.
    Idempotent: a second call returns the first remake.
    """
    from app.domains.insights.remake import hook_variants
    from app.domains.insights.winner_loop_state import iso, write_state
    from app.models.db.base import get_session

    with get_session() as session:
        project = AdStudioRepository(session).get_owned_project(user_id, project_id)
        if project is None:
            raise AdStudioError(404, "project not found")
        _, _, winner, replay = _winner_context(session, user_id, project, batch_id, accept_low_confidence)
        if replay is not None:
            return {"variant_ids": list(replay["variant_ids"]), "hooks": list(replay.get("hooks") or []), "replayed": True}
        angle = dict((winner.spec or {}).get("angle") or {})
        hook = str(angle.get("hook") or "").strip()
        topic, language = project.title, project.language

    # LLM (or template) rewrites happen outside any transaction/lock.
    hooks = hook_variants(hook, topic=topic, language=language, count=REMAKE_COUNT) if hook else []
    if not hooks:
        raise AdStudioError(422, "could not write new hooks for this ad; non-English rewrites need an AI provider configured")

    with get_session() as session:
        project = AdStudioRepository(session).get_owned_project(user_id, project_id)
        if project is None:
            raise AdStudioError(404, "project not found")
        anchor, state, winner, replay = _winner_context(session, user_id, project, batch_id, accept_low_confidence)
        if replay is not None:  # a concurrent click won the race
            return {"variant_ids": list(replay["variant_ids"]), "hooks": list(replay.get("hooks") or []), "replayed": True}
        ids = _queue_remakes(session, user_id=user_id, project=project, winner=winner, hooks=hooks, batch_id=batch_id)
        write_state(anchor, {
            **state, "status": "remade", "note": "", "remade_by": "adstudio",
            "adstudio_remake": {"variant_ids": ids, "hooks": hooks, "winner_variant_id": winner.id, "at": iso(_now())},
        })
    return {"variant_ids": ids, "hooks": hooks, "replayed": False}


def _queue_remakes(session: Any, *, user_id: str, project: Any, winner: Any, hooks: list[str], batch_id: str) -> list[str]:
    from app.domains.adstudio.models import AdVariant

    active = (
        session.query(AdVariant)
        .filter(AdVariant.user_id == user_id, AdVariant.status.in_(("queued", "rendering")))
        .count()
    )
    if active + len(hooks) > MAX_ACTIVE_RENDERS_PER_USER:
        raise AdStudioError(429, "too many ads are rendering; wait for the current batch to finish")
    spec = dict(winner.spec or {})
    angle = dict(spec.get("angle") or {})
    fields = {f: str(angle.get(f) or "") for f in angle_lib.FIELDS}
    repo = AdStudioRepository(session)
    ids: list[str] = []
    for hook in hooks:
        new_fields = {**fields, "hook": hook[: angle_lib.FIELD_MAX]}
        new_angle = {**angle, **new_fields, "script": angle_lib.build_script(new_fields, project.product or {}, project.language),
                     "source": "remake"}
        variant = repo.create_variant(
            project_id=project.id, user_id=user_id, angle_id=winner.angle_id, format=winner.format,
            aspect=winner.aspect, status="queued", script=new_angle["script"],
            spec={"angle": new_angle, "options": dict(spec.get("options") or {}),
                  "remake_of": {"batch_id": batch_id, "variant_id": winner.id, "hook": fields["hook"]}},
        )
        ids.append(variant.id)
    return ids


__all__ = [
    "CARRIER_KIND",
    "MAX_TEST_ADS",
    "MIN_TEST_ADS",
    "check_now",
    "check_publish_gates",
    "eligible_variants",
    "playable_key",
    "remake_winner",
    "retire_project_tests",
    "start_test",
    "stop_test",
    "test_carriers",
    "test_of",
]
