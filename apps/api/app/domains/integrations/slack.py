"""Slack app for the Ads agent: OAuth install, slash command, app mention, approve/reject buttons.

* Install: ``slack.com/oauth/v2/authorize`` (bot scopes ``commands``,
  ``app_mentions:read``, ``chat:write``), then ``oauth.v2.access``. The bot token
  is stored encrypted as an ``IntegrationConnection`` (kind ``slack``,
  ``external_id`` = Slack team id). One Slack team serves one Menivor scope.
  Owners/admins only, Pro and above.
* Every inbound request is verified with the Slack signing secret
  (``v0=HMAC_SHA256(secret, "v0:<ts>:<body>")``, 5-minute window); no secret
  configured means every request is refused.
* ``/menivor-ads <question>`` and ``@Menivor <question>`` answer through the Ads
  agent. ``/menivor-ads propose`` creates approval items and posts Approve /
  Reject buttons; a click calls the same approvals API as the web page
  (``actions.decide(..., via="slack")``).
* Who may approve: the Slack users in the install's ``approvers`` list (the
  installer by default). Decisions run as the installing Menivor user, who must
  still be an owner/admin of the workspace. Anyone in the Slack team may ask
  questions about the connected ad data.
* Replies to slash commands go to ``response_url``, accepted only on
  ``https://hooks.slack.com``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

from loguru import logger
from sqlalchemy import select

from app.domains.integrations import actions, agent
from app.domains.integrations.connectors.base import Grant, RequestsTransport, body_of, env
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.models import KIND_SLACK, IntegrationConnection
from app.domains.integrations.scope import Scope, resolve
from app.domains.integrations.service import claim_state, issue_state, store_connection
from app.services import crypto_tokens

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover
    get_session = None  # type: ignore[assignment]

PROVIDER = "slack"
SCOPES = "commands,app_mentions:read,chat:write"
AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
ACCESS_URL = "https://slack.com/api/oauth.v2.access"
POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
REQUIRED_ENV = ("SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET", "SLACK_SIGNING_SECRET")
MAX_SKEW_S = 300
APPROVE_ID = "ad_action_approve"
REJECT_ID = "ad_action_reject"
HELP = ("Menivor Ads agent. Try `/menivor-ads how did my ads do this week?` or `/menivor-ads propose` "
        "to get changes you can approve here.")
NOT_INSTALLED = "Menivor is not connected to this Slack workspace. Install it from Settings > Integrations."
NOT_APPROVER = "Only the approvers set in Menivor can propose or approve ad changes."

Llm = Callable[[str], str]
_TRANSPORT: Any = RequestsTransport()


def set_transport(transport: Any) -> None:
    global _TRANSPORT
    _TRANSPORT = transport


def missing_settings() -> list[str]:
    return [n for n in REQUIRED_ENV if not env(n)]


def configured() -> bool:
    return not missing_settings()


# --------------------------------------------------------------------------- signature
def verify_signature(body: bytes, timestamp: str, signature: str, *, secret: str | None = None,
                     now: float | None = None) -> bool:
    key = secret if secret is not None else env("SLACK_SIGNING_SECRET")
    if not key or not signature or not str(signature).startswith("v0="):
        return False
    try:
        ts = int(str(timestamp))
    except (TypeError, ValueError):
        return False
    if abs(int(now if now is not None else time.time()) - ts) > MAX_SKEW_S:
        return False
    expected = "v0=" + hmac.new(key.encode(), f"v0:{ts}:".encode() + bytes(body or b""), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature))


# --------------------------------------------------------------------------- install
def start_install(session: Any, scope: Scope) -> dict:
    scope.require_manage()
    agent.require_plan(session, scope)
    if not configured():
        raise IntegrationError(503, "The Slack app is not set up on this server yet.")
    from app.domains.integrations.settings import redirect_uri

    state = issue_state(session, scope, PROVIDER)
    url = AUTHORIZE_URL + "?" + urlencode({"client_id": env("SLACK_CLIENT_ID"), "scope": SCOPES, "state": state,
                                           "redirect_uri": redirect_uri()})
    return {"provider": PROVIDER, "authorize_url": url}


def finish_install(session: Any, user_id: str, *, code: str, state: str, transport: Any) -> dict:
    from app.domains.integrations.settings import redirect_uri

    claimed = claim_state(session, user_id, state)
    if claimed.provider != PROVIDER:
        raise IntegrationError(400, "This connect link is not for Slack.")
    scope = resolve(session, user_id, workspace_id=claimed.workspace_id)
    scope.require_manage()
    agent.require_plan(session, scope)
    try:
        resp = transport.request("POST", ACCESS_URL, data={
            "client_id": env("SLACK_CLIENT_ID"), "client_secret": env("SLACK_CLIENT_SECRET"),
            "code": code, "redirect_uri": redirect_uri()})
    except Exception as exc:  # noqa: BLE001
        raise IntegrationError(502, "Slack is unreachable. Try again.") from exc
    body = body_of(resp) or {}
    if not body.get("ok") or not body.get("access_token"):
        raise IntegrationError(400, "Slack did not finish the install. Try again.")
    team = body.get("team") or {}
    team_id = str(team.get("id") or "")
    taken = session.execute(select(IntegrationConnection).where(
        IntegrationConnection.provider == PROVIDER, IntegrationConnection.external_id == team_id,
        IntegrationConnection.owner_scope != scope.owner_scope)).scalars().first()
    if taken is not None:
        raise IntegrationError(409, "This Slack workspace is already connected to another Menivor workspace.")
    installer = str((body.get("authed_user") or {}).get("id") or "")
    meta = {"team_name": str(team.get("name") or "")[:200], "bot_user_id": str(body.get("bot_user_id") or ""),
            "installer_slack_user": installer, "approvers": [installer] if installer else []}
    store_connection(session, owner_scope=scope.owner_scope, workspace_id=scope.workspace_id, user_id=user_id,
                     kind=KIND_SLACK, provider=PROVIDER, grant=Grant(access_token=body["access_token"],
                                                                     scopes=str(body.get("scope") or SCOPES)),
                     display_name=meta["team_name"], meta=meta, external_id=team_id)
    return {"provider": PROVIDER, "team_id": team_id, "team_name": meta["team_name"], "approvers": meta["approvers"]}


def status(session: Any, scope: Scope) -> dict:
    row = session.execute(select(IntegrationConnection).where(
        IntegrationConnection.owner_scope == scope.owner_scope, IntegrationConnection.provider == PROVIDER,
    )).scalar_one_or_none()
    meta = dict(row.meta or {}) if row else {}
    return {"configured": configured(), "plan_allows": agent.plan_allows(session, scope), "connected": row is not None,
            "team_name": meta.get("team_name") or None, "approvers": list(meta.get("approvers") or []),
            "command": "/menivor-ads"}


def set_approvers(session: Any, scope: Scope, slack_user_ids: list[str]) -> dict:
    scope.require_manage()
    row = session.execute(select(IntegrationConnection).where(
        IntegrationConnection.owner_scope == scope.owner_scope, IntegrationConnection.provider == PROVIDER,
    )).scalar_one_or_none()
    if row is None:
        raise IntegrationError(404, "Slack is not connected.")
    clean = list(dict.fromkeys(u.strip() for u in slack_user_ids if u and u.strip().isalnum()))[:50]
    row.meta = {**dict(row.meta or {}), "approvers": clean}
    session.flush()
    return status(session, scope)


def disconnect(session: Any, scope: Scope) -> bool:
    scope.require_manage()
    row = session.execute(select(IntegrationConnection).where(
        IntegrationConnection.owner_scope == scope.owner_scope, IntegrationConnection.provider == PROVIDER,
    )).scalar_one_or_none()
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


# --------------------------------------------------------------------------- runtime
def _install_for(session: Any, team_id: str) -> IntegrationConnection | None:
    if not team_id:
        return None
    return session.execute(select(IntegrationConnection).where(
        IntegrationConnection.provider == PROVIDER, IntegrationConnection.external_id == team_id,
    )).scalars().first()


def _installer_scope(session: Any, row: IntegrationConnection) -> Scope:
    return resolve(session, row.user_id, workspace_id=row.workspace_id)


def _is_approver(row: IntegrationConnection, slack_user: str) -> bool:
    return bool(slack_user) and slack_user in list((row.meta or {}).get("approvers") or [])


def proposal_blocks(item: dict) -> list[dict]:
    payload = item.get("payload") or {}
    text = f"*{item.get('title', 'Proposed change')}*\n{payload.get('reason') or item.get('summary') or ''}".strip()
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}},
        {"type": "actions", "elements": [
            {"type": "button", "action_id": APPROVE_ID, "style": "primary", "value": item["id"],
             "text": {"type": "plain_text", "text": "Approve"}},
            {"type": "button", "action_id": REJECT_ID, "style": "danger", "value": item["id"],
             "text": {"type": "plain_text", "text": "Reject"}},
        ]},
    ]


def _answer(scope_session: Any, scope: Scope, question: str, llm: Llm | None) -> str:
    out = agent.ask_campaign_question(scope_session, scope, question, llm=llm)
    return out["answer"]


def respond(team_id: str, slack_user: str, text: str, *, llm: Llm | None = None) -> dict:
    """The Slack message for a question or command (shared by slash command and mention)."""
    words = " ".join(str(text or "").split())
    with get_session() as session:  # type: ignore[misc]
        row = _install_for(session, team_id)
        if row is None:
            return {"text": NOT_INSTALLED}
        if not words or words.lower() == "help":
            return {"text": HELP}
        try:
            scope = _installer_scope(session, row)
            if words.lower().startswith("propose"):
                if not _is_approver(row, slack_user):
                    return {"text": NOT_APPROVER}
                proposals = agent.propose_optimization(session, scope)["proposals"]
                if not proposals:
                    return {"text": "Nothing to change right now: no creative is clearly wasting budget."}
                blocks = [b for item in proposals for b in proposal_blocks(item)]
                return {"text": f"{len(proposals)} change(s) need approval.", "blocks": blocks}
            return {"text": _answer(session, scope, words, llm)}
        except IntegrationError as exc:
            return {"text": exc.message}


def command_message(form: dict, *, llm: Llm | None = None) -> dict:
    msg = respond(str(form.get("team_id") or ""), str(form.get("user_id") or ""), str(form.get("text") or ""),
                  llm=llm)
    return {"response_type": "ephemeral", **msg}


def parse_interaction_body(body: bytes) -> dict:
    try:
        raw = parse_qs((body or b"").decode("utf-8")).get("payload", [""])[0]
        data = json.loads(raw) if raw else {}
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def interaction_message(payload: dict) -> dict:
    """Handle an Approve/Reject click. Returns the replacement message."""
    team_id = str((payload.get("team") or {}).get("id") or "")
    slack_user = str((payload.get("user") or {}).get("id") or "")
    clicked = next((a for a in payload.get("actions") or [] if a.get("action_id") in (APPROVE_ID, REJECT_ID)), None)
    if clicked is None:
        return {"replace_original": False, "text": "Unknown action."}
    decision = "approve" if clicked["action_id"] == APPROVE_ID else "reject"
    with get_session() as session:  # type: ignore[misc]
        row = _install_for(session, team_id)
        if row is None:
            return {"replace_original": False, "text": NOT_INSTALLED}
        if not _is_approver(row, slack_user):
            return {"replace_original": False, "text": NOT_APPROVER}
        try:
            scope = _installer_scope(session, row)
        except IntegrationError as exc:
            return {"replace_original": False, "text": exc.message}
    try:
        out = actions.decide(scope, str(clicked.get("value") or ""), decision, via="slack",
                             note=f"slack:{slack_user}")
    except IntegrationError as exc:
        return {"replace_original": False, "text": exc.message}
    item = out["item"]
    verb = "Approved" if decision == "approve" else "Rejected"
    detail = f" ({item['error']})" if item.get("error") else ""
    return {"replace_original": True, "text": f"{verb} by <@{slack_user}>: {item['title']}{detail}"}


def post_response(transport: Any, response_url: str, message: dict) -> bool:
    parsed = urlparse(str(response_url or ""))
    if parsed.scheme != "https" or parsed.hostname != "hooks.slack.com":
        logger.warning("slack: refused a response_url outside hooks.slack.com")
        return False
    try:
        transport.request("POST", response_url, json=message)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"slack: response_url post failed: {exc.__class__.__name__}")
        return False
    return True


def handle_event(payload: dict, *, transport: Any = None, llm: Llm | None = None) -> dict:
    """Events API: URL verification and ``app_mention`` (answered in the thread)."""
    if payload.get("type") == "url_verification":
        return {"challenge": str(payload.get("challenge") or "")}
    event = payload.get("event") or {}
    if payload.get("type") != "event_callback" or event.get("type") != "app_mention" or event.get("bot_id"):
        return {}
    team_id = str(payload.get("team_id") or "")
    text = " ".join(w for w in str(event.get("text") or "").split() if not (w.startswith("<@") and w.endswith(">")))
    message = respond(team_id, str(event.get("user") or ""), text, llm=llm)
    with get_session() as session:  # type: ignore[misc]
        row = _install_for(session, team_id)
        token = crypto_tokens.decrypt(row.access_token_enc) if row else ""
    if not token:
        return {}
    body = {"channel": event.get("channel"), "thread_ts": event.get("thread_ts") or event.get("ts"), **message}
    try:
        (transport or _TRANSPORT).request("POST", POST_MESSAGE_URL, json=body,
                                          headers={"Authorization": f"Bearer {token}",
                                                   "Content-Type": "application/json; charset=utf-8"})
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"slack: chat.postMessage failed: {exc.__class__.__name__}")
    return {}


__all__ = [
    "APPROVE_ID", "REJECT_ID", "SCOPES", "command_message", "configured", "disconnect", "finish_install",
    "handle_event", "interaction_message", "parse_interaction_body", "post_response", "proposal_blocks", "respond",
    "set_approvers", "set_transport", "start_install", "status", "verify_signature",
]
