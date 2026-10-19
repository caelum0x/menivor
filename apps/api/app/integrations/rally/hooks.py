"""Menivor lifecycle hooks -> Rally journeys (dogfood: Rally markets our own apps).

Events: ``signed_up``, ``first_reel_rendered``, ``reel_published``,
``credits_purchased``, ``email_consent_changed``. (``went_inactive`` is computed
by Rally itself.)

Every hook is a cheap no-op unless ``RALLY_EVENTS_KEY`` is set, runs its DB
lookups + HTTP send off-thread, and swallows every error. Idempotency keys are
derived from source record ids, so a retried webhook / re-settled job is
recorded once by Rally.

Consent: Menivor captures lifecycle-email consent as the ``marketing`` kind in
``consent_records`` (Settings > Privacy). Events carry ``consent`` only when the
user has an explicit latest decision; otherwise it is omitted and Rally tracks
the contact without emailing it.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from loguru import logger

from . import client
from .settings import Env, load_settings

CONSENT_KIND = "marketing"
CONSENT_SOURCE = "menivor_privacy_settings"
_TASK_STATE_COMPLETE = 1
# Synthetic placeholder addresses (device-only / provider-less accounts) are not
# mailable; the event is still sent without an email so Rally can track it.
_SYNTHETIC_DOMAINS = ("reelforge.app", "reelforge", "local")

SessionFactory = Callable[[], Any]


def real_email(email: Optional[str]) -> Optional[str]:
    value = (email or "").strip().lower()
    if "@" not in value:
        return None
    domain = value.rsplit("@", 1)[1]
    if any(domain == d or domain.endswith(f".{d}") for d in _SYNTHETIC_DOMAINS):
        return None
    return value


def _session_factory() -> SessionFactory:
    from app.models.db.base import get_session

    return get_session


def _user_context(user_id: str, session_factory: Optional[SessionFactory] = None) -> Tuple[Optional[str], Optional[bool]]:
    """(mailable email, explicit marketing consent or None) for ``user_id``."""
    from app.models.db.models import User
    from app.models.db.repositories import ConsentRepository

    with (session_factory or _session_factory())() as session:
        user = session.get(User, user_id)
        email = real_email(getattr(user, "email", None)) if user is not None else None
        latest = ConsentRepository(session).get_latest(user_id, CONSENT_KIND)
        consent = bool(latest.granted) if latest is not None else None
    return email, consent


def _emit(
    *,
    event: str,
    user_id: str,
    idempotency_key: str,
    properties: Optional[Dict[str, Any]] = None,
    traits: Optional[Dict[str, Any]] = None,
    email: Optional[str] = None,
    lookup_user: bool = True,
    consent_override: Optional[bool] = None,
    env: Optional[Env] = None,
    sync: bool = False,
    transport: Optional[client.Transport] = None,
    session_factory: Optional[SessionFactory] = None,
) -> bool:
    settings = load_settings(env)
    if not settings.enabled or not user_id:
        return False

    def job() -> None:
        mail, consent = (email, None)
        if lookup_user:
            try:
                found_mail, consent = _user_context(user_id, session_factory)
                mail = mail or found_mail
            except Exception as exc:  # noqa: BLE001 - send without context
                logger.debug(f"rally events: user lookup failed for {user_id}: {exc}")
        if consent_override is not None:
            consent = consent_override
        body = client.build_event(
            event=event,
            user_id=user_id,
            idempotency_key=idempotency_key,
            source=settings.source,
            email=real_email(mail),
            traits={"app_name": "Menivor", **(traits or {})},
            properties=properties,
            consent=consent,
            consent_source=CONSENT_SOURCE if consent is not None else None,
        )
        client.send_events([body], settings=settings, transport=transport)

    client.submit(job, sync=sync)
    return True


def track_signed_up(user_id: str, email: Optional[str], *, method: str, **kw: Any) -> bool:
    """New account provisioned. Consent is never known at signup (captured later)."""
    return _emit(
        event="signed_up",
        user_id=str(user_id),
        idempotency_key=f"signed_up:{user_id}",
        email=real_email(email),
        lookup_user=False,  # the row is not committed yet; use the given email
        traits={"signup_method": method},
        properties={"method": method},
        **kw,
    )


def track_render_completed(job_id: str, **kw: Any) -> bool:
    """Send ``first_reel_rendered`` when this is the owner's first completed job."""
    settings = load_settings(kw.get("env"))
    if not settings.enabled or not job_id:
        return False
    session_factory = kw.pop("session_factory", None)
    sync = kw.pop("sync", False)

    def job() -> None:
        from sqlalchemy import func, select

        from app.models.db.models import Job

        with (session_factory or _session_factory())() as session:
            row = session.get(Job, job_id)
            if row is None or not row.user_id:
                return
            user_id = str(row.user_id)
            completed = session.execute(
                select(func.count()).select_from(Job).where(
                    Job.user_id == user_id, Job.state == _TASK_STATE_COMPLETE
                )
            ).scalar_one()
        if int(completed or 0) != 1:
            return
        _emit(
            event="first_reel_rendered",
            user_id=user_id,
            idempotency_key=f"first_reel_rendered:{user_id}",
            properties={"job_id": job_id},
            sync=True,
            session_factory=session_factory,
            **kw,
        )

    client.submit(job, sync=sync)
    return True


def track_reel_published(user_id: str, job_id: str, platform: str, external_id: str = "", **kw: Any) -> bool:
    return _emit(
        event="reel_published",
        user_id=str(user_id),
        idempotency_key=f"reel_published:{job_id}:{platform}",
        properties={"job_id": job_id, "platform": platform, **({"external_id": external_id} if external_id else {})},
        **kw,
    )


def track_credits_purchased(
    user_id: str,
    *,
    provider: str,
    reference: str,
    credits: int,
    workspace_id: Optional[str] = None,
    properties_extra: Optional[Dict[str, Any]] = None,
    **kw: Any,
) -> bool:
    return _emit(
        event="credits_purchased",
        user_id=str(user_id),
        idempotency_key=f"credits_purchased:{provider}:{reference}",
        properties={
            "provider": provider,
            "credits": int(credits),
            **({"workspace_id": workspace_id} if workspace_id else {}),
            **(properties_extra or {}),
        },
        **kw,
    )


def track_email_consent(user_id: str, granted: bool, record_id: Any, **kw: Any) -> bool:
    """Mirror a marketing-consent decision so Rally honours opt-outs immediately."""
    return _emit(
        event="email_consent_changed",
        user_id=str(user_id),
        idempotency_key=f"email_consent_changed:{record_id}",
        properties={"granted": bool(granted)},
        consent_override=bool(granted),
        **kw,
    )


__all__ = [
    "real_email",
    "track_credits_purchased",
    "track_email_consent",
    "track_reel_published",
    "track_render_completed",
    "track_signed_up",
]
