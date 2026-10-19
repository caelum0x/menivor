"""Preflight: check an action can really run BEFORE the user is asked to approve it.

Approve used to be shown first and the action failed afterwards ("no product preset
for this brand", three times in a row). Now every gated action is checked for what
it needs: being signed in, enough credits, an Ad Clone product, a connected account
to publish to, a generation model. Each missing thing becomes an inline step with
one action that fixes it (sign in, get credits, pick a product, connect an
account); Approve appears only once nothing is missing.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

NEED_SIGN_IN = "sign_in"
NEED_CREDITS = "credits"
NEED_PRODUCT = "product"
NEED_ACCOUNT = "account"
NEED_VIDEO = "video"
NEED_UNAVAILABLE = "unavailable"
DEVICE_EMAIL_SUFFIX = "@accounts.reelforge.app"
MAX_PRODUCT_CHIPS = 6
_PLATFORM_PROVIDER = {"tiktok": "tiktok", "instagram": "instagram", "youtube_shorts": "youtube"}


def need(need_id: str, title: str, detail: str = "", options: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"id": need_id, "title": title, "detail": detail, "options": list(options or [])}


def is_signed_out(session: Any, user_id: str) -> bool:
    """A guest device account (no real sign-in) cannot approve spending."""
    from app.models.db.models import User

    user = session.get(User, user_id)
    email = str(getattr(user, "email", "") or "")
    return user is None or not email or email.endswith(DEVICE_EMAIL_SUFFIX)


def credit_balance(session: Any, user_id: str) -> int:
    """The credits meter the agent shows (personal credit ledger)."""
    from app.models.db.repositories import CreditRepository

    try:
        return int(CreditRepository(session).balance(user_id))
    except Exception as exc:  # noqa: BLE001 - unknown balance: let the generation service decide
        logger.warning(f"brand agent preflight: balance lookup failed: {type(exc).__name__}")
        return 1 << 30


def has_spendable(session: Any, user_id: str) -> bool:
    """Credits on the meter, or money in the wallet the media gateway charges (a Mint-backed
    wallet is never blocked here: its balance is remote and the gateway checks it)."""
    if credit_balance(session, user_id) > 0:
        return True
    try:
        from app.domains.wallet.service import WalletService

        account = WalletService(session)._resolve_account(user_id, None, create=False)
    except Exception:  # noqa: BLE001 - no wallet tables / unknown: do not block
        return True
    if account is None:
        return False
    return bool(getattr(account, "mint_account_id", "")) or int(getattr(account, "available_micros", 0) or 0) > 0


def _accounts(session: Any, user_id: str, providers: set[str]) -> set[str]:
    try:
        from sqlalchemy import select

        from app.domains.multipost.models import MultipostAccount

        rows = session.execute(select(MultipostAccount.provider).where(
            MultipostAccount.user_id == user_id, MultipostAccount.provider.in_(providers))).scalars().all()
        return set(rows)
    except Exception:  # noqa: BLE001 - optional table
        return set()


def _clone_needs(session: Any, deps: Any, user_id: str, space_id: str, sections: dict[str, Any]) -> list[dict]:
    from app.domains.brand_agent.ports.ad_clone import StubAdClone

    port = deps.ad_clone
    if isinstance(port, StubAdClone):
        return [need(NEED_UNAVAILABLE, "Ad Clone is not installed on this server yet.",
                     "Your link is saved in Inspirations.")]
    check = getattr(port, "preflight", None)
    found = check(session, user_id, brand=sections, space_id=space_id) if callable(check) else None
    if not found:
        return []
    if found["id"] == "product":
        return [need(NEED_PRODUCT, found["title"], found.get("detail", ""), found.get("options") or [])]
    return [need(NEED_UNAVAILABLE, found["title"], found.get("detail", ""))]


def _publish_needs(session: Any, user_id: str, payload: dict[str, Any]) -> list[dict]:
    out = []
    if not str(payload.get("job_id") or ""):
        out.append(need(NEED_VIDEO, "There is no finished video to publish yet.",
                        "Ask me for a video first; publishing comes after it is made."))
    wanted = {_PLATFORM_PROVIDER.get(p, p) for p in payload.get("platforms") or ["tiktok"]}
    missing = sorted(wanted - _accounts(session, user_id, wanted))
    if missing:
        out.append(need(NEED_ACCOUNT, f"Connect {', '.join(m.title() for m in missing)} to publish.",
                        "Connect the account in Autopost, then press Check again."))
    return out


def _media_needs(deps: Any, kind: str, payload: dict[str, Any]) -> list[dict]:
    check = getattr(deps.generation, "preflight", None)
    media = "video" if kind == "generate_video" or payload.get("media") == "video" else "image"
    reason = check(media, dict(payload.get("options") or {})) if callable(check) else ""
    return [need(NEED_UNAVAILABLE, reason)] if reason else []


def check(session: Any, deps: Any, user_id: str, space_id: str, kind: str, payload: dict[str, Any],
          sections: dict[str, Any]) -> list[dict[str, Any]]:
    """Everything still missing for this action (empty list = ready to approve)."""
    from app.domains.brand_agent import gate

    if is_signed_out(session, user_id):
        return [need(NEED_SIGN_IN, "Sign in to make this.", "Your brand and chat stay as they are.")]
    needs: list[dict[str, Any]] = []
    cost = gate.estimate(kind, payload)
    if cost > 0 and not has_spendable(session, user_id):
        needs.append(need(NEED_CREDITS, f"You have 0 credits; this uses about {cost}.",
                          "Get credits, then press Check again."))
    if kind == gate.KIND_CLONE:
        needs.extend(_clone_needs(session, deps, user_id, space_id, sections))
    elif kind == gate.KIND_PUBLISH:
        needs.extend(_publish_needs(session, user_id, payload))
    else:
        needs.extend(_media_needs(deps, kind, payload))
    return needs


def chips(action_id: str, needs: list[dict[str, Any]]) -> list[dict[str, str]]:
    """One clear action per missing thing, then "Check again" when the fix happens elsewhere."""
    out: list[dict[str, str]] = []
    recheck = False
    for n in needs:
        if n["id"] == NEED_SIGN_IN:
            return [{"label": "Sign in", "choice": "open", "href": "/sign-in"}]
        if n["id"] == NEED_CREDITS:
            out.append({"label": "Get credits", "choice": "open", "href": "/billing"})
            recheck = True
        elif n["id"] == NEED_PRODUCT:
            for o in (n.get("options") or [])[:MAX_PRODUCT_CHIPS]:
                out.append({"label": f"Use {o['name'][:40]}", "choice": "use_product", "action_id": action_id,
                            "value": o["id"]})
            if not n.get("options"):
                out.append({"label": "Import products", "choice": "open", "href": "/settings/integrations"})
                recheck = True
        elif n["id"] == NEED_ACCOUNT:
            out.append({"label": "Connect account", "choice": "open", "href": "/autopost"})
            recheck = True
    if recheck:
        out.append({"label": "Check again", "choice": "recheck", "action_id": action_id})
    return out


def summary(needs: list[dict[str, Any]]) -> str:
    return " ".join(n["title"] for n in needs)


__all__ = ["NEED_ACCOUNT", "NEED_CREDITS", "NEED_PRODUCT", "NEED_SIGN_IN", "NEED_UNAVAILABLE", "NEED_VIDEO",
           "check", "chips", "credit_balance", "has_spendable", "is_signed_out", "need", "summary"]
