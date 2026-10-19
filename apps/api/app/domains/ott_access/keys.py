"""The tier-1 key server (MV5): releases a title's AES-128 key only to a valid playback token."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.ott_transcode.keys import KeyUnavailable, read_key, version

from . import tokens


class KeyRefused(Exception):
    pass


def release(session: Session, title_id: str, token: str, kv: str | int | None = None) -> bytes:
    """The key for a valid token. ``kv`` is the key version the playlist names (QM1.2, P-M7):
    a playlist from before the last rotation is refused. Playlists without ``kv`` predate
    versions and are accepted only while the key is still version 1."""
    try:
        tokens.verify(token, title_id=title_id)
    except tokens.TokenError as exc:
        raise KeyRefused(str(exc)) from exc
    try:
        key = read_key(session, title_id)
    except KeyUnavailable as exc:
        raise KeyRefused("keys are not configured") from exc
    if key is None:
        raise KeyRefused("no key for this title")
    try:
        wanted = int(kv) if kv not in (None, "") else 1
    except (TypeError, ValueError):
        raise KeyRefused("stale key version") from None
    if wanted != version(session, title_id):
        raise KeyRefused("stale key version")
    return key


__all__ = ["KeyRefused", "release"]
