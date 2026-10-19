"""Wave E M-5 (MR3): onboarding mail Day 0/1/3/7 that stops after payment."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.db.base as db_base
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import CreditRepository
from app.services import audit, mailer
from app.services.billing import lifecycle_mail
from app.services.email_templates import render_email
from app.services.lifecycle import rally_tx_client as rally
from app.services.lifecycle import sequence, templates

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
DENYLIST = json.loads((Path(__file__).resolve().parents[2] / "policy" / "copy-denylist.json").read_text())
GATED = re.compile(r"\b(presenters?|lip[- ]?sync(ed)?|avatars?|talking head|publish(ing|es)?|schedul(e|ing))\b", re.I)


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
    monkeypatch.setenv("MENIVOR_MAIL_UNSUBSCRIBE_SECRET", "test-secret-for-unsubscribe-links")
    monkeypatch.delenv("RALLY_TX_URL", raising=False)
    monkeypatch.delenv("RALLY_TX_KEY", raising=False)
    return maker


@pytest.fixture()
def outbox(monkeypatch):
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(mailer, "configured", lambda: True)

    def _send(to, rendered):
        sent.append((to, rendered.subject, rendered.text))
        return True

    monkeypatch.setattr(lifecycle_mail, "_send", _send)
    return sent


def _user(maker, email="new@example.com", at=T0) -> str:
    with maker() as s:
        u = User(email=email, created_at=at.replace(tzinfo=None))
        s.add(u)
        s.commit()
        return u.id


def _run_hourly(days: float, start=T0, transport=None) -> list[datetime]:
    moments = []
    now = start
    while now <= start + timedelta(days=days):
        sequence.run(now=now, transport=transport)
        moments.append(now)
        now += timedelta(hours=1)
    return moments


SUBJECT_STEP = {
    "Your first reel starts with one link": "day0",
    "Pick the hook that sounds like you": "day1",
    "Captions for a video you already have": "day3",
    "Keep making reels": "day7",
}


def _steps(outbox) -> list[str]:
    return [SUBJECT_STEP[subject] for _, subject, _ in outbox]


def _sent_at(maker, user_id) -> dict[str, datetime]:
    from sqlalchemy import select

    from app.models.db.models import AuditLog

    with maker() as s:
        rows = s.execute(
            select(AuditLog.target_type, AuditLog.action).where(AuditLog.actor_user_id == user_id)
        ).all()
    return {t: a for t, a in rows}


# --------------------------------------------------------------------------- #
# Sequence
# --------------------------------------------------------------------------- #
def test_fake_clock_sends_exactly_day_0_1_3_7(factory, outbox, monkeypatch):
    uid = _user(factory)
    sent_when: list[tuple[str, datetime]] = []
    real = lifecycle_mail._send

    clock = {"now": T0}

    def _send(to, rendered):
        sent_when.append((SUBJECT_STEP[rendered.subject], clock["now"]))
        return real(to, rendered)

    monkeypatch.setattr(lifecycle_mail, "_send", _send)
    now = T0
    while now <= T0 + timedelta(days=10):
        clock["now"] = now
        sequence.run(now=now)
        now += timedelta(hours=1)
    assert _steps(outbox) == ["day0", "day1", "day3", "day7"]
    for step, at in sent_when:
        assert at - T0 == timedelta(days=templates.OFFSET_DAYS[step])
    assert all(to == "new@example.com" for to, _, _ in outbox)
    assert all(a == sequence.ACTION_SENT for a in _sent_at(factory, uid).values())


def test_stops_after_payment(factory, outbox):
    uid = _user(factory)
    _run_hourly(2)
    with factory() as s:
        CreditRepository(s).grant(uid, 30, "purchase:dodo:pay_1")
        s.commit()
    _run_hourly(8, start=T0 + timedelta(days=2, hours=1))
    assert _steps(outbox) == ["day0", "day1"]
    decisions = _sent_at(factory, uid)
    assert decisions["onboarding:day3"] == sequence.ACTION_SUPPRESSED
    assert decisions["onboarding:day7"] == sequence.ACTION_SUPPRESSED


def test_card_check_alone_is_not_payment(factory, outbox):
    uid = _user(factory)
    with factory() as s:
        CreditRepository(s).grant(uid, 1, "purchase:dodo:card_check")
        s.commit()
        assert sequence.has_paid(s, uid) is False


def test_unsubscribed_account_gets_nothing(factory, outbox):
    uid = _user(factory)
    with factory() as s:
        lifecycle_mail.unsubscribe(s, uid)
        s.commit()
    _run_hourly(10)
    assert outbox == []
    onboarding = {k: v for k, v in _sent_at(factory, uid).items() if k.startswith("onboarding:")}
    assert set(onboarding) == {f"onboarding:{s}" for s in templates.STEPS}
    assert set(onboarding.values()) == {sequence.ACTION_SUPPRESSED}


def test_every_email_has_the_unsubscribe_footer_and_header(factory):
    uid = _user(factory)
    url = lifecycle_mail.unsubscribe_url(uid)
    assert url
    for step in templates.STEPS:
        rendered = render_email(templates.content(step, web_url="https://menivor.com", unsubscribe_url=url))
        assert url in rendered.text
        assert rendered.headers["List-Unsubscribe"] == f"<{url}>"
        assert rendered.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_late_signup_window_sends_only_the_latest_due_step(factory, outbox):
    uid = _user(factory, at=T0 - timedelta(days=1, hours=3))
    sequence.run(now=T0)
    assert _steps(outbox) == ["day1"]
    assert _sent_at(factory, uid)["onboarding:day0"] == sequence.ACTION_SUPPRESSED


# --------------------------------------------------------------------------- #
# No duplicate with MG5 / 411e7744
# --------------------------------------------------------------------------- #
def _mg5_sent(maker, uid, kind, at):
    with maker() as s:
        row = audit.record(s, actor_user_id=uid, action=lifecycle_mail.ACTION_SENT,
                           target_type=f"lifecycle:{kind}", target_id="cause", metadata={})
        row.created_at = at.replace(tzinfo=None)
        s.commit()


def test_day7_dropped_when_mg5_credits_low_went_out(factory, outbox):
    uid = _user(factory)
    _mg5_sent(factory, uid, lifecycle_mail.CREDITS_LOW, T0 + timedelta(days=4))
    _run_hourly(10)
    assert _steps(outbox) == ["day0", "day1", "day3"]
    assert _sent_at(factory, uid)["onboarding:day7"] == sequence.ACTION_SUPPRESSED


def test_step_waits_after_a_recent_mg5_email(factory, outbox):
    uid = _user(factory)
    _mg5_sent(factory, uid, lifecycle_mail.AUTOPILOT_PAUSED, T0 - timedelta(hours=1))
    sequence.run(now=T0)
    assert outbox == []
    sequence.run(now=T0 + timedelta(hours=20))
    assert _steps(outbox) == ["day0"]


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
def _rule_hits(rule, text):
    unit = re.sub(r"\s+", " ", text).strip()
    for token in rule.get("exceptTokens", []):
        unit = re.sub(re.escape(token), " ", unit, flags=re.I)
    m = rule["match"]
    if m["type"] == "regex":
        flags = 0 if m.get("caseSensitive", DENYLIST["defaults"].get("caseSensitive")) else re.I
        return re.search(m["value"], unit, flags) is not None
    ranges = [(int(lo, 16), int(hi, 16)) for lo, hi in m["ranges"]]
    return any(lo <= ord(ch) <= hi for ch in unit for lo, hi in ranges)


def _units(step):
    content = templates.content(step, web_url="https://menivor.com", unsubscribe_url="https://api.menivor.com/u")
    return [content.subject, content.preheader, content.title, content.reason, *content.paragraphs,
            content.action.label]


@pytest.mark.parametrize("step", templates.STEPS)
def test_templates_pass_the_denylist_and_name_no_gated_feature(step):
    rules = [r for r in DENYLIST["rules"] if "menivor" in r["products"] and "outbound" in r["surfaces"]
             and r.get("severity", DENYLIST["defaults"]["severity"]) == "error"]
    assert rules
    sourced = set(templates.plan_lines())
    for text in _units(step):
        assert not GATED.search(text), (step, text)
        # Plan-config lines carry the copy-source escape (CLAIMS-RULES 4.4).
        escaped = text in sourced
        hits = [r["id"] for r in rules if _rule_hits(r, text)
                and not (escaped and r.get("sourceEscape", DENYLIST["defaults"].get("sourceEscape")))]
        assert hits == [], (step, text, hits)


def test_day7_prices_come_from_plan_config_and_comparison_needs_a_source():
    from app.services.billing.plans import list_plans

    pack = sorted(list_plans(purchasable_only=True), key=lambda p: p.price_usd)[0]
    text = " ".join(_units("day7"))
    assert f"{pack.credits} reels for ${pack.price_usd:.0f}" in text
    assert templates.DAY7_COMPARISON is None
    assert "source:" not in text
    sourced = templates.content(
        "day7", web_url="https://menivor.com", unsubscribe_url="https://api.menivor.com/u",
        comparison=templates.Comparison("A comparison line.", "https://example.com/pricing"),
    )
    assert any("source: https://example.com/pricing" in p for p in sourced.paragraphs)
    unsourced = templates.content(
        "day7", web_url="https://menivor.com", unsubscribe_url="https://api.menivor.com/u",
        comparison=templates.Comparison("A comparison line.", ""),
    )
    assert not any("comparison" in p.lower() for p in unsourced.paragraphs)


# --------------------------------------------------------------------------- #
# Rally Send client (contract 5.2)
# --------------------------------------------------------------------------- #
class _Stub:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body))
        status = self.statuses.pop(0) if self.statuses else 202
        return status, ({"id": f"msg_{len(self.calls)}"} if status in (200, 202) else {})


def test_rally_path_sends_one_idempotency_key_per_user_and_step(factory, monkeypatch):
    monkeypatch.setenv("RALLY_TX_URL", "https://vcpeer.test")
    monkeypatch.setenv("RALLY_TX_KEY", "rtx_test")
    uid = _user(factory)
    stub = _Stub([429])  # the first Day 0 attempt hits the cap and is retried
    _run_hourly(10, transport=stub)
    keys = [body["idempotency_key"] for _, _, body in stub.calls]
    assert keys[0] == keys[1] == f"menivor:onboarding:{uid}:day0"
    assert keys[1:] == [f"menivor:onboarding:{uid}:{s}" for s in templates.STEPS]
    url, headers, body = stub.calls[-1]
    assert url == "https://vcpeer.test/api/rally/v1/transactional/send"
    assert headers["Authorization"] == "Bearer rtx_test"
    assert body["product"] == "menivor" and body["from_local"] == "hello"
    assert body["unsubscribe_url"].startswith("https://")
    assert "@" not in body["from_local"]


def test_rally_suppressed_address_is_recorded_and_never_retried(factory, monkeypatch):
    monkeypatch.setenv("RALLY_TX_URL", "https://vcpeer.test")
    monkeypatch.setenv("RALLY_TX_KEY", "rtx_test")
    uid = _user(factory)
    stub = _Stub([422])
    sequence.run(now=T0, transport=stub)
    sequence.run(now=T0 + timedelta(hours=1), transport=stub)
    assert len(stub.calls) == 1
    assert _sent_at(factory, uid)["onboarding:day0"] == sequence.ACTION_SUPPRESSED


def test_rally_client_is_off_without_url_and_never_raises(monkeypatch):
    monkeypatch.delenv("RALLY_TX_URL", raising=False)
    assert rally.configured() is False
    monkeypatch.setenv("RALLY_TX_URL", "https://vcpeer.test/api/rally/v1/transactional/send")
    monkeypatch.setenv("RALLY_TX_KEY", "k")
    assert rally.endpoint() == "https://vcpeer.test/api/rally/v1/transactional/send"

    def boom(*_a):
        raise OSError("down")

    assert rally.send({"x": 1}, boom).outcome == rally.RETRY


def test_worker_is_registered_with_an_hourly_beat():
    from app.workers.celery_app import celery_app

    assert "app.workers.tasks_lifecycle" in celery_app.conf.include
    entry = celery_app.conf.beat_schedule["menivor-onboarding-mail"]
    assert entry["task"] == "app.workers.tasks_lifecycle.onboarding_mail_tick_task"
