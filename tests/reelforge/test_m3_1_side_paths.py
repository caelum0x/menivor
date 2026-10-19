"""M3.1 verifier: approvals and remakes price a reel like a create (MD8)."""

from __future__ import annotations

from types import SimpleNamespace

from app.domains.approvals import reel_jobs


def _params(seconds: int, layout: str = "captions_only") -> SimpleNamespace:
    return SimpleNamespace(target_duration_s=seconds, layout=layout, video_script="")


def test_short_reel_costs_the_flat_credit():
    assert reel_jobs.job_credits(_params(30)) == reel_jobs.cost_per_job()


def test_long_form_reel_costs_one_credit_per_started_minute():
    assert reel_jobs.job_credits(_params(150)) == 3 * reel_jobs.cost_per_job()


def test_presenter_reel_costs_the_presenter_floor(monkeypatch):
    monkeypatch.setenv("MENIVOR_PRESENTER_CREDITS", "5")
    assert reel_jobs.job_credits(_params(30, layout="split")) >= 5
