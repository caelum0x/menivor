"""SEO (Menivor Growth): connect a workspace's OpenSEO account, pull a basic
site audit, research keywords for their niche, and track a handful of target
keywords' rank -- surfaced in the Menivor dashboard.

Every OpenSEO research/audit/rank-tracking call spends the *customer's own*
OpenSEO credits. Nothing here runs automatically: every credit-spending call
is one explicit, rate-limited, customer-triggered HTTP request (see
``router.py``); nothing is batched or scheduled by Menivor itself. Reads of
already-cached rows never touch the network.

Reuses ``app.domains.integrations.scope`` (workspace/brand resolution) and the
same bring-your-own-credential storage pattern as ``app.domains.integrations``
(tokens encrypted with :mod:`app.services.crypto_tokens`, never returned).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from app.domains.integrations.scope import Scope
from app.domains.seo import openseo_client as oseo
from app.domains.seo.errors import SeoError
from app.domains.seo.models import (
    AUDIT_COMPLETED, AUDIT_FAILED, AUDIT_RUNNING, STATUS_CONNECTED, STATUS_REAUTH, SeoAuditRun, SeoConnection,
    SeoKeywordResearch, SeoRankKeyword, SeoRankSnapshot,
)
from app.services import crypto_tokens

MAX_TRACKED_KEYWORDS = 10
MAX_RESEARCH_SEEDS = 10
MAX_RESEARCH_HISTORY = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hint(key: str) -> str:
    return f"{key[:8]}...{key[-2:]}" if len(key) > 12 else "..."


def _encrypt(value: str) -> str:
    try:
        return crypto_tokens.encrypt(value)
    except crypto_tokens.MissingTokenKeyError as exc:
        raise SeoError(503, "Token encryption is not configured on this server.") from exc


def _decrypt(conn: SeoConnection) -> str:
    try:
        return crypto_tokens.decrypt(conn.api_key_enc)
    except crypto_tokens.TokenCryptoError as exc:
        raise SeoError(409, "The stored OpenSEO key can no longer be read. Reconnect it.") from exc


def _mapped(exc: oseo.OpenSeoError) -> SeoError:
    return SeoError(exc.status_code if exc.status_code in (400, 401, 422) else 502, exc.message)


def _connection(session: Any, owner_scope: str) -> SeoConnection | None:
    return session.execute(select(SeoConnection).where(SeoConnection.owner_scope == owner_scope)).scalar_one_or_none()


def get_connection(session: Any, scope: Scope) -> SeoConnection:
    conn = _connection(session, scope.owner_scope)
    if conn is None:
        raise SeoError(404, "Connect an OpenSEO account first.")
    if conn.status == STATUS_REAUTH:
        raise SeoError(409, "Reconnect OpenSEO to keep pulling data.")
    return conn


def _call(conn: SeoConnection, transport: Any, tool: str, arguments: dict) -> Any:
    try:
        return oseo.call_tool(transport, _decrypt(conn), tool, arguments)
    except oseo.OpenSeoError as exc:
        if exc.status_code == 401:
            conn.status = STATUS_REAUTH
            conn.last_error = exc.message[:1000]
        raise _mapped(exc) from exc


# --------------------------------------------------------------------------- #
# Connect / disconnect
# --------------------------------------------------------------------------- #
def connect(session: Any, scope: Scope, api_key: str, *, domain: str = "", transport: Any) -> dict:
    """Validate the key with a free (no-credit) ``list_projects`` call, then store it."""
    scope.require_manage()
    key = (api_key or "").strip()
    if not (8 <= len(key) <= 300):
        raise SeoError(422, "Paste the full OpenSEO API key.")
    projects = _call_unbound(transport, key, "list_projects", {})
    project_id = _pick_project(projects, domain)
    conn = _connection(session, scope.owner_scope)
    if conn is None:
        conn = SeoConnection(owner_scope=scope.owner_scope, user_id=scope.user_id, api_key_enc="")
        session.add(conn)
    conn.workspace_id = scope.workspace_id
    conn.user_id = scope.user_id
    conn.status = STATUS_CONNECTED
    conn.api_key_enc = _encrypt(key)
    conn.token_hint = _hint(key)
    conn.project_id = project_id
    conn.domain = (domain or "")[:300]
    conn.last_error = ""
    conn.connected_at = _now()
    session.flush()
    return overview(session, scope)


def _call_unbound(transport: Any, key: str, tool: str, arguments: dict) -> Any:
    try:
        return oseo.call_tool(transport, key, tool, arguments)
    except oseo.OpenSeoError as exc:
        raise _mapped(exc) from exc


def _pick_project(projects: Any, domain: str) -> str:
    rows = projects if isinstance(projects, list) else (projects or {}).get("projects") or []
    for row in rows:
        if isinstance(row, dict) and domain and str(row.get("domain") or "").lower() == domain.lower():
            return str(row.get("id") or "")
    if rows and isinstance(rows[0], dict):
        return str(rows[0].get("id") or "")
    return ""


def disconnect(session: Any, scope: Scope) -> bool:
    scope.require_manage()
    conn = _connection(session, scope.owner_scope)
    if conn is None:
        return False
    session.execute(delete(SeoRankSnapshot).where(SeoRankSnapshot.rank_keyword_id.in_(
        select(SeoRankKeyword.id).where(SeoRankKeyword.connection_id == conn.id))))
    session.execute(delete(SeoRankKeyword).where(SeoRankKeyword.connection_id == conn.id))
    session.execute(delete(SeoKeywordResearch).where(SeoKeywordResearch.connection_id == conn.id))
    session.execute(delete(SeoAuditRun).where(SeoAuditRun.connection_id == conn.id))
    session.delete(conn)
    session.flush()
    return True


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
def overview(session: Any, scope: Scope) -> dict:
    conn = _connection(session, scope.owner_scope)
    if conn is None:
        return {"connected": False, "can_manage": scope.can_manage}
    latest_audit = session.execute(select(SeoAuditRun).where(SeoAuditRun.connection_id == conn.id).order_by(
        SeoAuditRun.requested_at.desc())).scalars().first()
    tracked = list(session.execute(select(SeoRankKeyword).where(
        SeoRankKeyword.connection_id == conn.id)).scalars())
    research_count = session.execute(select(SeoKeywordResearch).where(
        SeoKeywordResearch.connection_id == conn.id)).scalars().all()
    return {
        "connected": True, "status": conn.status, "token_hint": conn.token_hint, "domain": conn.domain,
        "project_id": conn.project_id, "last_error": conn.last_error or None, "can_manage": scope.can_manage,
        "latest_audit": _audit_view(latest_audit) if latest_audit else None,
        "tracked_keywords": [_rank_view(k) for k in tracked],
        "tracked_keyword_limit": MAX_TRACKED_KEYWORDS,
        "research_keyword_count": len(research_count),
    }


# --------------------------------------------------------------------------- #
# Site audit (customer-triggered; costs OpenSEO credits)
# --------------------------------------------------------------------------- #
def _audit_view(run: SeoAuditRun) -> dict:
    return {"id": run.id, "status": run.status, "score": run.score, "issues_count": run.issues_count,
            "summary": run.summary, "requested_at": run.requested_at.isoformat() if run.requested_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None}


def run_audit(session: Any, scope: Scope, *, transport: Any) -> dict:
    scope.require_manage()
    conn = get_connection(session, scope)
    if not conn.project_id:
        raise SeoError(422, "Connect an OpenSEO project with a domain before auditing it.")
    result = _call(conn, transport, "run_site_audit", {"projectId": conn.project_id})
    run = SeoAuditRun(connection_id=conn.id, owner_scope=scope.owner_scope,
                      external_audit_id=str((result or {}).get("auditId") or (result or {}).get("id") or ""),
                      status=AUDIT_RUNNING)
    session.add(run)
    session.flush()
    return _audit_view(run)


def refresh_audit(session: Any, scope: Scope, audit_run_id: str, *, transport: Any) -> dict:
    """Free status/issue reads (no new audit is started)."""
    scope.require_manage()
    conn = get_connection(session, scope)
    run = session.get(SeoAuditRun, audit_run_id)
    if run is None or run.owner_scope != scope.owner_scope:
        raise SeoError(404, "Audit not found.")
    status = _call(conn, transport, "get_audit_status", {"auditId": run.external_audit_id})
    state = str((status or {}).get("status") or "").lower()
    run.status = AUDIT_COMPLETED if state in ("completed", "done", "finished") else (
        AUDIT_FAILED if state in ("failed", "error") else AUDIT_RUNNING)
    run.score = (status or {}).get("score")
    if run.status == AUDIT_COMPLETED:
        issues = _call(conn, transport, "get_audit_issues", {"auditId": run.external_audit_id})
        rows = issues if isinstance(issues, list) else (issues or {}).get("issues") or []
        run.issues_count = len(rows)
        run.summary = {"issues": rows[:50]}
        run.completed_at = _now()
    session.flush()
    return _audit_view(run)


# --------------------------------------------------------------------------- #
# Keyword research (customer-triggered; costs OpenSEO credits)
# --------------------------------------------------------------------------- #
def research_keywords(session: Any, scope: Scope, seeds: list[str], *, transport: Any) -> list[dict]:
    scope.require_manage()
    conn = get_connection(session, scope)
    cleaned = list(dict.fromkeys(s.strip() for s in seeds if s and s.strip()))[:MAX_RESEARCH_SEEDS]
    if not cleaned:
        raise SeoError(422, "Give at least one seed keyword.")
    result = _call(conn, transport, "research_keywords", {"projectId": conn.project_id, "keywords": cleaned})
    rows = result if isinstance(result, list) else (result or {}).get("keywords") or []
    existing = {r.keyword: r for r in session.execute(select(SeoKeywordResearch).where(
        SeoKeywordResearch.connection_id == conn.id)).scalars()}
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        keyword = str(row.get("keyword") or "").strip()
        if not keyword:
            continue
        rec = existing.get(keyword)
        if rec is None:
            rec = SeoKeywordResearch(connection_id=conn.id, owner_scope=scope.owner_scope, keyword=keyword)
            session.add(rec)
            existing[keyword] = rec
        rec.seed = (cleaned[0] if cleaned else "")[:200]
        rec.volume = row.get("volume")
        rec.difficulty = row.get("difficulty") or row.get("keywordDifficulty")
        rec.cpc_minor = int(round(float(row.get("cpc") or 0) * 100)) if row.get("cpc") is not None else None
        rec.intent = str(row.get("intent") or "")[:32]
        rec.fetched_at = _now()
        out.append(rec)
    session.flush()
    _trim_research_history(session, conn.id)
    return [_research_view(r) for r in out]


def _trim_research_history(session: Any, connection_id: str) -> None:
    rows = list(session.execute(select(SeoKeywordResearch).where(
        SeoKeywordResearch.connection_id == connection_id).order_by(SeoKeywordResearch.fetched_at.desc())).scalars())
    for stale in rows[MAX_RESEARCH_HISTORY:]:
        session.delete(stale)
    session.flush()


def _research_view(r: SeoKeywordResearch) -> dict:
    return {"keyword": r.keyword, "seed": r.seed, "volume": r.volume, "difficulty": r.difficulty,
            "cpc_minor": r.cpc_minor, "intent": r.intent, "currency": r.currency,
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None}


def list_research(session: Any, scope: Scope) -> list[dict]:
    conn = _connection(session, scope.owner_scope)
    if conn is None:
        return []
    rows = session.execute(select(SeoKeywordResearch).where(SeoKeywordResearch.connection_id == conn.id).order_by(
        SeoKeywordResearch.fetched_at.desc())).scalars()
    return [_research_view(r) for r in rows]


# --------------------------------------------------------------------------- #
# Rank tracking (a handful of target keywords; costs OpenSEO credits to refresh)
# --------------------------------------------------------------------------- #
def _rank_view(k: SeoRankKeyword) -> dict:
    return {"id": k.id, "keyword": k.keyword, "country": k.country, "current_rank": k.current_rank,
            "change_7d": k.change_7d, "last_checked_at": k.last_checked_at.isoformat() if k.last_checked_at else None}


def add_rank_keywords(session: Any, scope: Scope, keywords: list[str], *, country: str = "us",
                      transport: Any) -> list[dict]:
    scope.require_manage()
    conn = get_connection(session, scope)
    existing = list(session.execute(select(SeoRankKeyword).where(SeoRankKeyword.connection_id == conn.id)).scalars())
    have = {(k.keyword, k.country) for k in existing}
    cleaned = list(dict.fromkeys(k.strip() for k in keywords if k and k.strip()))
    room = MAX_TRACKED_KEYWORDS - len(existing)
    if room <= 0:
        raise SeoError(422, f"Menivor tracks at most {MAX_TRACKED_KEYWORDS} keywords per workspace. "
                            "Remove one before adding another.")
    wanted = [k for k in cleaned if (k, country) not in have][:room]
    if not wanted:
        return [_rank_view(k) for k in existing]
    _call(conn, transport, "create_rank_tracker", {"projectId": conn.project_id})
    _call(conn, transport, "add_rank_tracking_keywords", {"projectId": conn.project_id, "keywords": wanted,
                                                          "country": country})
    added = []
    for keyword in wanted:
        row = SeoRankKeyword(connection_id=conn.id, owner_scope=scope.owner_scope, keyword=keyword, country=country)
        session.add(row)
        added.append(row)
    session.flush()
    return [_rank_view(k) for k in existing + added]


def remove_rank_keyword(session: Any, scope: Scope, keyword_id: str) -> bool:
    scope.require_manage()
    conn = get_connection(session, scope)
    row = session.get(SeoRankKeyword, keyword_id)
    if row is None or row.connection_id != conn.id:
        raise SeoError(404, "Tracked keyword not found.")
    session.execute(delete(SeoRankSnapshot).where(SeoRankSnapshot.rank_keyword_id == row.id))
    session.delete(row)
    session.flush()
    return True


def refresh_rank_tracker(session: Any, scope: Scope, *, transport: Any, today: str | None = None) -> list[dict]:
    """Ask OpenSEO to re-check every tracked keyword's rank (costs credits)."""
    scope.require_manage()
    conn = get_connection(session, scope)
    rows = list(session.execute(select(SeoRankKeyword).where(SeoRankKeyword.connection_id == conn.id)).scalars())
    if not rows:
        return []
    _call(conn, transport, "run_rank_tracker", {"projectId": conn.project_id})
    result = _call(conn, transport, "get_rank_tracker", {"projectId": conn.project_id})
    positions = result if isinstance(result, list) else (result or {}).get("keywords") or []
    by_keyword = {str(p.get("keyword") or "").strip(): p for p in positions if isinstance(p, dict)}
    day = today or _now().date().isoformat()
    for row in rows:
        p = by_keyword.get(row.keyword)
        if p is None:
            continue
        new_rank = p.get("rank") if p.get("rank") is not None else p.get("position")
        row.change_7d = (row.current_rank - new_rank) if (row.current_rank is not None and new_rank is not None) \
            else row.change_7d
        row.current_rank = new_rank
        row.last_checked_at = _now()
        session.add(SeoRankSnapshot(rank_keyword_id=row.id, day=day, rank=new_rank))
    session.flush()
    return [_rank_view(k) for k in rows]


__all__ = [
    "MAX_RESEARCH_SEEDS", "MAX_TRACKED_KEYWORDS", "add_rank_keywords", "connect", "disconnect", "get_connection",
    "list_research", "overview", "refresh_audit", "refresh_rank_tracker", "remove_rank_keyword", "research_keywords",
    "run_audit",
]
