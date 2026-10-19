"""M3.1: one public pricing model (WP3.1, MD8).

* Ledger by style and length: 1 credit up to 60 s, 1 per started minute for
  long-form, 5 for a presenter reel (Pro and Agency only, monthly cap).
* Charge on keep (``MENIVOR_CHARGE_ON_KEEP``): variant 1 is debited at
  create, variants 2-3 only when kept; a keep debits exactly once.
"""

from __future__ import annotations

import pytest

from app.domains.reels import keep, policy, pricing
from app.models import const
from app.models.db.models import CreditLedger, Job
from app.models.db.repositories import CreditRepository, JobRepository
from tests.reelforge.test_premium_credits import (  # noqa: F401 - fixtures
    _HEADERS,
    _balances,
    _params,
    _pro,
    _user,
    api,
    db,
)

_FREE_VOICE = "en-US-AriaNeural-Female"


def _reel(seconds: int = 30, **extra) -> dict:
    return {
        "params": {
            "video_subject": "cats",
            "layout": "captions_only",
            "voice_name": _FREE_VOICE,
            "target_duration_s": seconds,
            **extra.pop("params", {}),
        },
        **extra,
    }


def _presenter(**extra) -> dict:
    return {"params": {"video_subject": "cats", "target_duration_s": 30}, **extra}


def _debits(factory, job_id: str) -> list[int]:
    with factory() as s:
        rows = s.query(CreditLedger).filter(CreditLedger.job_id == job_id).order_by(CreditLedger.id)
        return [int(r.delta) for r in rows]


def _complete(factory, job_id: str) -> None:
    with factory() as s:
        job = s.get(Job, job_id)
        job.state = const.TASK_STATE_COMPLETE
        job.progress = 100
        s.commit()


# --------------------------------------------------------------------------- #
# Credits by style and length (ledger)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("seconds", "credits"), [(15, 1), (60, 1), (90, 2), (180, 3)])
def test_create_debits_credits_by_length(db, api, seconds, credits):  # noqa: F811 - shared fixtures
    client, _pipeline = api
    uid = _user(db, credits=10)
    res = client.post("/api/v1/jobs", json=_reel(seconds), headers=_HEADERS)
    assert res.status_code == 200, res.text
    assert _debits(db, res.json()["data"]["job_id"]) == [-credits]
    assert _balances(db, uid)[0] == 10 - credits


def test_long_form_without_enough_credits_is_402_and_creates_nothing(db, api):  # noqa: F811 - shared fixtures
    client, pipeline = api
    uid = _user(db, credits=2)
    res = client.post("/api/v1/jobs", json=_reel(180), headers=_HEADERS)
    assert res.status_code == 402, res.text
    assert _balances(db, uid)[0] == 2 and pipeline.start_calls == []
    with db() as s:
        assert JobRepository(s).list_for_user(uid) == []


@pytest.mark.parametrize("plan", ["pro", "agency"])
def test_presenter_costs_five_credits_on_pro_and_agency(db, api, plan):  # noqa: F811 - shared fixtures
    client, _pipeline = api
    uid = _user(db, credits=10, ai=10_000)
    _pro(db, uid, plan)
    res = client.post("/api/v1/jobs", json=_presenter(), headers=_HEADERS)
    assert res.status_code == 200, res.text
    assert _debits(db, res.json()["data"]["job_id"]) == [-policy.DEFAULT_PRESENTER_CREDITS]


@pytest.mark.parametrize("plan", [None, "creator"])
def test_presenter_is_refused_below_pro(db, api, plan):  # noqa: F811 - shared fixtures
    client, pipeline = api
    uid = _user(db, credits=10, ai=10_000)
    if plan:
        _pro(db, uid, plan)
    for path in ("/api/v1/jobs/quote", "/api/v1/jobs"):
        res = client.post(path, json=_presenter(), headers=_HEADERS)
        assert res.status_code == 402, res.text
        assert res.json()["data"]["code"] == "sku_locked"
    assert _balances(db, uid) == (10, 0, 10_000)
    assert pipeline.start_calls == []


def test_presenter_monthly_cap(db, api, monkeypatch):  # noqa: F811 - shared fixtures
    monkeypatch.setenv("MENIVOR_PRESENTER_MONTHLY_CAP", "1")
    client, _pipeline = api
    uid = _user(db, credits=20, ai=10_000)
    _pro(db, uid)
    assert client.post("/api/v1/jobs", json=_presenter(), headers=_HEADERS).status_code == 200
    res = client.post("/api/v1/jobs", json=_presenter(), headers=_HEADERS)
    assert res.status_code == 402 and res.json()["data"]["code"] == "sku_locked"
    assert _balances(db, uid)[0] == 20 - policy.DEFAULT_PRESENTER_CREDITS


def test_quote_shows_the_same_standard_credits_create_debits(db, api):  # noqa: F811 - shared fixtures
    client, _pipeline = api
    uid = _user(db, credits=10)
    quoted = client.post("/api/v1/jobs/quote", json=_reel(150), headers=_HEADERS).json()["data"]
    assert quoted["per_variant"]["standard"] == 3
    assert quoted["lines"][0]["sku"] == pricing.SKU_LONG_FORM
    res = client.post("/api/v1/jobs", json=_reel(150), headers=_HEADERS)
    assert _debits(db, res.json()["data"]["job_id"]) == [-3]
    assert _balances(db, uid)[0] == 7


def test_retry_charges_the_job_length_again(db, api):  # noqa: F811 - shared fixtures
    client, _pipeline = api
    uid = _user(db, credits=10)
    job_id = client.post("/api/v1/jobs", json=_reel(90), headers=_HEADERS).json()["data"]["job_id"]
    with db() as s:
        JobRepository(s).mark_failed(job_id, "render", "boom")
        CreditRepository(s).grant(uid, 2, "failure_refund", job_id=job_id)
        s.commit()
    res = client.post(f"/api/v1/jobs/{job_id}/retry", headers=_HEADERS)
    assert res.status_code == 200, res.text
    assert _debits(db, job_id) == [-2, 2, -2]


# --------------------------------------------------------------------------- #
# Charge on keep
# --------------------------------------------------------------------------- #
@pytest.fixture()
def keep_on(monkeypatch):
    monkeypatch.setenv("MENIVOR_CHARGE_ON_KEEP", "1")


def test_flag_off_debits_every_variant(db, api, monkeypatch):  # noqa: F811 - shared fixtures
    monkeypatch.delenv("MENIVOR_CHARGE_ON_KEEP", raising=False)
    client, _pipeline = api
    uid = _user(db, credits=10)
    data = client.post("/api/v1/jobs", json=_reel(30, variants=3), headers=_HEADERS).json()["data"]
    assert "keep_required" not in data
    assert _balances(db, uid)[0] == 7


def test_variants_two_and_three_are_debited_only_when_kept(db, api, keep_on):  # noqa: F811 - shared fixtures
    client, pipeline = api
    uid = _user(db, credits=10)
    quoted = client.post("/api/v1/jobs/quote", json=_reel(90, variants=3), headers=_HEADERS).json()["data"]
    assert quoted["charge_on_keep"] is True
    assert quoted["due_now"]["standard"] == 2 and quoted["total"]["standard"] == 6
    res = client.post("/api/v1/jobs", json=_reel(90, variants=3), headers=_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    first, second, third = data["job_ids"]
    assert data["keep_required"] == [second, third] and data["keep_credits"] == 2
    assert len(pipeline.start_calls) == 3  # every variant renders
    assert _balances(db, uid)[0] == 8
    assert _debits(db, second) == [] and _debits(db, third) == []

    view = client.get(f"/api/v1/jobs/{second}", headers=_HEADERS).json()["data"]
    assert view["keep"] == {"required": True, "credits": 2}
    assert not view.get("result_url")
    assert "keep" not in client.get(f"/api/v1/jobs/{first}", headers=_HEADERS).json()["data"]

    # Not finished yet: nothing to keep.
    assert client.post(f"/api/v1/jobs/{second}/keep", headers=_HEADERS).status_code == 409
    _complete(db, second)
    kept = client.post(f"/api/v1/jobs/{second}/keep", headers=_HEADERS)
    assert kept.status_code == 200, kept.text
    assert kept.json()["data"]["debited"] == 2
    assert kept.json()["data"]["job"]["keep"] == {"required": False, "credits": 2}
    # A download retried, double-clicked or raced debits exactly once.
    again = client.post(f"/api/v1/jobs/{second}/keep", headers=_HEADERS)
    assert again.json()["data"]["debited"] == 0
    assert _debits(db, second) == [-2]
    assert _balances(db, uid)[0] == 6
    # A variant paid at create is already kept.
    _complete(db, first)
    assert client.post(f"/api/v1/jobs/{first}/keep", headers=_HEADERS).json()["data"]["debited"] == 0


def test_keep_without_credits_is_402_and_debits_nothing(db, api, keep_on):  # noqa: F811 - shared fixtures
    client, _pipeline = api
    uid = _user(db, credits=1)
    data = client.post("/api/v1/jobs", json=_reel(30, variants=2), headers=_HEADERS).json()["data"]
    second = data["job_ids"][1]
    _complete(db, second)
    res = client.post(f"/api/v1/jobs/{second}/keep", headers=_HEADERS)
    assert res.status_code == 402, res.text
    assert _debits(db, second) == [] and _balances(db, uid)[0] == 0
    with db() as s:
        assert keep.is_pending(s.get(Job, second).params)


def test_keep_of_a_foreign_job_is_404(db, api, keep_on):  # noqa: F811 - shared fixtures
    from app.models.db.models import User

    client, _pipeline = api
    _user(db, credits=5)
    with db() as s:
        other = User(email="other@example.com", api_key_hash="not-this-key", credits=0)
        s.add(other)
        s.flush()
        job = Job(user_id=other.id, kind="avatar_reel", params=keep.pending_marker(1, None),
                  state=const.TASK_STATE_COMPLETE)
        s.add(job)
        s.commit()
        job_id = job.id
    assert client.post(f"/api/v1/jobs/{job_id}/keep", headers=_HEADERS).status_code == 404
    assert _debits(db, job_id) == []


def test_unpaid_variant_enqueue_failure_refunds_nothing(db, api, keep_on):  # noqa: F811 - shared fixtures
    client, pipeline = api
    uid = _user(db, credits=5)
    real_start = pipeline.start_pipeline
    calls = {"n": 0}

    def flaky(job_id, params):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("broker down")
        return real_start(job_id, params)

    pipeline.start_pipeline = flaky
    data = client.post("/api/v1/jobs", json=_reel(30, variants=3), headers=_HEADERS).json()["data"]
    assert _debits(db, data["job_ids"][1]) == []
    assert _balances(db, uid)[0] == 4  # only variant 1 was paid; no free credit appeared


def test_auto_publish_batch_is_paid_in_full(db, api, keep_on, monkeypatch):  # noqa: F811 - shared fixtures
    import app.controllers.v1.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "_split_autopublish", lambda params, uid, rid: (params, ["tiktok"]))
    client, _pipeline = api
    uid = _user(db, credits=5)
    data = client.post("/api/v1/jobs", json=_reel(30, variants=2), headers=_HEADERS).json()["data"]
    assert "keep_required" not in data
    assert _balances(db, uid)[0] == 3


def test_require_kept_guards_other_clean_mp4_surfaces():
    params = keep.pending_marker(2, None)
    with pytest.raises(keep.KeepRequired) as exc:
        keep.require_kept(params, "job-1")
    assert exc.value.as_dict() == {"code": "keep_required", "job_id": "job-1", "credits": 2}
    keep.require_kept(keep.mark_kept(params), "job-1")
    keep.require_kept({}, "job-2")


def test_unpaid_variant_is_never_presigned_a_clean_url(monkeypatch):
    import app.controllers.v1.jobs as jobs_mod

    seen: list[bool] = []
    monkeypatch.setattr(
        jobs_mod,
        "_presign_job_artifacts",
        lambda job, data, rid, include_result=True: seen.append(include_result),
    )
    pending = Job(user_id="u", kind="avatar_reel", params=keep.pending_marker(1, None),
                  state=const.TASK_STATE_COMPLETE, stages={}, progress=100)
    kept = Job(user_id="u", kind="avatar_reel", params=keep.mark_kept(keep.pending_marker(1, None)),
               state=const.TASK_STATE_COMPLETE, stages={}, progress=100)
    jobs_mod._job_public_data(pending, "rid", include_result=True)
    jobs_mod._job_public_data(kept, "rid", include_result=True)
    assert seen == [False, True]
