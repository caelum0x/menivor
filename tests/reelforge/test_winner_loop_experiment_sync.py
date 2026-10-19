"""Winner loop -> Experiment sync, and completion/rewatch rates from connectors.

Completion and rewatch rates are only ever written when a platform reported
them; an unreported metric stays ``None`` in the loop state and never
overwrites the stored experiment value with a fabricated 0.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.experiments import registration as reg
from app.domains.insights import platform_metrics as pm
from app.domains.insights import winner_loop_service as svc
from app.domains.insights.winner_loop_state import LOOP_KEY
from app.models.db import experiments, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import Job, User


class _Resp:
    def __init__(self, status: int, body: dict) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> dict:
        return self._body


class _YouTubeTransport:
    """Serves the Analytics summary report and the retention curve."""

    def __init__(self, curve_rows: list | None, curve_status: int = 200) -> None:
        self.curve_rows = curve_rows
        self.curve_status = curve_status
        self.calls: list[dict] = []

    def request(self, method, url, *, headers=None, params=None, json=None, data=None):
        self.calls.append(dict(params or {}))
        if (params or {}).get("dimensions") == "elapsedVideoTimeRatio":
            return _Resp(self.curve_status, {
                "columnHeaders": [{"name": "elapsedVideoTimeRatio"}, {"name": "audienceWatchRatio"}],
                "rows": self.curve_rows or [],
            })
        return _Resp(200, {
            "columnHeaders": [{"name": n} for n in
                              ("views", "averageViewPercentage", "likes", "comments", "shares")],
            "rows": [[1000, 62.5, 50, 10, 5]],
        })


class _TikTokTransport:
    def request(self, method, url, *, headers=None, params=None, json=None, data=None):
        return _Resp(200, {"data": {"videos": [
            {"id": "tt1", "view_count": 400, "like_count": 20, "comment_count": 2, "share_count": 1},
        ]}, "error": {"code": "ok"}})


_POSTED = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _variant(platform: str, external_id: str) -> dict:
    return {"job_id": "jobv1", "hook": "POV: hook", "format": {}, "duration_s": 30.0, "logged": None,
            "posts": [{"platform": platform, "external_id": external_id, "url": "", "posted_at": _POSTED}]}


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(pm, "_token_for", lambda user_id, platform: ("tok", "acct"))


# --------------------------------------------------------------------------- #
# Connector-reported completion
# --------------------------------------------------------------------------- #
def test_youtube_completion_is_the_last_point_of_the_retention_curve() -> None:
    transport = _YouTubeTransport([[0.0, 1.0], [0.5, 0.7], [1.0, 0.41]])
    inp, posts, source = svc._measure("u1", _variant("youtube", "yt1"), transport)

    assert source == "platform"
    assert inp.completion_rate == pytest.approx(0.41)
    assert inp.rewatch_rate is None  # no platform reports rewatch per post
    assert inp.avg_watch_frac == pytest.approx(0.625)
    assert posts[0]["completion_rate"] == pytest.approx(0.41)
    assert posts[0]["rewatch_rate"] is None


def test_looping_shorts_completion_is_capped_at_one() -> None:
    inp, _, _ = svc._measure("u1", _variant("youtube", "yt1"), _YouTubeTransport([[1.0, 1.8]]))
    assert inp.completion_rate == pytest.approx(1.0)


@pytest.mark.parametrize(("rows", "status"), [([], 200), (None, 403)])
def test_missing_retention_curve_leaves_completion_unknown(rows, status) -> None:
    inp, _, _ = svc._measure("u1", _variant("youtube", "yt1"), _YouTubeTransport(rows, status))
    assert inp.completion_rate is None
    assert inp.views == 1000  # the summary report still counts


def test_tiktok_reports_no_completion_or_rewatch() -> None:
    inp, _, _ = svc._measure("u1", _variant("tiktok", "tt1"), _TikTokTransport())
    assert inp.views == 400
    assert inp.completion_rate is None
    assert inp.rewatch_rate is None


def test_view_weighted_skips_posts_that_did_not_report() -> None:
    posts = [
        pm.PostMetrics("youtube", "a", True, views=300, completion_rate=0.5),
        pm.PostMetrics("tiktok", "b", True, views=10_000),
        pm.PostMetrics("instagram", "c", True, views=100, completion_rate=0.1),
    ]
    assert svc._view_weighted(posts, "completion_rate") == pytest.approx((0.5 * 300 + 0.1 * 100) / 400)
    assert svc._view_weighted(posts, "rewatch_rate") is None


# --------------------------------------------------------------------------- #
# Experiment sync
# --------------------------------------------------------------------------- #
@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Factory.begin() as s:
        s.add(User(id="u1", email="u1@x.com"))
    return Factory


@pytest.fixture()
def patched_session(factory, monkeypatch):
    @contextmanager
    def fake_get_session():
        with factory.begin() as s:
            yield s

    monkeypatch.setattr("app.models.db.base.get_session", fake_get_session)
    return factory


def _seed_run(factory, loop_variants: list[dict[str, Any]], batch_id: str = "batchsync01") -> None:
    with factory.begin() as s:
        for jid in ("jobsyn1", "jobsyn2"):
            s.add(Job(id=jid, user_id="u1", kind="avatar_reel", params={}, stages={}, batch_id=batch_id))
        s.flush()
        reg.register_run(s, user_id="u1", variants=[
            reg.RunVariant(job_id="jobsyn1", hook_style="pov"),
            reg.RunVariant(job_id="jobsyn2", hook_style="question"),
        ])
        anchor = s.get(Job, "jobsyn1")
        anchor.stages = {LOOP_KEY: {"status": "measuring", "mode": "manual", "variants": loop_variants}}


def _variants_by_job(factory) -> dict[str, Any]:
    from app.domains.publishing.experiment_repo import ExperimentRepository

    with factory() as s:
        repo = ExperimentRepository(s)
        exp = repo.get_by_key(reg.experiment_key_for("batchsync01"))
        return {reg.job_id_of_hook_ref(v.hook_ref): v for v in repo.variants(exp.id)}


def test_sync_experiment_writes_reported_rates_and_keeps_unreported(patched_session) -> None:
    _seed_run(patched_session, [
        {"job_id": "jobsyn1", "views": 900, "avg_watch_frac": 0.8, "engagement_rate": 0.1,
         "completion_rate": 0.55, "rewatch_rate": None},
        {"job_id": "jobsyn2", "views": 700, "avg_watch_frac": None, "engagement_rate": 0.02,
         "completion_rate": None, "rewatch_rate": None},
    ])
    from app.domains.publishing.experiment_repo import ExperimentRepository

    with patched_session.begin() as s:  # a stored value from an earlier ingest
        repo = ExperimentRepository(s)
        exp = repo.get_by_key(reg.experiment_key_for("batchsync01"))
        v2 = next(v for v in repo.variants(exp.id) if v.hook_ref.endswith("jobsyn2"))
        repo.ingest_metrics(experiment_key=exp.experiment_key, variant_id=v2.id, views=10,
                            completion_rate=0.3, avg_watch_frac=0.25, rewatch_rate=0.05)

    assert svc.sync_experiment("u1", "batchsync01") is True

    by_job = _variants_by_job(patched_session)
    assert by_job["jobsyn1"].views == 900
    assert by_job["jobsyn1"].completion_rate == pytest.approx(0.55)
    assert by_job["jobsyn1"].avg_watch_frac == pytest.approx(0.8)
    assert by_job["jobsyn2"].views == 700
    # Unreported metrics keep the stored snapshot rather than becoming 0.
    assert by_job["jobsyn2"].completion_rate == pytest.approx(0.3)
    assert by_job["jobsyn2"].avg_watch_frac == pytest.approx(0.25)
    assert by_job["jobsyn2"].rewatch_rate == pytest.approx(0.05)


def test_sync_experiment_skips_batches_that_are_not_runs(patched_session) -> None:
    with patched_session.begin() as s:
        s.add(Job(id="jobplain", user_id="u1", kind="avatar_reel", params={}, stages={}, batch_id="plainbatch"))
    assert svc.sync_experiment("u1", "plainbatch") is False
    assert svc.sync_experiment("someone-else", "batchsync01") is False


def test_advance_syncs_the_experiment_when_the_loop_has_measurements(monkeypatch) -> None:
    measured_state = {"status": "measuring", "mode": "manual", "variants": [{"job_id": "j1"}]}
    monkeypatch.setattr(svc, "_phase_one", lambda *a, **k: svc._Snapshot(state=measured_state))
    synced: list[tuple[str, str]] = []
    monkeypatch.setattr(svc, "sync_experiment", lambda u, b: synced.append((u, b)) or True)

    assert svc.advance("u1", "b1") == measured_state
    assert synced == [("u1", "b1")]

    monkeypatch.setattr(svc, "_phase_one", lambda *a, **k: svc._Snapshot(state={"status": "live"}))
    svc.advance("u1", "b2")
    assert synced == [("u1", "b1")]  # nothing measured yet: no sync
