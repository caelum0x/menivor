"""SCIM 2.0 provisioning service (Identity & SSO, Epic 2).

An enterprise IdP (Okta / Azure AD / …) provisions and deprovisions users into a
workspace over SCIM 2.0. This module implements the core resource operations plus
the token auth that enforces the #1 invariant:

    TENANT ISOLATION — a SCIM token is scoped to ONE workspace and can NEVER
    provision into, read, or modify another workspace.

:func:`auth_token` resolves a presented ``Bearer`` token (by its SHA-256 digest,
never the raw secret) to its :class:`ScimToken` row and asserts the row's
``workspace_id`` matches the target workspace — a mismatch is a
:class:`ScimAuthError` (mapped to 401/403 at the API), so a token minted for
workspace *B* cannot touch workspace *A*. Every subsequent write
(:func:`provision_user` / :func:`update_user` / :func:`deactivate_user`) is scoped
to that same workspace and mutates an :class:`ExternalIdentity` (+ its
:class:`User` membership) within it. Every write records an audit row (Epic 1).

The provisioning state lives in :class:`ExternalIdentity` (shared with the SAML
path): a provision creates/links it (``provisioned=True``), a deactivate
soft-disables it (``provisioned=False``) — never a hard delete, so the mapping is
retained for audit and re-activation.

The optional ``scim2-filter-parser`` (MIT) may help parse SCIM ``filter=``
expressions; it is import-guarded and the service degrades to a simple
``userName``/``email`` equality match when it is absent.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from app.models.db.models import User, WorkspaceMember
from app.models.db.repositories import (
    ExternalIdentityRepository,
    ScimTokenRepository,
    WorkspaceRepository,
)
from app.services import audit, rbac

# --------------------------------------------------------------------------- #
# Import-guarded optional SCIM filter parser. Absence degrades filtering to a
# simple equality match — never an ImportError.
# --------------------------------------------------------------------------- #
try:  # pragma: no cover - optional dependency
    from scim2_filter_parser.parser import SCIMParser  # type: ignore

    _FILTER_PARSER_AVAILABLE = True
except Exception:  # noqa: BLE001 - import-safe
    SCIMParser = None  # type: ignore[assignment,misc]
    _FILTER_PARSER_AVAILABLE = False


#: SCIM 2.0 schema URIs.
SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"

#: Default role granted to a SCIM-provisioned user (mirrors the SSO default).
SCIM_DEFAULT_ROLE = rbac.ROLE_VIEWER

#: The non-secret display prefix + full token prefix for a minted SCIM token.
_TOKEN_PREFIX = "scim_"


class ScimError(Exception):
    """Base class for a SCIM operation failure."""


class ScimAuthError(ScimError):
    """Raised when a bearer token is missing, unknown, revoked, or cross-tenant.

    This is the tenant-isolation gate: a token that does not resolve to a LIVE row
    whose ``workspace_id`` matches the target workspace is rejected here.
    """


class ScimNotFoundError(ScimError):
    """Raised when a SCIM resource id does not exist in the token's workspace."""


# --------------------------------------------------------------------------- #
# Token minting + auth
# --------------------------------------------------------------------------- #
def hash_token(raw_token: str) -> str:
    """Return the SHA-256 hex digest of a raw SCIM bearer token (the stored form)."""
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def create_token(
    session: Any,
    workspace_id: str,
    *,
    actor_user_id: str | None = None,
    actor_ip: str | None = None,
) -> tuple[Any, str]:
    """Mint a SCIM bearer token for ``workspace_id``; return ``(row, raw_token)``.

    The RAW token is returned exactly ONCE (for the caller to hand to the IdP) and
    NEVER persisted — only its SHA-256 digest is stored. The token is scoped to
    ``workspace_id`` (tenant isolation). Records an audit row when ``actor_user_id``
    is given.
    """
    if not (workspace_id or "").strip():
        raise ScimError("workspace_id must be a non-empty string")
    raw_token = _TOKEN_PREFIX + secrets.token_urlsafe(32)
    prefix = raw_token[:12]
    row = ScimTokenRepository(session).create(
        workspace_id=workspace_id, token_hash=hash_token(raw_token), prefix=prefix
    )
    if actor_user_id:
        audit.record(
            session,
            actor_user_id=actor_user_id,
            action="scim.token_created",
            workspace_id=workspace_id,
            target_type="scim_token",
            target_id=row.id,
            metadata={"prefix": prefix},
            ip=actor_ip,
        )
    return row, raw_token


def revoke_token(
    session: Any,
    workspace_id: str,
    token_id: str,
    *,
    actor_user_id: str | None = None,
    actor_ip: str | None = None,
) -> bool:
    """Revoke a SCIM token owned by ``workspace_id``; return whether a row changed.

    Workspace-scoped: a caller can never revoke another workspace's token. Records
    an audit row on a real revocation.
    """
    revoked = ScimTokenRepository(session).revoke(token_id, workspace_id)
    if revoked and actor_user_id:
        audit.record(
            session,
            actor_user_id=actor_user_id,
            action="scim.token_revoked",
            workspace_id=workspace_id,
            target_type="scim_token",
            target_id=token_id,
            metadata={},
            ip=actor_ip,
        )
    return revoked


def auth_token(session: Any, workspace_id: str, bearer: str) -> Any:
    """Authenticate a SCIM ``Bearer`` token against ``workspace_id`` (tenant gate).

    Resolves the presented token by its SHA-256 digest to a LIVE (non-revoked)
    :class:`ScimToken` and asserts the row's ``workspace_id`` EQUALS the target —
    the load-bearing tenant-isolation check. A missing / unknown / revoked /
    cross-tenant token raises :class:`ScimAuthError`. Best-effort stamps
    ``last_used_at``. Returns the authenticated token row.
    """
    normalized_ws = (workspace_id or "").strip()
    if not normalized_ws:
        raise ScimAuthError("workspace_id must be a non-empty string")
    token = _extract_bearer(bearer)
    if not token:
        raise ScimAuthError("missing SCIM bearer token")

    repo = ScimTokenRepository(session)
    row = repo.get_by_hash(hash_token(token))
    if row is None:
        raise ScimAuthError("invalid or revoked SCIM token")
    # TENANT ISOLATION: the token must belong to the workspace being addressed.
    if row.workspace_id != normalized_ws:
        raise ScimAuthError(
            "SCIM token is not authorized for this workspace"
        )
    repo.touch_last_used(row.id)
    return row


def _extract_bearer(value: str) -> str:
    """Strip an optional ``Bearer `` prefix and surrounding whitespace."""
    token = (value or "").strip()
    if token.lower().startswith("bearer "):
        token = token[len("bearer "):].strip()
    return token


# --------------------------------------------------------------------------- #
# User resource operations (all workspace-scoped)
# --------------------------------------------------------------------------- #
def provision_user(session: Any, workspace_id: str, payload: dict) -> dict:
    """Create/link a user + :class:`ExternalIdentity` in ``workspace_id`` (SCIM Create).

    The SCIM ``externalId`` (falling back to ``userName``) is the IdP subject; the
    identity is matched/created by ``(workspace_id, idp_subject)`` (tenant-scoped),
    linking an existing ReelForge user with that email or creating a new one, and
    workspace membership is ensured. Idempotent — re-provisioning the same subject
    re-activates the existing identity. Returns the SCIM User resource. Records an
    audit row.
    """
    subject = _subject_from_payload(payload)
    email = _email_from_payload(payload)
    if not subject:
        raise ScimError("SCIM payload must carry an externalId or userName")

    identities = ExternalIdentityRepository(session)
    existing = identities.get_by_subject(workspace_id, subject)
    if existing is not None:
        if email and (existing.email or "").lower() != email.lower():
            identities.update_email(existing.id, workspace_id, email)
        identities.set_provisioned(existing.id, workspace_id, True)
        _ensure_membership(session, workspace_id, existing.user_id)
        row = identities.get_owned(existing.id, workspace_id)
        _audit(session, workspace_id, "scim.user_reprovisioned", row.user_id, row.id, email)
        return _to_scim_user(row)

    user = _find_or_create_user(session, email or subject)
    identity = identities.create(
        user_id=user.id,
        workspace_id=workspace_id,
        idp_subject=subject,
        email=email,
        provisioned=True,
    )
    _ensure_membership(session, workspace_id, user.id)
    _audit(session, workspace_id, "scim.user_provisioned", user.id, identity.id, email)
    return _to_scim_user(identity)


def get_user(session: Any, workspace_id: str, identity_id: str) -> dict:
    """Return one SCIM User resource by id (tenant-scoped); 404 across tenants."""
    identity = ExternalIdentityRepository(session).get_owned(identity_id, workspace_id)
    if identity is None:
        raise ScimNotFoundError(f"SCIM user {identity_id} not found")
    return _to_scim_user(identity)


def list_users(
    session: Any,
    workspace_id: str,
    scim_filter: str | None = None,
    *,
    start_index: int = 1,
    count: int = 100,
) -> dict:
    """Return a SCIM ListResponse of the workspace's identities (tenant-scoped).

    Only ``workspace_id``'s identities are ever returned — a token for another
    workspace can never enumerate these. An optional SCIM ``filter=`` (``userName``
    / ``email`` equality) narrows the result; the parse uses ``scim2-filter-parser``
    when available and falls back to a simple ``eq`` match otherwise.
    """
    offset = max(0, int(start_index) - 1)
    limit = max(1, int(count))
    rows = ExternalIdentityRepository(session).list_for_workspace(
        workspace_id, limit=limit, offset=offset
    )
    wanted = _filter_value(scim_filter)
    if wanted is not None:
        rows = [r for r in rows if (r.email or "").lower() == wanted.lower()]
    resources = [_to_scim_user(r) for r in rows]
    return {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": len(resources),
        "startIndex": int(start_index),
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


def update_user(
    session: Any, workspace_id: str, identity_id: str, payload: dict
) -> dict:
    """Apply a SCIM PATCH/PUT to a user in ``workspace_id`` (tenant-scoped).

    Supports the common IdP operations: toggling ``active`` (a ``False`` maps to a
    soft-deactivate) and updating the email. A resource in another workspace is a
    :class:`ScimNotFoundError` (never touched). Returns the updated SCIM User.
    """
    identities = ExternalIdentityRepository(session)
    identity = identities.get_owned(identity_id, workspace_id)
    if identity is None:
        raise ScimNotFoundError(f"SCIM user {identity_id} not found")

    active = _active_from_payload(payload)
    email = _email_from_payload(payload)
    if email and (identity.email or "").lower() != email.lower():
        identities.update_email(identity_id, workspace_id, email)
    if active is not None:
        identities.set_provisioned(identity_id, workspace_id, active)
        if not active:
            _remove_membership(session, workspace_id, identity.user_id)
    row = identities.get_owned(identity_id, workspace_id)
    _audit(session, workspace_id, "scim.user_updated", row.user_id, identity_id, row.email)
    return _to_scim_user(row)


def deactivate_user(session: Any, workspace_id: str, identity_id: str) -> dict:
    """Soft-deactivate a user in ``workspace_id`` (SCIM Delete/deprovision).

    Tenant-scoped: flips the identity's ``provisioned`` to ``False`` and removes
    the workspace membership — the :class:`ExternalIdentity` row is RETAINED (never
    hard-deleted) so the mapping survives for audit / re-activation. A resource in
    another workspace is a :class:`ScimNotFoundError`. Returns the deactivated
    SCIM User.
    """
    identities = ExternalIdentityRepository(session)
    identity = identities.set_provisioned(identity_id, workspace_id, False)
    if identity is None:
        raise ScimNotFoundError(f"SCIM user {identity_id} not found")
    _remove_membership(session, workspace_id, identity.user_id)
    _audit(
        session, workspace_id, "scim.user_deactivated",
        identity.user_id, identity_id, identity.email,
    )
    return _to_scim_user(identity)


# --------------------------------------------------------------------------- #
# Group / membership sync (minimal core)
# --------------------------------------------------------------------------- #
def sync_group_members(
    session: Any,
    workspace_id: str,
    member_subjects: list[str],
    role: str = SCIM_DEFAULT_ROLE,
) -> dict:
    """Ensure each subject in a SCIM group is an active member at ``role``.

    Tenant-scoped: only identities already provisioned in ``workspace_id`` are
    affected. Returns a small summary ``{updated: [subject...], missing:
    [subject...]}`` — a subject with no identity in this workspace is reported as
    ``missing`` rather than silently created (SCIM group membership does not imply
    user creation). ``role`` is validated to a known RBAC role.
    """
    normalized_role = role if role in rbac.ROLES else SCIM_DEFAULT_ROLE
    identities = ExternalIdentityRepository(session)
    updated: list[str] = []
    missing: list[str] = []
    for subject in member_subjects or []:
        identity = identities.get_by_subject(workspace_id, subject)
        if identity is None:
            missing.append(subject)
            continue
        _ensure_membership(session, workspace_id, identity.user_id, role=normalized_role)
        updated.append(subject)
    return {"updated": updated, "missing": missing}


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _subject_from_payload(payload: dict) -> str:
    """Extract the IdP subject: ``externalId`` first, else ``userName``."""
    data = payload or {}
    subject = str(data.get("externalId") or "").strip()
    if subject:
        return subject
    return str(data.get("userName") or "").strip()


def _email_from_payload(payload: dict) -> str:
    """Extract the primary email from a SCIM User payload (best-effort)."""
    data = payload or {}
    emails = data.get("emails")
    if isinstance(emails, list):
        primary = next(
            (e for e in emails if isinstance(e, dict) and e.get("primary")), None
        )
        chosen = primary or (emails[0] if emails and isinstance(emails[0], dict) else None)
        if chosen and chosen.get("value"):
            return str(chosen["value"]).strip()
    for key in ("email", "userName"):
        value = data.get(key)
        if isinstance(value, str) and "@" in value:
            return value.strip()
    return ""


def _active_from_payload(payload: dict) -> bool | None:
    """Resolve the ``active`` flag from a SCIM PUT or PatchOp; ``None`` if absent."""
    data = payload or {}
    if "active" in data:
        return bool(data["active"])
    # PatchOp: {"Operations": [{"op": "replace", "path": "active", "value": ...}]}
    operations = data.get("Operations") or data.get("operations")
    if isinstance(operations, list):
        for op in operations:
            if not isinstance(op, dict):
                continue
            path = str(op.get("path") or "").strip().lower()
            value = op.get("value")
            if path == "active":
                return _coerce_bool(value)
            if path == "" and isinstance(value, dict) and "active" in value:
                return _coerce_bool(value.get("active"))
    return None


def _coerce_bool(value: Any) -> bool:
    """Coerce a SCIM boolean (bool or the strings 'true'/'false') to ``bool``."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _filter_value(scim_filter: str | None) -> str | None:
    """Return the equality value from a SCIM ``userName``/``email`` eq filter.

    Uses ``scim2-filter-parser`` when available, else a simple string parse of
    ``<attr> eq "<value>"``. Returns ``None`` when there is no usable filter.
    """
    expr = (scim_filter or "").strip()
    if not expr:
        return None
    if _FILTER_PARSER_AVAILABLE:
        try:  # pragma: no cover - exercised only when the parser is installed
            from scim2_filter_parser.lexer import SCIMLexer  # type: ignore

            tokens = SCIMLexer().tokenize(expr)
            tree = SCIMParser().parse(tokens)
            value = getattr(getattr(tree, "second", None), "value", None)
            if value is not None:
                return str(value).strip().strip('"')
        except Exception:  # noqa: BLE001 - fall through to the simple parser
            pass
    lowered = expr.lower()
    if " eq " in lowered:
        raw = expr.split(" eq ", 1)[1].strip()
        return raw.strip().strip('"')
    return None


def _find_or_create_user(session: Any, email: str) -> User:
    """Return the existing user for ``email`` (linking) or create a new one."""
    from sqlalchemy import func, select

    normalized = (email or "").strip()
    if normalized:
        stmt = (
            select(User).where(func.lower(User.email) == normalized.lower()).limit(1)
        )
        user = session.execute(stmt).scalars().first()
        if user is not None:
            return user
    display = normalized.split("@", 1)[0] if "@" in normalized else normalized
    user = User(email=normalized or f"{secrets.token_hex(8)}@scim.local", display_name=display)
    session.add(user)
    session.flush()  # populate user.id without ending the transaction
    return user


def _ensure_membership(
    session: Any, workspace_id: str, user_id: str, role: str = SCIM_DEFAULT_ROLE
) -> None:
    """Ensure a workspace membership at ``role`` (idempotent; sets role if present)."""
    repo = WorkspaceRepository(session)
    existing = repo.get_membership(workspace_id, user_id)
    if existing is not None:
        if role and existing.role != role:
            existing.role = role
            session.flush()
        return
    session.add(
        WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
    )
    session.flush()


def _remove_membership(session: Any, workspace_id: str, user_id: str) -> None:
    """Remove a user's workspace membership (deprovisioning); no-op when absent."""
    repo = WorkspaceRepository(session)
    membership = repo.get_membership(workspace_id, user_id)
    if membership is not None:
        session.delete(membership)
        session.flush()


def _to_scim_user(identity: Any) -> dict:
    """Serialize an :class:`ExternalIdentity` into a SCIM 2.0 User resource dict."""
    return {
        "schemas": [SCIM_USER_SCHEMA],
        "id": identity.id,
        "externalId": identity.idp_subject,
        "userName": identity.email or identity.idp_subject,
        "active": bool(identity.provisioned),
        "emails": (
            [{"value": identity.email, "primary": True}] if identity.email else []
        ),
        "meta": {
            "resourceType": "User",
            "created": _iso(getattr(identity, "created_at", None)),
            "lastModified": _iso(getattr(identity, "updated_at", None)),
        },
    }


def _iso(value: Any) -> str | None:
    """Best-effort ISO-8601 rendering of a timestamp; ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:  # noqa: BLE001 - defensive
        return str(value)


def _audit(
    session: Any,
    workspace_id: str,
    action: str,
    actor_user_id: str,
    target_id: str,
    email: str,
) -> None:
    """Record a SCIM write to the append-only audit trail (Epic 1).

    The write is made by an IdP-held SCIM token (not an interactive user), so the
    audit row is attributed to the AFFECTED user (a real, FK-valid ``users.id``)
    with the SCIM origin captured in ``metadata`` — scoped to the token's
    workspace. This keeps the ``actor_user_id`` foreign key valid on Postgres
    while still recording who was provisioned/deprovisioned.
    """
    metadata: dict[str, Any] = {"via": "scim"}
    if email:
        metadata["email"] = email
    audit.record(
        session,
        actor_user_id=actor_user_id,
        action=action,
        workspace_id=workspace_id,
        target_type="external_identity",
        target_id=target_id,
        metadata=metadata,
    )


__all__ = [
    "SCIM_DEFAULT_ROLE",
    "SCIM_LIST_SCHEMA",
    "SCIM_USER_SCHEMA",
    "ScimAuthError",
    "ScimError",
    "ScimNotFoundError",
    "auth_token",
    "create_token",
    "deactivate_user",
    "get_user",
    "hash_token",
    "list_users",
    "provision_user",
    "revoke_token",
    "sync_group_members",
]
