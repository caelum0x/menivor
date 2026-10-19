"""Competitor tracker: tracked brands, refresh from official ad libraries, winners, alerts, clone.

Nothing here scrapes or logs in anywhere: every ad comes from the Meta Ad Library
API or the TikTok Commercial Content API (see :mod:`.sources`). A source without
keys is reported as not connected with the owner step; the other source still runs.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from loguru import logger
from sqlalchemy import func, select, update

from app.domains.adstudio.extract import clean_text
from app.domains.competitors import longevity
from app.domains.competitors.models import CompetitorAd, CompetitorBrand
from app.domains.competitors.sources import SourceError, SourceNotConnected, TrackedAd
from app.domains.competitors.sources import meta_ad_library as meta
from app.domains.competitors.sources import tiktok_commercial as tiktok

MAX_BRANDS = 25
MAX_IDS = 10
MAX_ADS_PER_BRAND = 500
REFRESH_EVERY = timedelta(hours=20)
_COUNTRY = re.compile(r"^[A-Z]{2}$")


class CompetitorError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def sources_status(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    e = None if env is None else dict(env)
    return [
        {"id": meta.SOURCE, "name": "Meta Ad Library", "connected": meta.configured(e),
         "detail": "Official Ad Library API (ads shown in the EU)." if meta.configured(e) else meta.SETUP_STEP},
        {"id": tiktok.SOURCE, "name": "TikTok ad library", "connected": tiktok.configured(e),
         "detail": "Official Commercial Content API." if tiktok.configured(e) else tiktok.SETUP_STEP},
    ]


# --------------------------------------------------------------------------- brands
def _ids(values: Any) -> list[str]:
    out = []
    for v in values or []:
        text = re.sub(r"\D", "", str(v or ""))
        if text and text not in out:
            out.append(text[:32])
    return out[:MAX_IDS]


def _countries(values: Any) -> list[str]:
    out = [str(v or "").strip().upper() for v in values or []]
    return [c for c in out if _COUNTRY.match(c)][:20] or list(meta.DEFAULT_COUNTRIES)


def brand_view(session: Any, row: CompetitorBrand, now: datetime | None = None) -> dict[str, Any]:
    ads = session.execute(select(CompetitorAd).where(CompetitorAd.brand_id == row.id)).scalars().all()
    marks = longevity.annotate(ads, now or _now())
    return {
        "id": row.id, "name": row.name, "space_id": row.space_id, "meta_page_ids": list(row.meta_page_ids or []),
        "tiktok_advertiser_ids": list(row.tiktok_advertiser_ids or []), "search_terms": row.search_terms,
        "countries": list(row.countries or []), "last_checked_at": _iso(row.last_checked_at),
        "last_error": row.last_error or "", "ads": len(ads), "active": sum(1 for a in ads if a.active),
        "new": sum(1 for a in ads if a.is_new), "winners": sum(1 for m in marks if m["tier"] == "winner"),
    }


def add_brand(session: Any, user_id: str, *, name: str, meta_page_ids: Any = None, tiktok_advertiser_ids: Any = None,
              search_terms: str = "", countries: Any = None, space_id: str | None = None,
              workspace_id: str | None = None) -> dict[str, Any]:
    title = clean_text(name, 200)
    if not title:
        raise CompetitorError("Name the brand you want to track.", 422)
    page_ids, advertiser_ids = _ids(meta_page_ids), _ids(tiktok_advertiser_ids)
    terms = clean_text(search_terms, 100)
    if not (page_ids or advertiser_ids or terms):
        raise CompetitorError("Add a Facebook page id, a TikTok advertiser id or search words.", 422)
    count = session.execute(select(func.count()).select_from(CompetitorBrand)
                            .where(CompetitorBrand.user_id == user_id)).scalar() or 0
    if count >= MAX_BRANDS:
        raise CompetitorError(f"You can track up to {MAX_BRANDS} brands.")
    row = CompetitorBrand(user_id=user_id, workspace_id=workspace_id, space_id=space_id, name=title,
                          meta_page_ids=page_ids, tiktok_advertiser_ids=advertiser_ids, search_terms=terms,
                          countries=_countries(countries))
    session.add(row)
    session.flush()
    return brand_view(session, row)


def _brand(session: Any, user_id: str, brand_id: str) -> CompetitorBrand:
    row = session.get(CompetitorBrand, brand_id) if brand_id else None
    if row is None or row.user_id != user_id:
        raise CompetitorError("tracked brand not found", 404)
    return row


def list_brands(session: Any, user_id: str) -> list[dict[str, Any]]:
    rows = session.execute(select(CompetitorBrand).where(CompetitorBrand.user_id == user_id)
                           .order_by(CompetitorBrand.created_at)).scalars().all()
    return [brand_view(session, r) for r in rows]


def delete_brand(session: Any, user_id: str, brand_id: str) -> None:
    row = _brand(session, user_id, brand_id)
    session.execute(CompetitorAd.__table__.delete().where(CompetitorAd.brand_id == row.id))
    session.delete(row)
    session.flush()


# --------------------------------------------------------------------------- refresh
def _upsert(session: Any, brand: CompetitorBrand, ads: list[TrackedAd], *, baseline: bool, now: datetime) -> dict:
    existing = {(a.source, a.external_id): a for a in session.execute(
        select(CompetitorAd).where(CompetitorAd.brand_id == brand.id)).scalars()}
    added = updated = 0
    for ad in ads:
        row = existing.get((ad.source, ad.external_id))
        if row is None:
            if len(existing) >= MAX_ADS_PER_BRAND:
                continue
            row = CompetitorAd(brand_id=brand.id, user_id=brand.user_id, source=ad.source,
                               external_id=ad.external_id, is_new=not baseline, first_seen_at=now)
            session.add(row)
            existing[(ad.source, ad.external_id)] = row
            added += 1
        else:
            updated += 1
        row.advertiser, row.body, row.title = ad.advertiser, ad.body, ad.title
        row.page_url, row.media_url, row.thumbnail_url = ad.page_url, ad.media_url, ad.thumbnail_url
        row.platforms, row.languages, row.raw = list(ad.platforms), list(ad.languages), dict(ad.raw)
        row.started_at, row.stopped_at, row.active = ad.started_at, ad.stopped_at, ad.active
        row.last_seen_at = now
    session.flush()
    return {"added": added, "updated": updated, "new": 0 if baseline else added}


def refresh(session: Any, user_id: str, brand_id: str, *, transport: Any = None,
            env: Mapping[str, str] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Pull both official libraries for one brand. The first pull is the baseline (no alerts)."""
    from app.domains.integrations.connectors.base import RequestsTransport

    brand = _brand(session, user_id, brand_id)
    moment = now or _now()
    http = transport or RequestsTransport()
    e = None if env is None else dict(env)
    statuses: dict[str, str] = {}
    pulled: list[TrackedAd] = []
    jobs: list[tuple[str, Callable[[], list[TrackedAd]], bool]] = [
        (meta.SOURCE, lambda: meta.fetch(http, page_ids=list(brand.meta_page_ids or []),
                                         search_terms=brand.search_terms, countries=list(brand.countries or []),
                                         env=e), bool(brand.meta_page_ids or brand.search_terms)),
        (tiktok.SOURCE, lambda: tiktok.fetch(http, advertiser_ids=list(brand.tiktok_advertiser_ids or []),
                                             search_terms=brand.search_terms, countries=list(brand.countries or []),
                                             env=e, today=moment.date()),
         bool(brand.tiktok_advertiser_ids or brand.search_terms)),
    ]
    for name, call, wanted in jobs:
        if not wanted:
            statuses[name] = "skipped"
            continue
        try:
            pulled.extend(call())
            statuses[name] = "ok"
        except SourceNotConnected as exc:
            statuses[name] = f"not_connected: {exc.message}"
        except SourceError as exc:
            statuses[name] = f"error: {exc.message}"
            logger.warning(f"competitor refresh {brand.id} {name} failed: {exc.message}")
    counts = _upsert(session, brand, pulled, baseline=brand.last_checked_at is None, now=moment)
    errors = [v.split(": ", 1)[1] for v in statuses.values() if v.startswith("error")]
    if any(v == "ok" for v in statuses.values()):
        brand.last_checked_at = moment
    brand.last_error = "; ".join(errors)[:1000]
    session.flush()
    return {**counts, "sources": statuses, "brand": brand_view(session, brand, moment)}


def refresh_due(session: Any, *, now: datetime | None = None, transport: Any = None, limit: int = 100) -> int:
    """Beat: refresh every brand not checked in the last ~day. One failing brand never stops the tick."""
    moment = now or _now()
    cutoff = moment - REFRESH_EVERY
    rows = session.execute(select(CompetitorBrand).where(
        (CompetitorBrand.last_checked_at.is_(None)) | (CompetitorBrand.last_checked_at < cutoff))
        .order_by(CompetitorBrand.created_at).limit(limit)).scalars().all()
    done = 0
    for row in rows:
        try:
            refresh(session, row.user_id, row.id, transport=transport, now=moment)
            done += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"competitor refresh tick: brand {row.id} failed: {type(exc).__name__}")
    return done


# --------------------------------------------------------------------------- read
def ad_view(row: CompetitorAd, mark: dict[str, Any], brand_name: str = "") -> dict[str, Any]:
    return {
        "id": row.id, "brand_id": row.brand_id, "brand_name": brand_name, "source": row.source,
        "external_id": row.external_id, "advertiser": row.advertiser, "body": row.body, "title": row.title,
        "page_url": row.page_url, "media_url": row.media_url, "thumbnail_url": row.thumbnail_url,
        "platforms": list(row.platforms or []), "languages": list(row.languages or []),
        "started_at": _iso(row.started_at), "stopped_at": _iso(row.stopped_at), "active": bool(row.active),
        "is_new": bool(row.is_new), "first_seen_at": _iso(row.first_seen_at), **mark,
        "can_clone": bool(row.body or row.title or row.media_url),
    }


def list_ads(session: Any, user_id: str, *, brand_id: str | None = None, tier: str | None = None,
             only_new: bool = False, now: datetime | None = None, limit: int = 200) -> list[dict[str, Any]]:
    stmt = select(CompetitorAd).where(CompetitorAd.user_id == user_id)
    if brand_id:
        stmt = stmt.where(CompetitorAd.brand_id == _brand(session, user_id, brand_id).id)
    rows = session.execute(stmt).scalars().all()
    names = {b.id: b.name for b in session.execute(
        select(CompetitorBrand).where(CompetitorBrand.user_id == user_id)).scalars()}
    out = []
    for brand in {r.brand_id for r in rows}:  # longevity "scaled" is per brand
        group = [r for r in rows if r.brand_id == brand]
        out.extend(ad_view(r, m, names.get(brand, "")) for r, m in zip(group, longevity.annotate(group, now or _now())))
    if tier:
        out = [a for a in out if a["tier"] == tier]
    if only_new:
        out = [a for a in out if a["is_new"]]
    out.sort(key=lambda a: (not a["is_new"], *longevity.rank_key(a)) if only_new else longevity.rank_key(a))
    return out[:max(1, min(limit, 500))]


def alerts(session: Any, user_id: str, now: datetime | None = None) -> dict[str, Any]:
    items = list_ads(session, user_id, only_new=True, now=now, limit=100)
    return {"count": len(items), "items": items}


def dismiss_alerts(session: Any, user_id: str, ad_ids: list[str] | None = None) -> int:
    stmt = update(CompetitorAd).where(CompetitorAd.user_id == user_id, CompetitorAd.is_new.is_(True))
    if ad_ids:
        stmt = stmt.where(CompetitorAd.id.in_([str(i)[:32] for i in ad_ids]))
    count = session.execute(stmt.values(is_new=False).execution_options(synchronize_session=False)).rowcount
    session.flush()
    return int(count or 0)


# --------------------------------------------------------------------------- clone
def clone_brief(session: Any, user_id: str, ad_id: str, *, downloader: Any = None, observer: Any = None,
                space_id: str | None = None) -> dict[str, Any]:
    """Send a tracked ad into Ad Clone: a clone brief (step 1 done) + an Inspiration. $0."""
    from app.domains.adclone import tracked_source
    from app.domains.adclone.service import AdCloneError

    row = session.get(CompetitorAd, ad_id) if ad_id else None
    if row is None or row.user_id != user_id:
        raise CompetitorError("ad not found", 404)
    try:
        if row.media_url and tracked_source.allowed_media(row.media_url):
            brief = tracked_source.brief_from_media(row.media_url, page_url=row.page_url, platform=row.source,
                                                    source_ref=f"{row.source}:{row.external_id}",
                                                    advertiser=row.advertiser, downloader=downloader,
                                                    observer=observer)
        else:
            brief = tracked_source.brief_from_copy(url=row.page_url, platform=row.source,
                                                   source_ref=f"{row.source}:{row.external_id}",
                                                   advertiser=row.advertiser, body=row.body, title=row.title,
                                                   language=(row.languages or ["en"])[0])
    except AdCloneError as exc:
        raise CompetitorError(exc.message, exc.status_code) from exc
    inspiration = _save_inspiration(session, user_id, row, space_id)
    return {"brief": brief.model_dump(), "inspiration": inspiration, "ad_clone_path": "/ad-clone?from=tracked",
            "source_url": row.page_url}


def _save_inspiration(session: Any, user_id: str, row: CompetitorAd, space_id: str | None) -> dict | None:
    from app.domains.brand_agent import inspirations, spaces

    if not row.page_url:
        return None
    try:
        space = spaces.resolve(session, user_id, space_id)
        mark = longevity.annotate([row], _now())[0]
        return inspirations.add(session, user_id, space.id, row.page_url, title=f"{row.advertiser}: {row.title or row.body}"[:300],
                                source="competitor", thumbnail_url=row.thumbnail_url,
                                metrics={"days_running": mark["days_running"], "tier": mark["tier"]})
    except Exception as exc:  # noqa: BLE001 - saving the inspiration never blocks the clone
        logger.warning(f"competitor clone: inspiration not saved: {type(exc).__name__}")
        return None


__all__ = ["CompetitorError", "add_brand", "alerts", "clone_brief", "delete_brand", "dismiss_alerts", "list_ads",
           "list_brands", "refresh", "refresh_due", "sources_status"]
