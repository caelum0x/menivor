"""Transactional mailer: Rally Send first, SMTP (OCI Email Delivery) as fallback.

Rally Send (``RALLY_TX_URL`` + ``RALLY_TX_KEY``, product ``menivor``, From
forced by Rally to ``<local>@mail.menivor.com``) is the primary path, so
suppression, idempotency and delivery logs live in Rally. A suppressed address
(422) is never retried over SMTP. A transport error, 429 or any other answer
falls back to SMTP so mail is never lost while Rally is unreachable.

SMTP fallback over OCI Email Delivery.

Configuration (names only): ``SMTP_HOST``, ``SMTP_PORT`` (465 = implicit TLS,
anything else STARTTLS; default 587), ``SMTP_USER``, ``SMTP_PASS``,
``SMTP_FROM`` (an approved sender; falls back to ``EMAIL_FROM``, either a bare
address or ``Name <address>``) and optional ``SMTP_SENDER_NAME``. Each may be
prefixed ``MENIVOR_`` to override the shared value. Unconfigured = the send
is skipped and logged, never an exception.
"""

from __future__ import annotations

import hashlib
import os
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime, timezone
from email.utils import formataddr, make_msgid, parseaddr
from typing import Any, Mapping

from loguru import logger

_TIMEOUT_SECONDS = 20


def _env(name: str) -> str:
    return (os.environ.get(f"MENIVOR_{name}") or os.environ.get(name) or "").strip()


def _sender() -> tuple[str, str]:
    """``(display name, address)`` of the approved sender, or ``("", "")``."""
    name, address = parseaddr(_env("SMTP_FROM") or _env("EMAIL_FROM"))
    if "@" not in address:
        return "", ""
    return (_env("SMTP_SENDER_NAME") or name or "Menivor"), address


def smtp_configured() -> bool:
    return bool(_env("SMTP_HOST") and _sender()[1])


def configured() -> bool:
    """True when at least one send path (Rally Send or SMTP) is configured."""
    from app.services.lifecycle import rally_tx_client as rally

    return rally.configured() or smtp_configured()


# Headers a caller may add to the SMTP message (everything else is ignored).
_ALLOWED_HEADERS = ("List-Unsubscribe", "List-Unsubscribe-Post", "Reply-To")


def _clean_header(value: str) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def build_message(
    to: str, subject: str, text: str, html: str | None = None, headers: Mapping[str, str] | None = None
) -> EmailMessage:
    name, sender = _sender()
    msg = EmailMessage()
    msg["From"] = formataddr((name, sender))
    msg["To"] = to
    msg["Subject"] = subject.replace("\r", " ").replace("\n", " ")
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    for name_, value in (headers or {}).items():
        if name_ in _ALLOWED_HEADERS and str(value).strip():
            msg[name_] = _clean_header(value)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def https_unsubscribe_url(headers: Mapping[str, str] | None) -> str:
    """The first https target of a ``List-Unsubscribe`` header, or ``""``."""
    raw = str((headers or {}).get("List-Unsubscribe", "") or "")
    for part in raw.split(","):
        target = part.strip().strip("<>").strip()
        if target.startswith("https://") and len(target) <= 2000:
            return target
    return ""


def derived_idempotency_key(to: str, subject: str, text: str, html: str | None, now: datetime | None = None) -> str:
    """One key per identical message, recipient and UTC day (a retried send never mails twice)."""
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    digest = hashlib.sha256("\x1f".join((day, to.strip().lower(), subject, text, html or "")).encode()).hexdigest()
    return f"menivor:mail:{digest[:48]}"


def _send_via_rally(
    *, to: str, subject: str, text: str, html: str | None, headers: Mapping[str, str] | None,
    idempotency_key: str | None, tags: tuple[str, ...], transport: Any = None,
) -> str:
    """Rally Send outcome: ``sent``, ``suppressed`` or ``fallback``."""
    from app.services.lifecycle import rally_tx_client as rally

    if not rally.configured():
        return "fallback"
    from_local = (_env("RALLY_TX_FROM_LOCAL") or rally.FROM_LOCAL).lower()
    body = rally.build_body(
        to=to,
        subject=_clean_header(subject),
        html=html or "",
        text=text,
        key=(idempotency_key or derived_idempotency_key(to, subject, text, html))[:200],
        unsubscribe_url=https_unsubscribe_url(headers),
        tags=tags,
    )
    body["from_local"] = from_local
    if not body["html"]:
        body.pop("html")
    result = rally.send(body, transport)
    if result.outcome == rally.SENT:
        return "sent"
    if result.outcome == rally.SUPPRESSED:
        logger.info("mailer: Rally holds the address as suppressed; not sent")
        return "suppressed"
    if result.status in (401, 403) and https_unsubscribe_url(headers):
        # Opt-out mail must honour Rally's suppression list: with the key refused we
        # cannot check it, so this message is not sent over SMTP either.
        logger.error(f"mailer: Rally refused the key ({result.status}); opt-out mail not sent; fix RALLY_TX_KEY")
        return "suppressed"
    logger.warning(f"mailer: Rally Send answered {result.outcome} ({result.status}); trying SMTP")
    return "fallback"


def send_email(
    *,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
    headers: Mapping[str, str] | None = None,
    idempotency_key: str | None = None,
    tags: tuple[str, ...] = (),
    transport: Any = None,
) -> bool:
    """Send one email (Rally Send, then SMTP). Returns False (and logs) on any failure."""
    outcome = _send_via_rally(
        to=to, subject=subject, text=text, html=html, headers=headers,
        idempotency_key=idempotency_key, tags=tags, transport=transport,
    )
    if outcome == "sent":
        return True
    if outcome == "suppressed":
        return False
    if not smtp_configured():
        logger.warning("mailer: SMTP_HOST / SMTP_FROM not configured; email skipped")
        return False
    host = _env("SMTP_HOST")
    try:
        port = int(_env("SMTP_PORT") or "587")
    except ValueError:
        port = 587
    user, password = _env("SMTP_USER"), _env("SMTP_PASS") or _env("SMTP_PASSWORD")
    msg = build_message(to, subject, text, html, headers)
    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT_SECONDS, context=context) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=_TIMEOUT_SECONDS) as smtp:
                smtp.starttls(context=context)
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.error(f"mailer: send failed: {type(exc).__name__}")
        return False
