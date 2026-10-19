"""Viewer accounts per channel (MV6): sign in, resume across devices, sign out, delete.

* **Isolation:** a viewer is the pair (channel, Scribase Auth subject). Signing
  in on channel A never makes the person a viewer of channel B; a session for A
  is refused on B's routes.
* **Resume:** one progress row per (viewer, title), written by any device (web,
  mobile, TV) and read by all; titles of other channels are refused.
* **Delete:** removes the viewer's watch history and the viewer row in one
  transaction; every session token stops working at once.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.ott.models import STATUS_PUBLISHED, OttChannel, OttTitle

from . import auth, session as viewer_session
from .models import OttViewer, OttWatchProgress

DEVICES = ("web", "ios", "android", "tv")
FINISHED_RATIO = 0.95
CONTINUE_LIMIT = 20
MAX_NAME = 60


class ViewerError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def now() -> datetime:
    return datetime.now(timezone.utc)


def published_channel(session: Session, handle: str) -> OttChannel:
    channel = session.execute(select(OttChannel).where(OttChannel.handle == str(handle or "").lower())
                              ).scalar_one_or_none()
    if channel is None or channel.status != STATUS_PUBLISHED:
        raise ViewerError(404, "not_found", "channel not found")
    return channel


def sign_in(session: Session, handle: str, access_token: str, *, env: Optional[Mapping[str, str]] = None,
            device: str = "web") -> dict[str, Any]:
    """Exchange a Scribase Auth token for a session on this channel (creates the viewer once)."""
    channel = published_channel(session, handle)
    try:
        identity = auth.verify(access_token, env)
    except auth.AuthRefused as exc:
        raise ViewerError(401, "sign_in", "Sign-in did not work. Ask for a new code and try again.") from exc
    viewer = session.execute(select(OttViewer).where(OttViewer.channel_id == channel.id,
                                                     OttViewer.auth_subject == identity.subject)
                             ).scalar_one_or_none()
    created = False
    if viewer is None:
        viewer = OttViewer(channel_id=channel.id, auth_subject=identity.subject, email=identity.email,
                           display_name=identity.email.split("@")[0][:MAX_NAME])
        try:
            with session.begin_nested():
                session.add(viewer)
            created = True
        except IntegrityError:
            viewer = session.execute(select(OttViewer).where(OttViewer.channel_id == channel.id,
                                                             OttViewer.auth_subject == identity.subject)
                                     ).scalar_one()
    viewer.email = identity.email
    viewer.last_seen_at = now()
    session.flush()
    try:
        token, exp = viewer_session.issue(viewer)
    except viewer_session.SessionRefused as exc:
        raise ViewerError(503, "sessions_off", "Sign-in is not available right now.") from exc
    return {"session": token, "expires_at": exp, "created": created, "viewer": viewer_view(viewer),
            "channel": {"id": channel.id, "handle": channel.handle, "title": channel.title}, "device": device}


def viewer_view(viewer: OttViewer) -> dict[str, Any]:
    return {"id": viewer.id, "email": viewer.email, "display_name": viewer.display_name,
            "member_since": viewer.created_at.isoformat() if viewer.created_at else None}


def resolve(session: Session, token: str, handle: str) -> OttViewer:
    channel = published_channel(session, handle)
    try:
        return viewer_session.viewer_for(session, token, channel_id=channel.id)
    except viewer_session.SessionRefused as exc:
        raise ViewerError(401, "signed_out", "Sign in to this channel to continue.") from exc


def rename(session: Session, viewer: OttViewer, display_name: str) -> dict[str, Any]:
    name = " ".join(str(display_name or "").split())[:MAX_NAME]
    if not name:
        raise ViewerError(400, "name", "type a name")
    viewer.display_name = name
    session.flush()
    return viewer_view(viewer)


def sign_out_everywhere(session: Session, viewer: OttViewer) -> None:
    viewer.session_version = int(viewer.session_version) + 1
    session.flush()


def _channel_title(session: Session, viewer: OttViewer, title_id: str) -> OttTitle:
    title = session.get(OttTitle, title_id)
    if title is None or title.channel_id != viewer.channel_id:
        raise ViewerError(404, "not_found", "title not found")
    return title


def save_progress(session: Session, viewer: OttViewer, title_id: str, *, position_s: float, duration_s: float,
                  device: str = "web") -> dict[str, Any]:
    title = _channel_title(session, viewer, title_id)
    if device not in DEVICES:
        raise ViewerError(400, "device", f"device is one of {', '.join(DEVICES)}")
    duration = max(0.0, float(duration_s or title.duration_s or 0.0))
    position = max(0.0, float(position_s))
    if duration:
        position = min(position, duration)
    row = session.execute(select(OttWatchProgress).where(OttWatchProgress.viewer_id == viewer.id,
                                                         OttWatchProgress.title_id == title.id)
                          ).scalar_one_or_none()
    if row is None:
        row = OttWatchProgress(viewer_id=viewer.id, title_id=title.id)
        try:
            with session.begin_nested():
                session.add(row)
        except IntegrityError:
            row = session.execute(select(OttWatchProgress).where(OttWatchProgress.viewer_id == viewer.id,
                                                                 OttWatchProgress.title_id == title.id)
                                  ).scalar_one()
    row.position_s, row.duration_s, row.device, row.updated_at = position, duration, device, now()
    session.flush()
    return progress_view(row)


def progress_view(row: OttWatchProgress) -> dict[str, Any]:
    finished = bool(row.duration_s) and row.position_s >= row.duration_s * FINISHED_RATIO
    return {"title_id": row.title_id, "position_s": round(row.position_s, 1), "duration_s": round(row.duration_s, 1),
            "finished": finished, "device": row.device,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def resume_point(session: Session, viewer: OttViewer, title_id: str) -> dict[str, Any]:
    _channel_title(session, viewer, title_id)
    row = session.execute(select(OttWatchProgress).where(OttWatchProgress.viewer_id == viewer.id,
                                                         OttWatchProgress.title_id == title_id)
                          ).scalar_one_or_none()
    if row is None:
        return {"title_id": title_id, "position_s": 0.0, "duration_s": 0.0, "finished": False, "device": None,
                "updated_at": None}
    view = progress_view(row)
    if view["finished"]:
        view["position_s"] = 0.0
    return view


def continue_watching(session: Session, viewer: OttViewer, *, limit: int = CONTINUE_LIMIT) -> list[dict[str, Any]]:
    rows = session.execute(
        select(OttWatchProgress, OttTitle)
        .join(OttTitle, OttTitle.id == OttWatchProgress.title_id)
        .where(OttWatchProgress.viewer_id == viewer.id, OttTitle.channel_id == viewer.channel_id,
               OttTitle.status == STATUS_PUBLISHED)
        .order_by(OttWatchProgress.updated_at.desc())
        .limit(limit * 2)
    ).all()
    out = []
    for progress, title in rows:
        view = progress_view(progress)
        if view["finished"]:
            continue
        out.append({**view, "title": title.title})
        if len(out) >= limit:
            break
    return out


def delete_viewer(session: Session, viewer: OttViewer) -> dict[str, int]:
    """Delete the viewer and their history. Other packages add their own clean-up lines here."""
    history = session.execute(delete(OttWatchProgress).where(OttWatchProgress.viewer_id == viewer.id)).rowcount
    from app.domains.ott_commerce import entitlements  # Wave P PM3.2: purchases end with the account

    ended = entitlements.forget_viewer(session, viewer.id)
    from . import retention  # Wave Q QM1.5: watchlist, ratings and push opt-ins go with the account

    retention.erase(session, viewer.id)
    session.delete(viewer)
    session.flush()
    return {"history_deleted": int(history or 0), "purchases_ended": ended}


__all__ = ["DEVICES", "ViewerError", "continue_watching", "delete_viewer", "progress_view", "published_channel",
           "rename", "resolve", "resume_point", "save_progress", "sign_in", "sign_out_everywhere", "viewer_view"]
