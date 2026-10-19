"""Channel team roles (Wave P PM3.5): who besides the owner may see or change a channel.

* ``owner``   the creator who owns the channel (always, no row needed)
* ``editor``  titles, AI panel, live and linear
* ``analyst`` analytics only

Members are added by the owner by email. The seat is stored as an invite
whether or not that email has a Menivor account yet (the answer is the same
either way, P-M15), and applies when an account with that email signs in.
Rows in ``ott_channel_members`` from before Wave Q keep working.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.db.base import Base

from .models import OttChannel

ROLES = ("editor", "analyst")
_EMAIL_RE = re.compile(r"[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{1,60}")
ACTIONS: dict[str, tuple[str, ...]] = {
    "view_analytics": ("owner", "editor", "analyst"),
    "use_ai": ("owner", "editor"),
    "edit_titles": ("owner", "editor"),
    "manage_team": ("owner",),
}


class RoleError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class OttChannelMember(Base):
    __tablename__ = "ott_channel_members"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("channel_id", "user_id", name="uq_ott_channel_members"),)


class OttChannelInvite(Base):
    """A team seat by email (Wave Q QM1.0, P-M15); migration d1a3c5e7f9b2.

    Adding a member always stores an invite, whether or not a Menivor account
    with that email exists, so the answer never tells the owner which emails
    have accounts. The seat applies as soon as an account with that email
    signs in.
    """

    __tablename__ = "ott_channel_invites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("channel_id", "email", name="uq_ott_channel_invites"),)


def _email(value: object) -> str:
    return str(value or "").strip().lower()


def _user_email(session: Session, user_id: str) -> str:
    from app.models.db.models import User

    user = session.get(User, user_id)
    return _email(getattr(user, "email", ""))


def role_of(session: Session, user_id: str, channel: OttChannel) -> Optional[str]:
    if str(channel.user_id) == str(user_id):
        return "owner"
    row = session.execute(select(OttChannelMember).where(OttChannelMember.channel_id == channel.id,
                                                         OttChannelMember.user_id == user_id)).scalar_one_or_none()
    if row is not None:
        return row.role
    email = _user_email(session, user_id)
    if not email:
        return None
    invite = session.execute(select(OttChannelInvite).where(OttChannelInvite.channel_id == channel.id,
                                                            OttChannelInvite.email == email)).scalar_one_or_none()
    return invite.role if invite else None


def can(session: Session, user_id: str, channel: OttChannel, action: str) -> bool:
    return role_of(session, user_id, channel) in ACTIONS[action]


def channels_for(session: Session, user_id: str, action: str) -> list[OttChannel]:
    """Channels this user may act on (their own first)."""
    allowed = [r for r in ACTIONS[action] if r != "owner"]
    own = session.execute(select(OttChannel).where(OttChannel.user_id == user_id)).scalars().all()
    shared = list(session.execute(select(OttChannel).join(OttChannelMember, OttChannelMember.channel_id == OttChannel.id)
                                  .where(OttChannelMember.user_id == user_id, OttChannelMember.role.in_(allowed))
                                  ).scalars().all())
    email = _user_email(session, user_id)
    if email:
        shared += session.execute(select(OttChannel).join(OttChannelInvite, OttChannelInvite.channel_id == OttChannel.id)
                                  .where(OttChannelInvite.email == email, OttChannelInvite.role.in_(allowed))
                                  ).scalars().all()
    out = list(own)
    for channel in shared:
        if channel not in out:
            out.append(channel)
    return out


def require(session: Session, user_id: str, channel: OttChannel, action: str) -> None:
    if not can(session, user_id, channel, action):
        raise RoleError(403, "role", "You do not have access to this on the channel.")


def add_member(session: Session, channel: OttChannel, *, email: str, role: str) -> dict:
    """Give ``email`` a seat. The answer is the same whether or not that email has an account (P-M15)."""
    if role not in ROLES:
        raise RoleError(400, "role", f"role is one of {', '.join(ROLES)}")
    address = _email(email)
    if not _EMAIL_RE.fullmatch(address):
        raise RoleError(400, "email", "Enter an email address.")
    if address == _user_email(session, str(channel.user_id)):
        raise RoleError(400, "owner", "That is the channel owner.")
    invite = session.execute(select(OttChannelInvite).where(OttChannelInvite.channel_id == channel.id,
                                                            OttChannelInvite.email == address)).scalar_one_or_none()
    if invite is None:
        invite = OttChannelInvite(channel_id=channel.id, email=address, role=role)
        session.add(invite)
    invite.role = role
    # QM verify: a pre-Wave-Q direct member row wins in role_of() and team(), so a role
    # change must reach it too (same answer either way, so nothing leaks about accounts).
    from app.models.db.models import User

    for member in session.execute(select(OttChannelMember).join(User, User.id == OttChannelMember.user_id)
                                  .where(OttChannelMember.channel_id == channel.id,
                                         func.lower(User.email) == address)).scalars():
        member.role = role
    session.flush()
    return {"email": address, "role": role}


def remove_member(session: Session, channel: OttChannel, member_id: str) -> None:
    from app.models.db.models import User

    row = session.get(OttChannelMember, member_id)
    invite = session.get(OttChannelInvite, member_id)
    if row is not None and row.channel_id == channel.id:
        user = session.get(User, row.user_id)
        address = _email(getattr(user, "email", ""))
        session.delete(row)
    elif invite is not None and invite.channel_id == channel.id:
        address = invite.email
    else:
        raise RoleError(404, "not_found", "member not found")
    # The seat goes with every row for that person: the direct member row and the invite.
    for other in session.execute(select(OttChannelInvite).where(OttChannelInvite.channel_id == channel.id,
                                                                OttChannelInvite.email == address)).scalars():
        session.delete(other)
    for other in session.execute(select(OttChannelMember).join(User, User.id == OttChannelMember.user_id)
                                 .where(OttChannelMember.channel_id == channel.id,
                                        func.lower(User.email) == address)).scalars():
        session.delete(other)
    session.flush()


def team(session: Session, channel: OttChannel) -> list[dict]:
    """Everyone with a seat, by email. Nothing here says whether an email has an account."""
    from app.models.db.models import User

    rows = session.execute(select(OttChannelMember, User).join(User, User.id == OttChannelMember.user_id)
                           .where(OttChannelMember.channel_id == channel.id)).all()
    out = {_email(u.email): {"id": m.id, "email": _email(u.email), "role": m.role} for m, u in rows}
    invites = session.execute(select(OttChannelInvite).where(OttChannelInvite.channel_id == channel.id)
                              .order_by(OttChannelInvite.created_at)).scalars().all()
    for invite in invites:
        out.setdefault(invite.email, {"id": invite.id, "email": invite.email, "role": invite.role})
    return list(out.values())


__all__ = ["ACTIONS", "OttChannelInvite", "OttChannelMember", "ROLES", "RoleError", "add_member", "can", "channels_for", "remove_member",
           "require", "role_of", "team"]
