"""Channel definitions for the unattended channel runner (Clipfarm).

A *channel* is a creator-owned, named runner configuration: the render matrix
(hooks / aspects / accounts / template / voice), the cross-post platforms, the
inline source list the runner expands into clips, and two switches —
``autorun`` (the hourly beat renders new source items) and ``active``.

Storage reuses the existing ``channel_runs`` table (no schema change): a
definition is a ``ChannelRun`` row whose ``params["kind"] == "channel"`` and
whose ``channel_id`` is the channel's own id. Runner passes for the channel are
ordinary ``ChannelRun`` rows under the same ``channel_id``; history listings
filter definitions out via :func:`is_definition`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.models.db.series_runs import ChannelRun

DEFINITION_KIND = "channel"
_CONFIG_KEYS = (
    "hooks",
    "aspects",
    "accounts",
    "platforms",
    "subject",
    "voice_id",
    "template_slug",
    "max_words",
    "max_per_account",
)
_MAX_SCAN = 500


class ChannelError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def is_definition(row: Any) -> bool:
    params = getattr(row, "params", None)
    return isinstance(params, dict) and params.get("kind") == DEFINITION_KIND


def channel_view(row: ChannelRun) -> dict:
    params = dict(row.params or {})
    created = getattr(row, "created_at", None)
    return {
        "channel_id": row.channel_id,
        "name": params.get("name", ""),
        "active": bool(params.get("active", True)),
        "autorun": bool(params.get("autorun", False)),
        "config": dict(params.get("config") or {}),
        "source_items": list(params.get("source_items") or []),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else None,
    }


def _clean_config(config: dict) -> dict:
    return {k: config[k] for k in _CONFIG_KEYS if k in config and config[k] not in (None, "", [])}


def create_channel(
    session: Any,
    *,
    user_id: str,
    name: str,
    config: dict,
    source_items: list[dict],
    autorun: bool,
) -> ChannelRun:
    name = (name or "").strip()
    if not name:
        raise ChannelError(400, "channel name is required")
    row = ChannelRun(
        user_id=user_id,
        channel_id=uuid.uuid4().hex,
        params={
            "kind": DEFINITION_KIND,
            "name": name[:120],
            "active": True,
            "autorun": bool(autorun),
            "config": _clean_config(config),
            "source_items": list(source_items or []),
        },
    )
    session.add(row)
    session.flush()
    return row


def get_definition(session: Any, channel_id: str) -> ChannelRun | None:
    stmt = select(ChannelRun).where(ChannelRun.channel_id == (channel_id or "").strip())
    for row in session.execute(stmt).scalars().all():
        if is_definition(row):
            return row
    return None


def get_owned(session: Any, channel_id: str, user_id: str) -> ChannelRun:
    row = get_definition(session, channel_id)
    if row is None or str(row.user_id) != str(user_id) or not row.params.get("active", True):
        raise ChannelError(404, "channel not found")
    return row


def assert_channel_access(session: Any, channel_id: str, user_id: str) -> None:
    """Deny access to a channel id that belongs to someone else (404).

    Defined channels must be owned by the caller; an ad-hoc channel id (no
    definition) is only reachable by the user whose runs created it.
    """
    stmt = select(ChannelRun.user_id).where(
        ChannelRun.channel_id == (channel_id or "").strip()
    )
    owners = {str(uid) for uid in session.execute(stmt).scalars().all()}
    if owners and owners != {str(user_id)}:
        raise ChannelError(404, "channel not found")


def list_owned(session: Any, user_id: str) -> list[ChannelRun]:
    stmt = (
        select(ChannelRun)
        .where(ChannelRun.user_id == user_id)
        .order_by(ChannelRun.created_at.desc())
        .limit(_MAX_SCAN)
    )
    return [
        row
        for row in session.execute(stmt).scalars().all()
        if is_definition(row) and row.params.get("active", True)
    ]


def update_channel(
    session: Any,
    row: ChannelRun,
    *,
    name: str | None = None,
    config: dict | None = None,
    source_items: list[dict] | None = None,
    autorun: bool | None = None,
) -> ChannelRun:
    params = dict(row.params or {})
    if name is not None:
        if not name.strip():
            raise ChannelError(400, "channel name cannot be blank")
        params["name"] = name.strip()[:120]
    if config is not None:
        params["config"] = {**dict(params.get("config") or {}), **_clean_config(config)}
    if source_items is not None:
        params["source_items"] = list(source_items)
    if autorun is not None:
        params["autorun"] = bool(autorun)
    row.params = params  # replace-on-edit so the JSON change is detected
    session.flush()
    return row


def archive_channel(session: Any, row: ChannelRun) -> None:
    row.params = {**dict(row.params or {}), "active": False, "autorun": False}
    session.flush()


def autorun_payload(session: Any) -> list[dict]:
    """Beat payload channels: every active definition with ``autorun`` on."""
    stmt = select(ChannelRun).order_by(ChannelRun.created_at.asc())
    channels: list[dict] = []
    for row in session.execute(stmt).scalars().all():
        if not is_definition(row):
            continue
        params = row.params or {}
        if not params.get("active", True) or not params.get("autorun", False):
            continue
        channels.append(
            {
                **dict(params.get("config") or {}),
                "channel_id": row.channel_id,
                "user_id": row.user_id,
                "source_items": list(params.get("source_items") or []),
            }
        )
    return channels
