"""Wave E M-4 (MR1): funnel read-out per user since 2026-09-25.

Real SQLite: users, the credit ledger, jobs, creator plans, the ``16bfdc06``
funnel events (derived by ``sync_events``) and first-touch attribution.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.funnel_readout import router as readout_router
from app.domains.funnel_readout import service
from app.domains.funnel_readout.models import FunnelAttribution  # noqa: F401 - registers the table
from app.domains.reels.keep import pending_marker
from app.models import const
from app.models.db.base import Base
from app.models.db.creator_subscription import CreatorSubscription
from app.models.db.models import Job, User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services.funnel.store import sync_events
from app.utils import utils

STAFF_KEY = "staff-key"
USER_KEY = "user-key"


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=timezone.utc)


@pytest.fixture()
def factory(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        s = maker()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(readout_router, "get_session", _session)
    import app.controllers.v1.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "get_session", _session)
    return maker


def _user(s, email, created, *, key="", staff=False) -> str:
    u = User(
        email=email,
        api_key_hash=hashlib.sha256(key.encode()).hexdigest() if key else "",
        created_at=created,
        is_staff=staff,
    )
    s.add(u)
    s.flush()
    return u.id


def _job(s, uid, day, params=None, state=const.TASK_STATE_COMPLETE):
    j = Job(user_id=uid, kind="avatar_reel", params=params or {}, state=state)
    s.add(j)
    s.flush()
    j.updated_at = _at(day, 18)
    return j.id


@pytest.fixture()
def fixture_db(factory):
    """Five users: one before launch, a payer via Scribase, a card-check only,
    one with only an unpaid charge-on-keep variant, one with no attribution."""
    with factory() as s:
        old = _user(s, "old@example.com", _at(20))
        payer = _user(s, "payer@example.com", _at(25))
        carded = _user(s, "card@example.com", _at(26))
        unkept = _user(s, "unkept@example.com", _at(27))
        bare = _user(s, "bare@example.com", _at(28))
        staff = _user(s, "staff@example.com", _at(10), key=STAFF_KEY, staff=True)
        _user(s, "user@example.com", _at(10), key=USER_KEY)
        repo = CreditRepository(s)
        for uid in (old, payer, carded, unkept):
            repo.grant(uid, 1, "signup")
        repo.grant(payer, 30, "purchase:dodo:pay_1")
        s.add(CreatorSubscription(user_id=payer, plan_key="creator", status="active"))
        _job(s, old, 21)
        _job(s, payer, 25)
        _job(s, carded, 26)
        _job(s, unkept, 27, params=pending_marker(1, None))
        _job(s, bare, 28, state=const.TASK_STATE_FAILED)
        service.record_attribution(s, payer, source="scribase", utm_campaign="launch-video")
        service.record_attribution(s, carded, utm_source="producthunt", referrer="https://www.producthunt.com/")
        s.commit()
    sync_events()
    return {"old": old, "payer": payer, "carded": carded, "unkept": unkept, "bare": bare, "staff": staff}


def test_rows_since_launch(factory, fixture_db):
    with factory() as s:
        rows = {r.user_id: r for r in service.readout(s)}
    assert fixture_db["old"] not in rows
    payer = rows[fixture_db["payer"]]
    assert payer.card_check and payer.first_render and payer.first_kept and payer.first_payment
    assert payer.plan == "creator" and payer.source == "scribase" and payer.utm_campaign == "launch-video"
    carded = rows[fixture_db["carded"]]
    assert carded.plan == "free" and carded.first_payment is None
    assert carded.source == "unknown" and carded.utm_source == "producthunt"
    unkept = rows[fixture_db["unkept"]]
    assert unkept.first_render and unkept.first_kept is None
    bare = rows[fixture_db["bare"]]
    assert (bare.card_check, bare.first_render, bare.source, bare.referrer) == (None, None, "unknown", "unknown")


def test_totals_match_raw_sql(factory, fixture_db):
    since = service.DEFAULT_SINCE.replace(tzinfo=None).isoformat(sep=" ")
    with factory() as s:
        payload = service.readout_payload(s)
        users = s.execute(text("SELECT id FROM users WHERE created_at >= :d"), {"d": since}).scalars().all()

        def reach(step: str) -> int:
            return s.execute(
                text(
                    "SELECT COUNT(*) FROM funnel_events e JOIN users u ON u.id = e.user_id "
                    "WHERE e.step = :step AND u.created_at >= :d"
                ),
                {"step": step, "d": since},
            ).scalar()

        scribase = s.execute(
            text("SELECT COUNT(*) FROM funnel_attribution a JOIN users u ON u.id = a.user_id "
                 "WHERE a.source = 'scribase' AND u.created_at >= :d"),
            {"d": since},
        ).scalar()
    totals = payload["totals"]
    assert totals["users"] == len(users) == 4
    assert totals["reach"]["signed_up"] == len(users)
    assert totals["reach"]["card_check"] == reach("card_check")
    assert totals["reach"]["first_render"] == reach("first_reel")
    assert totals["reach"]["first_payment"] == reach("paid")
    assert totals["by_source"]["scribase"] == scribase
    json.dumps(payload)  # the scoreboard reads it as JSON


def test_unknown_is_never_zero(factory, fixture_db):
    with factory() as s:
        totals = service.readout_payload(s)["totals"]
    assert totals["by_source"]["unknown"] == 2  # unkept + bare
    assert "0" not in totals["by_source"] and 0 not in totals["by_source"].values()
    assert totals["by_campaign"]["unknown"] == 3


def test_attribution_is_first_touch_and_partner_sources_only(factory):
    with factory() as s:
        uid = _user(s, "a@example.com", _at(29))
        assert service.record_attribution(s, uid, source="rally") is True
        assert service.record_attribution(s, uid, source="scribase") is False
        with pytest.raises(ValueError):
            service.record_attribution(s, "other", source="somewhere")
        s.commit()
        assert s.get(FunnelAttribution, uid).source == "rally"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(readout_router.router)

    def handler(_request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code,
                            content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, handler)
    return TestClient(app)


def test_non_admin_gets_403_and_staff_gets_the_readout(factory, fixture_db):
    client = _client()
    res = client.get("/api/v1/admin/funnel/readout", headers={"x-api-key": USER_KEY})
    assert res.status_code == 403
    res = client.get("/api/v1/admin/funnel/readout", headers={"x-api-key": STAFF_KEY})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["totals"]["users"] == 4
    res = client.get("/api/v1/admin/funnel/readout?since=bad", headers={"x-api-key": STAFF_KEY})
    assert res.status_code == 422


def test_signed_in_user_records_first_touch(factory, fixture_db):
    client = _client()
    res = client.post(
        "/api/v1/funnel/attribution",
        json={"utm_source": "tiktok", "utm_campaign": "wave-e"},
        headers={"x-api-key": USER_KEY},
    )
    assert res.status_code == 200 and res.json()["data"]["recorded"] is True
    again = client.post("/api/v1/funnel/attribution", json={"utm_source": "x"}, headers={"x-api-key": USER_KEY})
    assert again.json()["data"]["recorded"] is False


def test_router_is_mounted_and_admin_path_is_staff_only_in_allowlist():
    from fastapi.routing import APIRoute

    from app.core import api_surface as surf
    from app.router import build_full_router

    full = build_full_router()
    paths = {r.path for r in full.routes if isinstance(r, APIRoute)}
    assert "/api/v1/admin/funnel/readout" in paths
    assert surf.is_staff_only("/api/v1/admin/funnel/readout")


def test_cli_prints_table_and_json(factory, fixture_db, capsys):
    tool = Path(__file__).resolve().parents[2] / "scripts" / "funnel-readout.py"
    spec = importlib.util.spec_from_file_location("funnel_readout_cli", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--since", "2026-09-25"]) == 0
    out = capsys.readouterr().out
    assert "users: 4" in out and "scribase" in out
    assert mod.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["totals"]["users"] == 4
