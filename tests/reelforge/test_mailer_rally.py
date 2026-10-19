"""Product mail goes through Rally Send first, SMTP only as the fallback.

Owner rule 2026-10-05: every product's email goes through Rally's transactional
API; a suppressed address is never retried over SMTP; Rally trouble never loses
a message while SMTP is configured.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import mailer

SMTP_NAMES = ("SMTP_HOST", "SMTP_FROM", "EMAIL_FROM", "MENIVOR_SMTP_HOST", "MENIVOR_SMTP_FROM", "MENIVOR_EMAIL_FROM")


@pytest.fixture()
def rally_env(monkeypatch):
    for name in SMTP_NAMES + ("RALLY_TX_FROM_LOCAL", "MENIVOR_RALLY_TX_FROM_LOCAL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RALLY_TX_URL", "https://rally.example.com")
    monkeypatch.setenv("RALLY_TX_KEY", "rtx_" + "k" * 32)


class Transport:
    def __init__(self, status: int = 202, data: dict | None = None, exc: Exception | None = None):
        self.status, self.data, self.exc = status, data or {"id": "m1"}, exc
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body))
        if self.exc:
            raise self.exc
        return self.status, self.data


@pytest.fixture()
def smtp_spy(monkeypatch):
    sent: list = []

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **k):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    return sent


def test_rally_alone_counts_as_configured(rally_env):
    assert mailer.smtp_configured() is False
    assert mailer.configured() is True


def test_sends_through_rally_with_product_body(rally_env, smtp_spy):
    t = Transport()
    ok = mailer.send_email(
        to="a@example.com",
        subject="Your reel\r\nis ready",
        text="t",
        html="<p>h</p>",
        headers={"List-Unsubscribe": "<https://api.menivor.com/u?t=1>, <mailto:hello@menivor.com>"},
        tags=("jobs",),
        transport=t,
    )
    assert ok is True and smtp_spy == []
    url, headers, body = t.calls[0]
    assert url == "https://rally.example.com/api/rally/v1/transactional/send"
    assert headers["Authorization"].startswith("Bearer rtx_")
    assert body["product"] == "menivor" and body["from_local"] == "hello"
    assert body["subject"] == "Your reel  is ready"
    assert body["unsubscribe_url"] == "https://api.menivor.com/u?t=1"
    assert body["tags"] == ["jobs"]
    assert body["idempotency_key"].startswith("menivor:mail:")


def test_suppressed_address_is_not_retried_over_smtp(rally_env, monkeypatch, smtp_spy):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM", "hello@menivor.com")
    assert mailer.send_email(to="a@example.com", subject="s", text="t", transport=Transport(422)) is False
    assert smtp_spy == []


@pytest.mark.parametrize("transport", [Transport(429), Transport(500), Transport(exc=OSError("down"))])
def test_rally_trouble_falls_back_to_smtp(rally_env, monkeypatch, smtp_spy, transport):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM", "hello@menivor.com")
    assert mailer.send_email(to="a@example.com", subject="s", text="t", transport=transport) is True
    assert len(smtp_spy) == 1


def test_rally_trouble_without_smtp_is_a_false_not_a_raise(rally_env, smtp_spy):
    assert mailer.send_email(to="a@example.com", subject="s", text="t", transport=Transport(500)) is False


def test_smtp_only_still_works_and_carries_unsubscribe_headers(monkeypatch, smtp_spy):
    monkeypatch.delenv("RALLY_TX_URL", raising=False)
    monkeypatch.delenv("RALLY_TX_KEY", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM", "hello@menivor.com")
    ok = mailer.send_email(
        to="a@example.com",
        subject="s",
        text="t",
        headers={"List-Unsubscribe": "<https://x.example/u>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click", "Bcc": "evil@x.y"},
    )
    assert ok is True
    msg = smtp_spy[0]
    assert msg["List-Unsubscribe"] == "<https://x.example/u>"
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert msg["Bcc"] is None


def test_explicit_idempotency_key_and_from_local_override(rally_env, monkeypatch):
    monkeypatch.setenv("RALLY_TX_FROM_LOCAL", "No-Reply")
    t = Transport()
    mailer.send_email(to="a@example.com", subject="s", text="t", idempotency_key="job:42:ready", transport=t)
    body = t.calls[0][2]
    assert body["idempotency_key"] == "job:42:ready"
    assert body["from_local"] == "no-reply"
    assert "html" not in body


def test_derived_key_is_stable_per_day_and_message():
    day1 = datetime(2026, 10, 6, 1, tzinfo=timezone.utc)
    day1_late = datetime(2026, 10, 6, 23, tzinfo=timezone.utc)
    day2 = datetime(2026, 10, 7, tzinfo=timezone.utc)
    k = mailer.derived_idempotency_key("A@example.com", "s", "t", None, day1)
    assert k == mailer.derived_idempotency_key("a@example.com", "s", "t", None, day1_late)
    assert k != mailer.derived_idempotency_key("a@example.com", "s", "t", None, day2)
    assert k != mailer.derived_idempotency_key("a@example.com", "s", "t2", None, day1)
    assert len(k) <= 200


def test_https_unsubscribe_url_ignores_mailto_and_http():
    assert mailer.https_unsubscribe_url({"List-Unsubscribe": "<mailto:x@y.z>, <http://a.b/u>"}) == ""
    assert mailer.https_unsubscribe_url(None) == ""


@pytest.mark.parametrize("status", [401, 403])
def test_refused_key_never_sends_opt_out_mail_over_smtp(rally_env, monkeypatch, smtp_spy, status):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM", "hello@menivor.com")
    opt_out = {"List-Unsubscribe": "<https://api.menivor.com/u?t=1>"}
    assert mailer.send_email(to="a@example.com", subject="s", text="t", headers=opt_out, transport=Transport(status)) is False
    assert smtp_spy == []
    # Plain transactional mail (no opt-out) still reaches the user over SMTP.
    assert mailer.send_email(to="a@example.com", subject="s", text="t", transport=Transport(status)) is True
    assert len(smtp_spy) == 1
