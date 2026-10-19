"""Paid-ads use cases: connect, launch from Ad Studio variants, start/pause/archive.

Sync (video processing -> live ads, stats) and the Thompson winner loop live in
:mod:`app.domains.ads.optimizer`. Business failures raise :class:`AdsError`
(status + advertiser-safe message) for the thin HTTP adapter to map.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.domains.ads import bandit, config, connections, store
from app.domains.ads.meta_client import MetaAdsClient
from app.domains.ads.platforms import CTAS, AccountRef, AdsApiError, Audience
from app.domains.ads.tiktok_client import TikTokAdsClient
from app.domains.adstudio import service as adstudio_service
from app.domains.adstudio import views as adstudio_views
from app.domains.adstudio.repository import AdStudioRepository

MAX_CREATIVES = 10
MAX_DAILY_BUDGET_MINOR = 10_000_000  # hard ceiling per campaign per day (100k in a 2-decimal currency)


class AdsError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class LaunchRequest:
    project_id: str
    platform: str
    variant_ids: tuple[str, ...]
    daily_budget_minor: int
    audience: Audience
    name: str = ""
    landing_url: str = ""
    primary_text: str = ""
    headline: str = ""
    cta: str = "SHOP_NOW"
    optimize_for: str = "ctr"
    auto_optimize: bool = True
    start_now: bool = False


def client_for(platform: str) -> Any:
    """The platform client, or AdsError(503) while the app is not approved."""
    cfg = config.platform_config(platform)
    if not cfg.enabled:
        raise AdsError(503, config.NOT_ENABLED_REASON)
    return MetaAdsClient(cfg) if platform == "meta" else TikTokAdsClient(cfg)


def _platform(platform: str) -> str:
    value = (platform or "").strip().lower()
    if value not in config.PLATFORMS:
        raise AdsError(404, "Unknown ads platform")
    return value


def _api(exc: AdsApiError) -> AdsError:
    if exc.status_code == 401:
        return AdsError(409, f"{exc.message}. Reconnect the ad account.")
    return AdsError(exc.status_code if exc.status_code in (400, 403, 409) else 502, exc.message)


def _conn(exc: connections.ConnectionError_) -> AdsError:
    return AdsError(exc.status_code, exc.message)


# ----------------------------------------------------------------- connections
def connect_url(user_id: str, platform: str) -> dict:
    platform = _platform(platform)
    client = client_for(platform)
    state = connections.sign_state(config.platform_config(platform), user_id)
    return {"platform": platform, "authorize_url": client.authorize_url(state)}


def finish_connect(session: Any, user_id: str, platform: str, code: str, state: str) -> dict:
    platform = _platform(platform)
    client = client_for(platform)
    try:
        connections.verify_state(config.platform_config(platform), state, user_id)
        grant = client.exchange_code(code)
        connections.store_grant(session, user_id, platform, grant)
    except connections.ConnectionError_ as exc:
        raise _conn(exc) from exc
    except AdsApiError as exc:
        raise _api(exc) from exc
    return connection_detail(session, user_id, platform)


def connection_detail(session: Any, user_id: str, platform: str) -> dict:
    """Connection state plus the ad accounts / identities the token can use."""
    platform = _platform(platform)
    gate = next(p for p in config.status()["platforms"] if p["platform"] == platform)
    out: dict[str, Any] = {"platform": platform, "enabled": gate["enabled"], "reason": gate["reason"],
                           "connected": False, "accounts": [], "identities": []}
    try:
        conn = connections.load(session, user_id, platform)
    except connections.ConnectionError_ as exc:
        return {**out, "connected": True, "error": exc.message}
    if conn is None:
        return out
    out.update(conn.public())
    if not gate["enabled"]:
        return out
    client = client_for(platform)
    try:
        out["accounts"] = client.list_accounts(conn.token)
        if conn.account and conn.account.account_id:
            out["identities"] = client.list_identities(conn.token, conn.account.account_id)
    except AdsApiError as exc:
        out["error"] = _api(exc).message
    return out


def choose_account(session: Any, user_id: str, platform: str, account_id: str, identity_id: str,
                   currency: str, identity_name: str = "") -> dict:
    platform = _platform(platform)
    client = client_for(platform)
    try:
        conn = connections.load(session, user_id, platform)
        if conn is None:
            raise AdsError(409, "Connect the ad account first.")
        accounts = {a["id"]: a for a in client.list_accounts(conn.token)}
        if account_id not in accounts:
            raise AdsError(400, "That ad account is not available to this connection.")
        if platform == "tiktok" and not identity_id and identity_name:
            identity_id = client.create_identity(conn.token, account_id, identity_name)
        if identity_id:
            known = {i["id"] for i in client.list_identities(conn.token, account_id)}
            if identity_id not in known:
                raise AdsError(400, "That page or identity is not available to this ad account.")
        acct = AccountRef(account_id=account_id, identity_id=identity_id,
                          currency=(accounts[account_id].get("currency") or currency or "USD").upper())
        connections.select_account(session, user_id, platform, acct)
    except connections.ConnectionError_ as exc:
        raise _conn(exc) from exc
    except AdsApiError as exc:
        raise _api(exc) from exc
    return connection_detail(session, user_id, platform)


def disconnect(session: Any, user_id: str, platform: str) -> dict:
    platform = _platform(platform)
    connections.disconnect(session, user_id, platform)
    return {"platform": platform, "connected": False}


# ----------------------------------------------------------------------- launch
def _validate(req: LaunchRequest, min_minor: int) -> None:
    if not 1 <= len(req.variant_ids) <= MAX_CREATIVES:
        raise AdsError(400, f"Pick between 1 and {MAX_CREATIVES} ads.")
    needed = min_minor * len(req.variant_ids)
    if req.daily_budget_minor < needed:
        raise AdsError(400, f"Daily budget must be at least {needed} (minor units) — the platform minimum per ad times {len(req.variant_ids)} ads.")
    if req.daily_budget_minor > MAX_DAILY_BUDGET_MINOR:
        raise AdsError(400, "Daily budget is above the per-campaign limit.")
    if req.cta not in CTAS:
        raise AdsError(400, "Unknown call to action.")
    if req.optimize_for not in ("ctr", "leads"):
        raise AdsError(400, "optimize_for must be ctr or leads.")
    aud = req.audience
    if not aud.countries or not 18 <= aud.age_min <= aud.age_max <= 65:
        raise AdsError(400, "Audience needs at least one country and an age range between 18 and 65.")


def _landing(url: str) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or not parsed.netloc:
        raise AdsError(400, "The landing page must be an https:// URL.")
    return url


def creatives_for(session: Any, user_id: str, project_id: str, variant_ids: tuple[str, ...]) -> tuple[Any, list[tuple[Any, dict]]]:
    """Owned, finished variants with presigned video + poster URLs."""
    repo = AdStudioRepository(session)
    project = repo.get_owned_project(user_id, project_id)
    if project is None:
        raise AdsError(404, "Ad Studio project not found.")
    variants = {v.id: v for v in repo.variants(project.id)}
    picked = [variants.get(vid) for vid in variant_ids]
    if any(v is None for v in picked):
        raise AdsError(404, "One of the selected ads was not found in this project.")
    jobs = adstudio_service.sync_jobs(session, picked)
    r2 = adstudio_views._r2()
    out = []
    for variant in picked:
        view = adstudio_views.variant_view(project, variant, jobs, r2)
        if variant.status != "done" or not view.get("video_url"):
            raise AdsError(409, f"Ad {variant.id} has not finished rendering.")
        out.append((variant, view))
    return project, out


def _copy(project: Any, variant: Any, req: LaunchRequest) -> tuple[str, str]:
    angle = (variant.spec or {}).get("angle") or {}
    primary = req.primary_text or " ".join(p for p in (angle.get("hook"), angle.get("offer"), angle.get("cta")) if p)
    headline = req.headline or str((project.product or {}).get("title") or project.title or "")
    return primary[:2000] or project.title, headline[:255]


def launch(session: Any, user_id: str, req: LaunchRequest) -> tuple[str, list[tuple[Any, dict]]]:
    platform = _platform(req.platform)
    client = client_for(platform)
    cfg = config.platform_config(platform)
    _validate(req, cfg.min_daily_budget_minor)
    try:
        conn = connections.require(session, user_id, platform)
    except connections.ConnectionError_ as exc:
        raise _conn(exc) from exc
    project, creatives = creatives_for(session, user_id, req.project_id, req.variant_ids)
    landing = _landing(req.landing_url or project.source_url)
    key = store.new_key()
    acct = conn.account
    alloc = bandit.allocate([bandit.Arm(v.id) for v, _ in creatives], req.daily_budget_minor,
                            cfg.min_daily_budget_minor, seed=bandit.seed_from_string(key))
    budgets = {a.arm_id: a for a in alloc.arms}
    campaign = {
        "key": key, "platform": platform, "name": (req.name or f"Menivor - {project.title}")[:200],
        "account_id": acct.account_id, "identity_id": acct.identity_id, "currency": acct.currency,
        "daily_budget_minor": req.daily_budget_minor, "audience": req.audience.to_record(),
        "optimize_for": req.optimize_for, "auto_optimize": req.auto_optimize, "landing_url": landing,
        "cta": req.cta, "status": store.STATUS_PAUSED, "external_id": "", "created_at": store.now_iso(),
        "project_id": project.id, "allocation": alloc.to_record(),
    }
    rows: list[tuple[Any, dict]] = []
    failure: AdsApiError | None = None
    try:
        campaign["external_id"] = client.create_campaign(conn.token, acct, campaign["name"])
        for order, (variant, view) in enumerate(creatives):
            primary, headline = _copy(project, variant, req)
            arm = budgets[variant.id]
            item = {"order": order, "campaign": campaign, "phase": store.PHASE_UPLOADING, "budget_minor": arm.budget_minor,
                    "active": arm.active, "p_best": round(arm.p_best, 4), "alloc_reason": arm.reason,
                    "primary_text": primary, "headline": headline, "poster_url": view.get("poster_url") or "",
                    "stats": {}, "error": ""}
            rows.append((variant, item))
            item["ad_group_id"] = client.create_ad_group(
                conn.token, acct, campaign["external_id"], f"{campaign['name']} / {variant.id[:8]}",
                max(arm.budget_minor, cfg.min_daily_budget_minor), req.audience)
            item["video_id"] = client.upload_video(conn.token, acct, view["video_url"], view.get("filename") or variant.id)
            item["phase"] = store.PHASE_PROCESSING
            if not arm.active:
                client.set_ad_group_status(conn.token, acct, item["ad_group_id"], False)
        if req.start_now:
            client.set_campaign_status(conn.token, acct, campaign["external_id"], True)
            campaign["status"] = store.STATUS_ACTIVE
    except AdsApiError as exc:
        failure = exc
        campaign["status"] = store.STATUS_ERROR
        campaign["error"] = exc.message
        if rows:
            rows[-1][1]["error"] = exc.message
    if campaign["external_id"]:
        for variant, item in rows:
            store.write(variant, key, {**item, "campaign": campaign})
        session.flush()
    if failure is not None:
        raise AdsError(_api(failure).status_code,
                       f"{failure.message} (partial campaign kept so you can retry or archive it)"
                       if campaign["external_id"] else failure.message)
    return key, store.campaign_rows(session, user_id, key)


# ---------------------------------------------------------------- lifecycle
def _rows(session: Any, user_id: str, key: str) -> list[tuple[Any, dict]]:
    rows = store.campaign_rows(session, user_id, key)
    if not rows:
        raise AdsError(404, "Campaign not found.")
    return rows


def context(session: Any, user_id: str, key: str) -> tuple[list[tuple[Any, dict]], dict, Any, Any]:
    rows = _rows(session, user_id, key)
    camp = rows[0][1]["campaign"]
    client = client_for(camp["platform"])
    try:
        conn = connections.load(session, user_id, camp["platform"])
    except connections.ConnectionError_ as exc:
        raise _conn(exc) from exc
    if conn is None:
        raise AdsError(409, "Reconnect the ad account that owns this campaign.")
    acct = AccountRef(account_id=camp["account_id"], identity_id=camp.get("identity_id", ""), currency=camp.get("currency", "USD"))
    if conn.account is None or conn.account.account_id != acct.account_id:
        raise AdsError(409, "This campaign belongs to a different ad account than the one connected.")
    return rows, camp, client, (conn.token, acct)


def set_status(session: Any, user_id: str, key: str, active: bool) -> list[tuple[Any, dict]]:
    rows, camp, client, (token, acct) = context(session, user_id, key)
    if camp.get("status") == store.STATUS_ARCHIVED:
        raise AdsError(409, "Archived campaigns cannot be restarted.")
    if active and not any(i.get("phase") == store.PHASE_LIVE for _, i in rows):
        raise AdsError(409, "No ad is live yet. Sync after the platform finishes processing the videos.")
    try:
        client.set_campaign_status(token, acct, camp["external_id"], active)
    except AdsApiError as exc:
        raise _api(exc) from exc
    rows = store.update_campaign(rows, key, status=store.STATUS_ACTIVE if active else store.STATUS_PAUSED, error="")
    session.flush()
    return rows


def archive(session: Any, user_id: str, key: str) -> list[tuple[Any, dict]]:
    """Pause on the platform (spend stops) and hide from the active list."""
    rows, camp, client, (token, acct) = context(session, user_id, key)
    try:
        client.set_campaign_status(token, acct, camp["external_id"], False)
    except AdsApiError as exc:
        raise _api(exc) from exc
    rows = store.update_campaign(rows, key, status=store.STATUS_ARCHIVED)
    session.flush()
    return rows


__all__ = ["AdsError", "LaunchRequest", "archive", "choose_account", "client_for", "connect_url", "connection_detail",
           "context", "creatives_for", "disconnect", "finish_connect", "launch", "set_status"]
