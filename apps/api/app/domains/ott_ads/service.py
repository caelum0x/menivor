"""Ads on channels (MV14): house ads and creator-sold sponsor slots, served as VAST.

Rules:
* One pre-roll per play, **skippable after 5 s**.
* Never on paid titles, and never for a viewer with a live channel
  subscription, unless the creator turned ``ads_on_paid`` on.
* The creator's own sponsor slots come first (active and inside their dates,
  the least-shown first); otherwise one of our house ads when the creator
  allows them. Programmatic demand stays off (OD-MV8): no third-party ad
  server or wrapper is ever called.
* An ad is made from a packaged title (the creator's own for sponsor slots;
  ours for house ads), so its media passes the same compliance gate as any
  title. Counters (impressions, completes, skips, clicks) come only from our
  own tracking URLs, each signed for one play and valid 15 minutes, and each
  (play, ad, event) counts once (Wave Q QM1.0, P-M12).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.ott import catalog_public
from app.domains.ott.models import OttChannel, OttTitle
from app.domains.ott_commerce.models import OttAd, OttAdEvent, OttAdSettings

SKIP_AFTER_S = 5
KIND_HOUSE, KIND_SPONSOR = "house", "sponsor"
EVENTS = ("impression", "start", "firstQuartile", "midpoint", "thirdQuartile", "complete", "skip", "click")
#: A tracking URL lives this long (P-M12: 15 minutes or less).
TRACK_TTL_S = 15 * 60
_PLAY_RE = re.compile(r"[0-9a-f]{16}")
COUNTED = {"impression": "impressions", "complete": "completes", "skip": "skips", "click": "clicks"}


class AdError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def now() -> datetime:
    return datetime.now(timezone.utc)


def settings_for(session: Session, channel_id: str) -> OttAdSettings:
    row = session.get(OttAdSettings, channel_id)
    if row is None:
        row = OttAdSettings(channel_id=channel_id, ads_on_free=True, ads_on_paid=False, house_ads=True)
        session.add(row)
        session.flush()
    return row


def update_settings(session: Session, channel_id: str, body: Mapping[str, Any]) -> OttAdSettings:
    row = settings_for(session, channel_id)
    for field in ("ads_on_free", "ads_on_paid", "house_ads"):
        if body.get(field) is not None:
            setattr(row, field, bool(body[field]))
    session.flush()
    return row


def _in_dates(ad: OttAd, moment: datetime) -> bool:
    def aware(v):
        return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)

    return (ad.starts_at is None or aware(ad.starts_at) <= moment) and (ad.ends_at is None or aware(ad.ends_at) > moment)


def _usable(session: Session, ad: OttAd, playing: OttTitle, moment: datetime) -> bool:
    if not ad.active or not _in_dates(ad, moment) or ad.title_id == playing.id:
        return False
    media = session.get(OttTitle, ad.title_id)
    return (media is not None and media.access_tier == "free" and bool(media.source_key)
            and catalog_public.watchable(session, media, now=moment))


def decide(session: Session, title: OttTitle, *, viewer_account_id: Optional[str] = None,
           at: Optional[datetime] = None) -> Optional[OttAd]:
    """The one pre-roll for this play, or ``None``."""
    from app.domains.ott_commerce import entitlements

    moment = at or now()
    rules = settings_for(session, title.channel_id)
    paid_context = title.access_tier != "free" or bool(
        viewer_account_id and entitlements.subscribed(session, viewer_account_id, title.channel_id))
    if paid_context and not rules.ads_on_paid:
        return None
    if not paid_context and not rules.ads_on_free:
        return None
    sponsor = session.execute(select(OttAd).where(OttAd.channel_id == title.channel_id, OttAd.kind == KIND_SPONSOR,
                                                  OttAd.active.is_(True))
                              .order_by(OttAd.impressions, OttAd.created_at)).scalars().all()
    for ad in sponsor:
        if _usable(session, ad, title, moment):
            return ad
    if not rules.house_ads:
        return None
    house = session.execute(select(OttAd).where(OttAd.channel_id.is_(None), OttAd.kind == KIND_HOUSE,
                                                OttAd.active.is_(True))
                            .order_by(OttAd.impressions, OttAd.created_at)).scalars().all()
    return next((ad for ad in house if _usable(session, ad, title, moment)), None)


# --------------------------------------------------------------------------- #
# Tracking
# --------------------------------------------------------------------------- #
def _key() -> bytes:
    from app.domains.ott_access import tokens

    return hashlib.sha256(b"ott-ads:" + tokens._secret()).digest()


def new_play(at: Optional[float] = None) -> tuple[str, int]:
    """A fresh play id and the expiry (epoch seconds) of the tracking URLs for one VAST answer."""
    return secrets.token_hex(8), int(at if at is not None else time.time()) + TRACK_TTL_S


def track_sig(ad_id: str, event: str, play_id: str, expires: int) -> str:
    """P-M12: the signature covers the ad, the event, the play and the expiry."""
    message = f"{ad_id}:{event}:{play_id}:{int(expires)}".encode()
    digest = hmac.new(_key(), message, hashlib.sha256).digest()[:12]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def track_query(ad_id: str, event: str, play_id: str, expires: int) -> str:
    return f"t={track_sig(ad_id, event, play_id, expires)}&p={play_id}&x={int(expires)}"


def _valid(ad_id: str, event: str, sig: str, play_id: str, expires: Any, at: float) -> bool:
    try:
        expiry = int(expires)
    except (TypeError, ValueError):
        return False
    if event not in EVENTS or not _PLAY_RE.fullmatch(str(play_id or "")):
        return False
    if expiry <= at or expiry > at + TRACK_TTL_S:
        return False
    return hmac.compare_digest(str(sig or ""), track_sig(ad_id, event, play_id, expiry))


def record(session: Session, ad_id: str, event: str, sig: str, play_id: str = "", expires: Any = None,
           *, at: Optional[float] = None) -> bool:
    """Count one tracking hit. A forged, expired or replayed URL records nothing (P-M12).

    Each (play, ad, event) counts once: the unique row in ``ott_ad_events`` is
    the guard, so two concurrent hits of the same URL cannot both count.
    """
    if not _valid(ad_id, event, sig, play_id, expires, at if at is not None else time.time()):
        return False
    column = COUNTED.get(event)
    if column is None:
        return True
    try:
        with session.begin_nested():
            session.add(OttAdEvent(ad_id=ad_id, play_id=play_id, event=event, created_at=now()))
    except IntegrityError:
        return False
    session.execute(update(OttAd).where(OttAd.id == ad_id).values({column: getattr(OttAd, column) + 1}))
    return True


def sweep_events(session: Session, *, now: Optional[datetime] = None) -> int:
    """Drop counted-event rows whose URLs can no longer verify (older than the TTL plus an hour)."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(seconds=TRACK_TTL_S + 3600)
    result = session.execute(delete(OttAdEvent).where(OttAdEvent.created_at < cutoff))
    return int(result.rowcount or 0)


# --------------------------------------------------------------------------- #
# Sponsor slots and house ads
# --------------------------------------------------------------------------- #
def _check_click(url: str) -> str:
    url = str(url or "").strip()
    if url and (not url.startswith("https://") or len(url) > 500):
        raise AdError(400, "click_url", "the sponsor link must be an https address")
    return url


def create_ad(session: Session, *, channel: Optional[OttChannel], body: Mapping[str, Any]) -> OttAd:
    from app.domains.presets_hub.catalog import vendor_hits

    title = session.get(OttTitle, str(body.get("title_id") or ""))
    if title is None or (channel is not None and title.channel_id != channel.id):
        raise AdError(404, "title", "pick one of your published titles for the ad")
    if not catalog_public.watchable(session, title) or title.access_tier != "free":
        raise AdError(400, "title", "the ad video must be a free title that is published and ready to play")
    name = " ".join(str(body.get("name") or "").split())[:80]
    sponsor = " ".join(str(body.get("sponsor") or "").split())[:80]
    if not name:
        raise AdError(400, "name", "give the ad a name")
    if vendor_hits(f"{name} {sponsor}"):
        raise AdError(400, "copy_vendor", "ad names cannot name tools or models")
    ad = OttAd(channel_id=channel.id if channel else None, kind=KIND_SPONSOR if channel else KIND_HOUSE, name=name,
               sponsor=sponsor, title_id=title.id, click_url=_check_click(body.get("click_url")),
               duration_s=float(title.duration_s or 15.0), starts_at=body.get("starts_at"),
               ends_at=body.get("ends_at"), active=True)
    session.add(ad)
    session.flush()
    return ad


def ad_view(ad: OttAd) -> dict[str, Any]:
    return {"id": ad.id, "kind": ad.kind, "name": ad.name, "sponsor": ad.sponsor, "title_id": ad.title_id,
            "click_url": ad.click_url, "active": ad.active, "duration_s": ad.duration_s,
            "starts_at": ad.starts_at.isoformat() if ad.starts_at else None,
            "ends_at": ad.ends_at.isoformat() if ad.ends_at else None,
            "stats": {"impressions": ad.impressions, "completes": ad.completes, "skips": ad.skips,
                      "clicks": ad.clicks}}


def studio_view(session: Session, channel_id: str) -> dict[str, Any]:
    rules = settings_for(session, channel_id)
    ads = session.execute(select(OttAd).where(OttAd.channel_id == channel_id).order_by(OttAd.created_at.desc())
                          ).scalars().all()
    return {"settings": {"ads_on_free": rules.ads_on_free, "ads_on_paid": rules.ads_on_paid,
                         "house_ads": rules.house_ads, "skip_after_s": SKIP_AFTER_S, "programmatic": False},
            "ads": [ad_view(a) for a in ads]}


__all__ = ["AdError", "EVENTS", "KIND_HOUSE", "KIND_SPONSOR", "SKIP_AFTER_S", "TRACK_TTL_S", "ad_view", "create_ad",
           "decide", "new_play", "record", "settings_for", "studio_view", "sweep_events", "track_query", "track_sig",
           "update_settings"]
