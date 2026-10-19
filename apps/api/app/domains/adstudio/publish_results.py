"""Read side of "Publish and test": each test's posts, numbers, ranking and winner.

Built from the sources of truth the loop already maintains — the batch
anchor's loop state (status, check window, measured numbers, ranking, why it
won), the ``ScheduledPublish`` rows (per-post status, time, live URL, error)
and the creator-logged ``JobPerformance`` rows (manual tests) — and mapped back
from carrier jobs to the Ad Studio ads. Unmeasured ratios stay ``None`` (shown
as "not measured"), never 0.
"""

from __future__ import annotations

from typing import Any

from app.domains.adstudio.publish_test import TEST_SPEC_KEY, test_of

_STATUS_LABELS = {
    "awaiting_render": "Preparing",
    "publishing": "Posting",
    "waiting_for_posts": "Waiting for posts",
    "live": "Live, collecting numbers",
    "measuring": "Measuring",
    "winner_ready": "Winner picked",
    "inconclusive": "No clear result",
    "remade": "Winner remade",
    "cap_reached": "Winner picked",
}
_MAX_TESTS = 10


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _schedules(session: Any, user_id: str, job_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    from app.models.db.models import ScheduledPublish

    if not job_ids:
        return {}
    rows = (
        session.query(ScheduledPublish)
        .filter(ScheduledPublish.user_id == user_id, ScheduledPublish.job_id.in_(job_ids))
        .order_by(ScheduledPublish.scheduled_at.asc())
        .all()
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        results = (row.result or {}).get("results") if isinstance(row.result, dict) else None
        urls = {
            str(r.get("platform") or ""): str(r.get("url") or "")
            for r in (results or []) if isinstance(r, dict)
        }
        for platform in row.platforms or []:
            name = "youtube" if platform == "youtube_shorts" else str(platform)
            out.setdefault(row.job_id, []).append({
                "platform": name,
                "status": row.status,
                "scheduled_at": _iso(row.scheduled_at),
                "url": urls.get(name) or urls.get(str(platform)) or None,
                "error": (row.error or None) if row.status == "failed" else None,
            })
    return out


def _logged(session: Any, user_id: str, job_ids: list[str]) -> dict[str, dict[str, Any]]:
    from app.models.db.models import JobPerformance

    if not job_ids:
        return {}
    rows = (
        session.query(JobPerformance)
        .filter(JobPerformance.user_id == user_id, JobPerformance.job_id.in_(job_ids))
        .all()
    )
    return {
        r.job_id: {
            "platform": r.platform, "views": int(r.views or 0), "likes": int(r.likes or 0),
            "comments": int(r.comments or 0), "shares": int(r.shares or 0), "saves": int(r.saves or 0),
            "retention_pct": float(r.retention_pct or 0.0), "logged_at": _iso(r.logged_at),
        }
        for r in rows
    }


def _metrics(measured: dict[str, Any] | None) -> dict[str, Any] | None:
    if not measured:
        return None
    return {
        key: measured.get(key)
        for key in ("views", "likes", "comments", "shares", "saves", "engagement_rate",
                    "avg_watch_frac", "completion_rate", "rewatch_rate", "source")
    }


def _explanation(state: dict[str, Any]) -> dict[str, Any] | None:
    raw = state.get("explanation")
    if not isinstance(raw, dict):
        return None
    return {
        "headline": str(raw.get("headline") or ""),
        "reasons": [str(r.get("text") or "") for r in raw.get("reasons") or [] if isinstance(r, dict) and r.get("text")],
        "caveats": [str(c) for c in raw.get("caveats") or [] if c],
        "confidence": str(raw.get("confidence") or ""),
    }


def _loop_state(session: Any, batch_id: str, user_id: str) -> dict[str, Any]:
    from app.domains.insights.winner_loop_service import find_anchor
    from app.domains.insights.winner_loop_state import read_state

    anchor = find_anchor(session, batch_id, user_id)
    return read_state(anchor) if anchor is not None else {}


def _ad_row(ad: Any, info: dict[str, Any], state: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    job_id = str(info.get("job_id") or "")
    measured = {str(v.get("job_id")): v for v in state.get("variants") or [] if isinstance(v, dict)}
    ranked = {
        str(r.get("job_id")): r
        for r in ((state.get("ranking") or {}).get("ranked") or []) if isinstance(r, dict)
    }
    rank = ranked.get(job_id) or {}
    angle = (ad.spec or {}).get("angle") or {}
    return {
        "variant_id": ad.id,
        "job_id": job_id,
        "angle_label": str(angle.get("label") or ad.angle_id),
        "format": ad.format,
        "aspect": ad.aspect,
        "hook": str(angle.get("hook") or ""),
        "poster_url": ctx["presign"](ad.poster_key),
        "is_winner": bool(job_id) and job_id == str(state.get("winner_job_id") or ""),
        "rank": rank.get("rank"),
        "score": rank.get("score"),
        "metrics": _metrics(measured.get(job_id)),
        "logged": ctx["logged"].get(job_id),
        "posts": ctx["schedules"].get(job_id, []),
    }


def _test_view(batch_id: str, ads: list[Any], state: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    first = test_of(ads[0]) if ads else {}
    rows = [_ad_row(ad, test_of(ad), state, ctx) for ad in ads]
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0))
    status = str(state.get("status") or "")
    if state.get("mode") == "off":
        status_label = "Stopped"
    else:
        status_label = _STATUS_LABELS.get(status, "Starting")
    winner = next((r for r in rows if r["is_winner"]), None)
    remake = state.get("adstudio_remake") if isinstance(state.get("adstudio_remake"), dict) else None
    return {
        "batch_id": batch_id,
        "mode": str(first.get("mode") or "publish"),
        "platforms": list(state.get("platforms") or first.get("platforms") or []),
        "started_at": first.get("started_at"),
        "status": status or "starting",
        "status_label": status_label,
        "stopped": state.get("mode") == "off",
        "note": str(state.get("note") or ""),
        "check_after_hours": state.get("check_after_hours"),
        "check_due_at": state.get("check_due_at"),
        "last_checked_at": state.get("last_checked_at"),
        "checks": int(state.get("checks") or 0),
        "early_read": bool(state.get("early_read")),
        "conclusive": bool(state.get("conclusive")),
        "winner_variant_id": winner["variant_id"] if winner else None,
        "can_remake": status == "winner_ready" and winner is not None and state.get("mode") != "off",
        "explanation": _explanation(state),
        "remake": {"variant_ids": list(remake.get("variant_ids") or []), "hooks": list(remake.get("hooks") or [])}
        if remake else None,
        "ads": rows,
    }


def project_tests(session: Any, user_id: str, variants: list[Any], presign: Any) -> list[dict[str, Any]]:
    """Every test of the project, newest first."""
    groups: dict[str, list[Any]] = {}
    for ad in variants:
        batch_id = str(test_of(ad).get("batch_id") or "")
        if batch_id:
            groups.setdefault(batch_id, []).append(ad)
    ordered = sorted(groups.items(), key=lambda kv: str(test_of(kv[1][0]).get("started_at") or ""), reverse=True)
    ordered = ordered[:_MAX_TESTS]
    job_ids = [str(test_of(ad).get("job_id")) for _, ads in ordered for ad in ads if test_of(ad).get("job_id")]
    ctx = {
        "presign": presign,
        "schedules": _schedules(session, user_id, job_ids),
        "logged": _logged(session, user_id, job_ids),
    }
    return [_test_view(batch_id, ads, _loop_state(session, batch_id, user_id), ctx) for batch_id, ads in ordered]


__all__ = ["TEST_SPEC_KEY", "project_tests"]
