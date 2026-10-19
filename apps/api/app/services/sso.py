"""Enterprise SSO service (Identity & SSO, Epic 2) — SAML on python3-saml.

Enterprise SSO is an ADDITIVE, NEW auth path for orgs that configure an identity
provider (IdP); it does NOT replace Clerk (email + Google). This module owns four
concerns:

    configure_connection() / get_connection() / rotate_certificate()
        Persist a workspace's IdP connection. The IdP signing certificate / OIDC
        client secret are Fernet-encrypted (:mod:`app.services.crypto_tokens`,
        ``SOCIAL_TOKEN_KEY``) before they reach the DB — never plaintext. RBAC
        (``workspace.settings``) is gated at the API; every change writes an audit
        row (Epic 1).
    build_login_redirect()
        Build the SP-initiated redirect URL (deflate+base64 AuthnRequest) that
        sends the browser to the IdP. Pure-python (no xmlsec) so it works without
        the native SAML toolkit.
    _validate_saml_response()  ← the MOCKABLE, IMPORT-GUARDED validator SEAM
        When python3-saml (``onelogin.saml2``) is available this parses AND
        validates the SAMLResponse — signature against the IdP cert, audience /
        recipient, and the ``NotOnOrAfter`` conditions — and returns the
        subject / email / attributes / assertion-id. It is the ONLY place that
        needs the native ``xmlsec`` lib, so it is guarded: when the lib is absent
        the SSO endpoints degrade to a clean ``503`` ("SSO unavailable"). Tests
        exercise :func:`process_acs` by INJECTING a validated assertion through
        this seam — no xmlsec required.
    process_acs()
        Validate (via the seam) -> REPLAY-protect (a processed-assertion-id cache)
        -> enforce email presence + domain allowlist -> map to a ReelForge user
        (match/create :class:`ExternalIdentity` by ``(workspace_id, idp_subject)``)
        -> return a session grant.

CRITICAL SAFETY — the SAML signature/condition validation is delegated ENTIRELY
to python3-saml (SAML-Toolkits/python3-saml, MIT). This module NEVER hand-rolls
an XML-signature check (hand-rolled SAML == XML-signature-wrapping / audience-
bypass vulnerabilities). Tenant isolation: a connection is scoped to ONE
workspace and can never authenticate into another.
"""

from __future__ import annotations

import base64
import zlib
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Any, Callable, Protocol
from urllib.parse import quote

from loguru import logger

from app.models.db.models import User, WorkspaceMember
from app.models.db.repositories import (
    ExternalIdentityRepository,
    SecurityPolicyRepository,
    SSOConnectionRepository,
    WorkspaceRepository,
)
from app.services import audit, crypto_tokens, rbac

# --------------------------------------------------------------------------- #
# Import-guarded native SAML toolkit (python3-saml -> onelogin.saml2). The
# toolkit needs the native ``xmlsec`` lib which MAY be absent; keeping the import
# guarded makes the whole module import-safe. When absent, :func:`saml_available`
# is ``False`` and the API layer degrades every SSO endpoint to a 503.
# --------------------------------------------------------------------------- #
try:  # pragma: no cover - depends on native xmlsec being installed
    from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore

    _SAML_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    OneLogin_Saml2_Auth = None  # type: ignore[assignment,misc]
    _SAML_IMPORT_ERROR = exc


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class SsoError(Exception):
    """Base class for an enterprise-SSO failure."""


class SsoUnavailableError(SsoError):
    """Raised when the native SAML toolkit (python3-saml/xmlsec) is unavailable.

    The API maps this to a clean ``503`` ("SSO unavailable") — the assertion could
    not be validated because the signature-checking lib is not installed.
    """


class SsoConfigError(SsoError):
    """Raised when a workspace has no enabled/complete SSO connection."""


class SsoValidationError(SsoError):
    """Raised when a SAML response fails signature / condition / audience validation."""


class SsoReplayError(SsoError):
    """Raised when an already-processed assertion id is presented again (replay)."""


class SsoDomainError(SsoError):
    """Raised when the asserted email is missing or its domain is not allowed."""


# --------------------------------------------------------------------------- #
# Default role granted to a freshly-provisioned SSO user. ``viewer`` grants
# read access (jobs.read) under the Casbin policy; an admin can elevate later.
# --------------------------------------------------------------------------- #
SSO_DEFAULT_ROLE: str = rbac.ROLE_VIEWER


def saml_available() -> bool:
    """Return whether the native SAML toolkit is importable (xmlsec present)."""
    return OneLogin_Saml2_Auth is not None


# --------------------------------------------------------------------------- #
# Validated-assertion DTO + session grant
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ValidatedAssertion:
    """The result of a VALIDATED SAML assertion (output of the validator seam).

    Immutable. ``assertion_id`` is the IdP-assigned unique id of the assertion,
    used for REPLAY protection (an id seen twice is rejected). ``subject`` is the
    SAML ``NameID`` used to map to an :class:`ExternalIdentity`.
    """

    subject: str
    email: str
    assertion_id: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SsoGrant:
    """A session grant returned by :func:`process_acs` on a successful login.

    Immutable. ``is_new_user`` marks whether a brand-new ReelForge user was
    created (vs an existing account linked). The controller issues its own session
    token from this grant.
    """

    user_id: str
    workspace_id: str
    email: str
    external_identity_id: str
    role: str
    is_new_user: bool


# --------------------------------------------------------------------------- #
# Replay protection (processed-assertion-id cache)
# --------------------------------------------------------------------------- #
class ReplayCache(Protocol):
    """The replay-protection seam: remembers processed assertion ids."""

    def seen(self, assertion_id: str) -> bool: ...

    def add(self, assertion_id: str) -> None: ...


#: Replay-window TTL (seconds). A processed assertion id is remembered for at
#: least this long — comfortably past a typical SAML ``NotOnOrAfter`` (~5 min) —
#: so a replay is rejected for the entire validity window. It also bounds memory:
#: expired ids are pruned rather than accumulated forever.
_REPLAY_TTL_SECONDS: int = 3600


class InMemoryReplayCache:
    """Thread-safe, TTL-expiring in-memory processed-assertion-id cache.

    Suitable for a SINGLE process / tests only. Each id is remembered for
    ``ttl_seconds`` and pruned afterwards, so the set can never grow unbounded.
    In any MULTI-worker / multi-instance deployment this is NOT sufficient (each
    process has its own set, so a replay routed to a different worker slips
    through) — use :class:`RedisReplayCache` there via :func:`default_replay_cache`.
    """

    def __init__(self, ttl_seconds: int = _REPLAY_TTL_SECONDS) -> None:
        self._ttl_seconds = max(1, int(ttl_seconds))
        # assertion_id -> monotonic expiry deadline.
        self._seen: dict[str, float] = {}
        self._lock = Lock()

    def _prune(self, now: float) -> None:
        if not self._seen:
            return
        expired = [key for key, deadline in self._seen.items() if deadline <= now]
        for key in expired:
            self._seen.pop(key, None)

    def seen(self, assertion_id: str) -> bool:
        if not assertion_id:
            return False
        now = monotonic()
        with self._lock:
            self._prune(now)
            return assertion_id in self._seen

    def add(self, assertion_id: str) -> None:
        if not assertion_id:
            return
        now = monotonic()
        with self._lock:
            self._prune(now)
            self._seen[assertion_id] = now + self._ttl_seconds


class RedisReplayCache:
    """Shared, TTL-backed replay cache (multi-worker / multi-instance safe).

    Every processed assertion id is written to a shared Redis store under a
    namespaced key with a TTL past the assertion's validity window, so a replay
    that lands on ANY worker or instance within that window is rejected. The write
    uses ``SET key value NX EX ttl`` (atomic across processes). This is the store
    the ACS path should use in production — the in-memory cache is process-local.
    """

    def __init__(
        self,
        client: Any,
        *,
        ttl_seconds: int = _REPLAY_TTL_SECONDS,
        key_prefix: str = "reelforge:sso:replay",
    ) -> None:
        self._client = client
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._prefix = key_prefix

    def _key(self, assertion_id: str) -> str:
        return f"{self._prefix}:{assertion_id}"

    def seen(self, assertion_id: str) -> bool:
        if not assertion_id:
            return False
        return bool(self._client.exists(self._key(assertion_id)))

    def add(self, assertion_id: str) -> None:
        if not assertion_id:
            return
        # NX so a concurrent worker cannot clobber an existing marker; EX bounds
        # the key's lifetime to the replay window.
        self._client.set(self._key(assertion_id), b"1", nx=True, ex=self._ttl_seconds)


#: Process-wide default (in-memory) replay cache. Tests pass their own to keep
#: isolation; production resolves a shared store via :func:`default_replay_cache`.
_DEFAULT_REPLAY_CACHE: InMemoryReplayCache = InMemoryReplayCache()

#: Memoized resolution of the shared replay store (Redis when reachable, else the
#: in-memory fallback). Resolved once per process behind a lock.
_replay_cache_lock: Lock = Lock()
_resolved_replay_cache: "ReplayCache | None" = None


def _build_shared_replay_cache() -> "ReplayCache | None":
    """Return a shared Redis-backed replay cache, or ``None`` when unreachable.

    Reuses the process-wide Redis client already built for the rate limiter (same
    ``[app]`` config keys). Verifies reachability with a short ``PING`` so a
    misconfigured / down Redis degrades to the in-memory fallback instead of
    hanging or erroring the ACS path.
    """
    try:
        from app.services.ratelimit import _get_client

        client = _get_client()
        if client is None:
            return None
        client.ping()  # verify reachability; unreachable -> in-memory fallback
    except Exception as exc:  # noqa: BLE001 - any failure -> safe in-memory fallback
        logger.debug(f"sso replay cache: shared Redis unavailable ({exc}); using in-memory")
        return None
    return RedisReplayCache(client)


def default_replay_cache() -> "ReplayCache":
    """Resolve the process's default replay store (shared Redis or in-memory).

    Memoized: the first call decides and every later call returns the same store.
    Prefers a shared, TTL-backed Redis store (correct for multi-worker
    deployments) and falls back to the process-local :data:`_DEFAULT_REPLAY_CACHE`
    only when Redis is unavailable.
    """
    global _resolved_replay_cache
    if _resolved_replay_cache is not None:
        return _resolved_replay_cache
    with _replay_cache_lock:
        if _resolved_replay_cache is None:
            _resolved_replay_cache = _build_shared_replay_cache() or _DEFAULT_REPLAY_CACHE
    return _resolved_replay_cache


#: The validator seam type: (connection, saml_response, relay_state) -> assertion.
Validator = Callable[[Any, str, str], ValidatedAssertion]


# --------------------------------------------------------------------------- #
# The MOCKABLE, import-guarded SAML validator seam
# --------------------------------------------------------------------------- #
def _validate_saml_response(
    connection: Any, saml_response: str, relay_state: str = ""
) -> ValidatedAssertion:
    """Parse + VALIDATE a base64 SAMLResponse via python3-saml; return the assertion.

    This is the ONE place that requires the native ``xmlsec`` lib. Delegates ALL
    security-critical checks to python3-saml (``onelogin.saml2``): the XML
    signature against the IdP's X.509 cert, the audience/recipient, and the
    ``NotOnOrAfter`` conditions — this module never hand-rolls those checks.

    Raises :class:`SsoUnavailableError` when the toolkit is absent (the API maps
    it to 503) and :class:`SsoValidationError` when validation fails. On success
    returns the subject (NameID), email, attributes and the assertion id (for
    replay protection).
    """
    if not saml_available():
        raise SsoUnavailableError(
            f"SSO unavailable: python3-saml/xmlsec is not installed "
            f"({_SAML_IMPORT_ERROR})"
        )

    settings = _saml_settings(connection)
    req = {
        # SP-side request context. The ACS is the SP's own URL; the toolkit
        # validates the assertion's Recipient/Destination against it.
        "https": "on",
        "http_host": _host_from_url(connection.sp_acs_url),
        "script_name": _path_from_url(connection.sp_acs_url),
        "get_data": {},
        "post_data": {"SAMLResponse": saml_response, "RelayState": relay_state or ""},
    }
    try:
        auth = OneLogin_Saml2_Auth(req, old_settings=settings)
        auth.process_response()
        errors = auth.get_errors()
        if errors or not auth.is_authenticated():
            reason = auth.get_last_error_reason() or ", ".join(errors or [])
            raise SsoValidationError(f"SAML response failed validation: {reason}")
        subject = (auth.get_nameid() or "").strip()
        attributes = dict(auth.get_attributes() or {})
        email = _extract_email(subject, attributes)
        assertion_id = (auth.get_last_assertion_id() or "").strip()
    except SsoError:
        raise
    except Exception as exc:  # noqa: BLE001 - any toolkit failure -> validation error
        raise SsoValidationError(f"SAML response could not be validated: {exc}") from exc

    if not subject:
        raise SsoValidationError("SAML assertion carried no NameID subject")
    return ValidatedAssertion(
        subject=subject, email=email, assertion_id=assertion_id, attributes=attributes
    )


def _saml_settings(connection: Any) -> dict[str, Any]:
    """Build the python3-saml settings dict from a :class:`SSOConnection` row.

    The IdP signing cert is decrypted from ``idp_x509_cert_enc`` for signature
    verification. Raises :class:`SsoConfigError` when the connection is missing the
    IdP cert (a SAML connection cannot verify signatures without it).
    """
    cert = ""
    if connection.idp_x509_cert_enc:
        try:
            cert = crypto_tokens.decrypt(connection.idp_x509_cert_enc)
        except Exception as exc:  # noqa: BLE001 - undecryptable cert -> config error
            raise SsoConfigError(f"could not decrypt IdP certificate: {exc}") from exc
    if not cert:
        raise SsoConfigError("SAML connection is missing the IdP signing certificate")

    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": connection.sp_acs_url,
            "assertionConsumerService": {
                "url": connection.sp_acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
        },
        "idp": {
            "entityId": connection.idp_entity_id,
            "singleSignOnService": {
                "url": connection.idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": cert,
        },
        # Defense-in-depth against XML-signature-wrapping (XSW): REQUIRE the
        # individual assertion to be signed, not merely some signature somewhere in
        # the document (the message-signed-but-assertion-unsigned case is the exact
        # XSW target). Left un-set, python3-saml defaults both flags to False.
        "security": {
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "rejectUnsolicitedResponsesWithInResponseTo": False,
        },
    }


def _extract_email(subject: str, attributes: dict[str, Any]) -> str:
    """Pull the email from common SAML attribute spellings, else the NameID."""
    for key in (
        "email",
        "Email",
        "mail",
        "urn:oid:0.9.2342.19200300.100.1.3",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    ):
        value = attributes.get(key)
        if isinstance(value, (list, tuple)) and value:
            return str(value[0]).strip()
        if isinstance(value, str) and value.strip():
            return value.strip()
    # Fall back to the NameID when it looks like an email address.
    return subject.strip() if "@" in (subject or "") else ""


def _host_from_url(url: str) -> str:
    """Best-effort host extraction from a URL (empty on parse failure)."""
    from urllib.parse import urlparse

    try:
        return urlparse(url or "").netloc
    except Exception:  # noqa: BLE001 - defensive
        return ""


def _path_from_url(url: str) -> str:
    """Best-effort path extraction from a URL (defaults to '/')."""
    from urllib.parse import urlparse

    try:
        return urlparse(url or "").path or "/"
    except Exception:  # noqa: BLE001 - defensive
        return "/"


# --------------------------------------------------------------------------- #
# ACS: validate -> replay-protect -> domain check -> map to user -> grant
# --------------------------------------------------------------------------- #
def process_acs(
    session: Any,
    workspace_id: str,
    saml_response: str,
    relay_state: str = "",
    *,
    validator: Validator | None = None,
    replay_cache: ReplayCache | None = None,
    actor_ip: str | None = None,
) -> SsoGrant:
    """Process an IdP SAMLResponse at the SP ACS and return a session grant.

    Order (each a hard gate):

    1. **Connection.** Resolve the workspace's enabled SSO connection or raise
       :class:`SsoConfigError` (tenant-scoped — a connection authenticates into
       its own workspace only).
    2. **Validate.** Run the assertion through the validator SEAM (default
       :func:`_validate_saml_response`, which delegates signature/condition checks
       to python3-saml). Tests inject a validated assertion here — no xmlsec.
    3. **Replay.** Reject an assertion id already in the processed-id cache
       (:class:`SsoReplayError`); otherwise remember it.
    4. **Domain.** The asserted email MUST be present and, when the workspace's
       :class:`SecurityPolicy` sets ``allowed_email_domains``, its domain MUST be
       in that list (:class:`SsoDomainError`).
    5. **Map.** Match/create an :class:`ExternalIdentity` by ``(workspace_id,
       idp_subject)`` — linking an existing user with that email or creating a new
       one — and ensure workspace membership. An audit row is written.

    Returns an :class:`SsoGrant` the controller turns into a session token.
    """
    normalized_ws = (workspace_id or "").strip()
    if not normalized_ws:
        raise SsoConfigError("workspace_id must be a non-empty string")

    connection = SSOConnectionRepository(session).get_for_workspace(normalized_ws)
    if connection is None:
        raise SsoConfigError(f"workspace {normalized_ws} has no SSO connection")
    if not connection.enabled:
        raise SsoConfigError(f"SSO is not enabled for workspace {normalized_ws}")

    validate = validator or _validate_saml_response
    assertion = validate(connection, saml_response, relay_state)

    # Replay protection — an assertion id may be consumed at most once. A MISSING
    # id is a hard validation failure (not a silent skip): without it we cannot
    # enforce replay protection, so we must never issue a session.
    assertion_id = (assertion.assertion_id or "").strip()
    if not assertion_id:
        raise SsoValidationError(
            "SAML assertion carried no id; replay protection cannot be enforced"
        )
    cache = replay_cache or default_replay_cache()
    if cache.seen(assertion_id):
        raise SsoReplayError(f"assertion {assertion_id} has already been processed")
    cache.add(assertion_id)

    email = (assertion.email or "").strip().lower()
    if not email:
        raise SsoDomainError("SAML assertion did not carry an email address")
    _enforce_email_domain(session, normalized_ws, email)

    grant = _map_to_user(
        session,
        workspace_id=normalized_ws,
        subject=assertion.subject.strip(),
        email=email,
        connection=connection,
    )

    audit.record(
        session,
        actor_user_id=grant.user_id,
        action="sso.provisioned" if grant.is_new_user else "sso.login",
        workspace_id=normalized_ws,
        target_type="user",
        target_id=grant.user_id,
        metadata={
            "idp_subject": assertion.subject,
            "email": email,
            "new_user": grant.is_new_user,
        },
        ip=actor_ip,
    )
    return grant


def _enforce_email_domain(session: Any, workspace_id: str, email: str) -> None:
    """Reject an email whose domain is not in the workspace's allowlist.

    An empty / unset ``allowed_email_domains`` means any domain is allowed. Raises
    :class:`SsoDomainError` when the domain is disallowed or the email is malformed.
    """
    policy = SecurityPolicyRepository(session).get(workspace_id)
    allowed = list(getattr(policy, "allowed_email_domains", None) or []) if policy else []
    if not allowed:
        return
    if "@" not in email:
        raise SsoDomainError(f"malformed email address: {email!r}")
    domain = email.rsplit("@", 1)[-1].strip().lower()
    allowed_lower = {str(d).strip().lower() for d in allowed if str(d).strip()}
    if domain not in allowed_lower:
        raise SsoDomainError(
            f"email domain {domain!r} is not permitted for this workspace"
        )


def _map_to_user(
    session: Any, *, workspace_id: str, subject: str, email: str, connection: Any = None
) -> SsoGrant:
    """Resolve/create the :class:`ExternalIdentity` + user for a validated subject.

    Match key is ``(workspace_id, idp_subject)`` (tenant-scoped). When it exists
    the linked user is returned (email refreshed if changed). Otherwise a brand-new
    workspace-isolated user is provisioned, OR — only when the link is AUTHORIZED
    (see :func:`_existing_link_allowed`) — an existing ReelForge user with that
    email is adopted; a new :class:`ExternalIdentity` is inserted
    (``provisioned=True``) and workspace membership ensured at
    :data:`SSO_DEFAULT_ROLE`.

    SECURITY (cross-tenant account takeover): the assertion is validly signed by
    THIS workspace's own configured IdP cert, which the workspace admin controls.
    That is proof the admin can sign for their own IdP — NOT proof the IdP owns the
    asserted email's domain. So we must NEVER adopt a pre-existing GLOBAL account
    (``User.email`` is unique platform-wide) by self-asserted email alone; doing so
    would let any workspace admin mint a session for ``victim@othertenant.com``.
    """
    identities = ExternalIdentityRepository(session)
    existing = identities.get_by_subject(workspace_id, subject)
    if existing is not None:
        if email and (existing.email or "").lower() != email:
            identities.update_email(existing.id, workspace_id, email)
        if not existing.provisioned:
            identities.set_provisioned(existing.id, workspace_id, True)
        role = _membership_role(session, workspace_id, existing.user_id)
        return SsoGrant(
            user_id=existing.user_id,
            workspace_id=workspace_id,
            email=email or existing.email,
            external_identity_id=existing.id,
            role=role,
            is_new_user=False,
        )

    user, is_new_user = _find_or_create_user(session, email)
    if not is_new_user and not _existing_link_allowed(
        session, workspace_id, connection, user.id, email
    ):
        # The email resolved to a PRE-EXISTING global account that this workspace
        # has not proven it may speak for. Refuse — never bind a foreign account to
        # this IdP identity, never issue a session for it, never join it to this
        # workspace. (A genuinely new email JIT-provisions a fresh isolated user.)
        raise SsoDomainError(
            "SSO cannot link this assertion to an existing ReelForge account: the "
            "account is not a member of this workspace and the email domain has not "
            "been verified as owned by this workspace's IdP connection"
        )
    identity = identities.create(
        user_id=user.id,
        workspace_id=workspace_id,
        idp_subject=subject,
        email=email,
        provisioned=True,
    )
    role = _ensure_membership(session, workspace_id, user.id)
    return SsoGrant(
        user_id=user.id,
        workspace_id=workspace_id,
        email=email,
        external_identity_id=identity.id,
        role=role,
        is_new_user=is_new_user,
    )


def _find_or_create_user(session: Any, email: str) -> tuple[User, bool]:
    """Return the existing user for ``email`` (linking SSO) or create a new one."""
    from sqlalchemy import func, select

    stmt = select(User).where(func.lower(User.email) == email.lower()).limit(1)
    user = session.execute(stmt).scalars().first()
    if user is not None:
        return user, False
    user = User(email=email, display_name=email.split("@", 1)[0])
    session.add(user)
    session.flush()  # populate user.id without ending the transaction
    return user, True


def _existing_link_allowed(
    session: Any, workspace_id: str, connection: Any, user_id: str, email: str
) -> bool:
    """Whether binding an SSO identity to a PRE-EXISTING account is authorized.

    Adopting an existing global :class:`User` by self-asserted email is a
    cross-tenant account-takeover vector, so it is permitted ONLY when the link is
    provably legitimate:

    1. **Already a member.** The account is already a member of ``workspace_id``
       (it was invited / consented in out-of-band), so attaching its IdP identity
       is expected — this is a real employee enabling SSO on their own account.
    2. **Verified domain.** The email's domain is in the connection's
       ``verified_domains`` — an ADMIN-VERIFIED, out-of-band proof of domain
       ownership (NOT the self-asserted, workspace-editable
       ``allowed_email_domains`` policy, which is only an inbound filter).

    Anything else (e.g. ``victim@othertenant.com`` who is a stranger to this
    workspace) is refused.
    """
    if WorkspaceRepository(session).get_membership(workspace_id, user_id) is not None:
        return True

    domain = email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""
    verified = {
        str(d).strip().lower()
        for d in (getattr(connection, "verified_domains", None) or [])
        if str(d).strip()
    }
    return bool(domain) and domain in verified


def _membership_role(session: Any, workspace_id: str, user_id: str) -> str:
    """Return the user's role in the workspace, ensuring membership exists."""
    membership = WorkspaceRepository(session).get_membership(workspace_id, user_id)
    if membership is not None:
        return membership.role
    return _ensure_membership(session, workspace_id, user_id)


def _ensure_membership(session: Any, workspace_id: str, user_id: str) -> str:
    """Ensure a workspace membership at :data:`SSO_DEFAULT_ROLE`; return the role.

    Inserts a :class:`WorkspaceMember` directly (bypassing the legacy-role
    validation in :meth:`WorkspaceRepository.add_member`) so an SSO-provisioned
    user gets a real Casbin role (``viewer``) rather than the policy-less legacy
    ``member`` token. Idempotent — an existing membership keeps its current role.
    """
    existing = WorkspaceRepository(session).get_membership(workspace_id, user_id)
    if existing is not None:
        return existing.role
    member = WorkspaceMember(
        workspace_id=workspace_id, user_id=user_id, role=SSO_DEFAULT_ROLE
    )
    session.add(member)
    session.flush()
    return SSO_DEFAULT_ROLE


# --------------------------------------------------------------------------- #
# Connection configuration (RBAC gated at the API)
# --------------------------------------------------------------------------- #
def configure_connection(
    session: Any,
    workspace_id: str,
    *,
    protocol: str = "saml",
    idp_entity_id: str = "",
    idp_sso_url: str = "",
    idp_x509_cert: str = "",
    sp_acs_url: str = "",
    oidc_client_id: str = "",
    oidc_client_secret: str = "",
    enabled: bool = False,
    actor_user_id: str | None = None,
    actor_ip: str | None = None,
) -> Any:
    """Create/update a workspace's SSO connection (encrypting secrets); audit it.

    The IdP signing cert (SAML) and OIDC client secret are encrypted via
    :mod:`app.services.crypto_tokens` before they reach the DB — a plaintext
    secret is never stored. RBAC (``workspace.settings``) is enforced at the API,
    not here. Returns the persisted :class:`SSOConnection`.
    """
    cert_enc = crypto_tokens.encrypt(idp_x509_cert) if idp_x509_cert else None
    secret_enc = (
        crypto_tokens.encrypt(oidc_client_secret) if oidc_client_secret else None
    )
    connection = SSOConnectionRepository(session).upsert(
        workspace_id=workspace_id,
        protocol=protocol,
        idp_entity_id=idp_entity_id,
        idp_sso_url=idp_sso_url,
        idp_x509_cert_enc=cert_enc,
        sp_acs_url=sp_acs_url,
        oidc_client_id=oidc_client_id or None,
        oidc_client_secret_enc=secret_enc,
        enabled=enabled,
    )
    if actor_user_id:
        audit.record(
            session,
            actor_user_id=actor_user_id,
            action="sso.configured",
            workspace_id=workspace_id,
            target_type="sso_connection",
            target_id=connection.id,
            metadata={"protocol": connection.protocol, "enabled": connection.enabled},
            ip=actor_ip,
        )
    return connection


def get_connection(session: Any, workspace_id: str) -> Any | None:
    """Return the workspace's SSO connection, or ``None`` when unset."""
    return SSOConnectionRepository(session).get_for_workspace(workspace_id)


def rotate_certificate(
    session: Any,
    workspace_id: str,
    new_cert: str,
    *,
    actor_user_id: str | None = None,
    actor_ip: str | None = None,
) -> Any:
    """Re-encrypt + store a fresh IdP signing certificate; audit the rotation.

    Raises :class:`SsoConfigError` when the workspace has no connection or the new
    cert is blank (a rotation must not clear the signing cert). Returns the row.
    """
    if not (new_cert or "").strip():
        raise SsoConfigError("new certificate must be a non-empty string")
    repo = SSOConnectionRepository(session)
    connection = repo.get_for_workspace(workspace_id)
    if connection is None:
        raise SsoConfigError(f"workspace {workspace_id} has no SSO connection")
    connection = repo.upsert(
        workspace_id=workspace_id,
        protocol=connection.protocol,
        idp_entity_id=connection.idp_entity_id,
        idp_sso_url=connection.idp_sso_url,
        idp_x509_cert_enc=crypto_tokens.encrypt(new_cert),
        sp_acs_url=connection.sp_acs_url,
        oidc_client_id=connection.oidc_client_id,
        oidc_client_secret_enc=connection.oidc_client_secret_enc,
        enabled=connection.enabled,
    )
    if actor_user_id:
        audit.record(
            session,
            actor_user_id=actor_user_id,
            action="sso.cert_rotated",
            workspace_id=workspace_id,
            target_type="sso_connection",
            target_id=connection.id,
            metadata={},
            ip=actor_ip,
        )
    return connection


# --------------------------------------------------------------------------- #
# SP-initiated login redirect (pure-python; no xmlsec)
# --------------------------------------------------------------------------- #
def build_login_redirect(connection: Any, relay_state: str = "") -> str:
    """Build the SP-initiated redirect URL that sends the browser to the IdP.

    Constructs a minimal (unsigned) SAML ``AuthnRequest``, DEFLATE-compresses and
    base64-encodes it per the HTTP-Redirect binding, and appends it (plus the
    ``RelayState``) to the IdP SSO URL. This is pure-python (zlib + base64) so it
    works WITHOUT the native ``xmlsec`` lib — signing is only required when the IdP
    demands signed requests, which is a later enhancement.

    Raises :class:`SsoConfigError` when the connection is disabled or missing its
    IdP SSO URL.
    """
    if connection is None:
        raise SsoConfigError("no SSO connection to build a login redirect for")
    if not connection.enabled:
        raise SsoConfigError("SSO is not enabled for this workspace")
    sso_url = (connection.idp_sso_url or "").strip()
    if not sso_url:
        raise SsoConfigError("SSO connection is missing the IdP SSO URL")

    authn_request = _build_authn_request(connection)
    # HTTP-Redirect binding: raw-DEFLATE then base64 (no zlib header/trailer).
    deflated = _deflate(authn_request.encode("utf-8"))
    encoded = base64.b64encode(deflated).decode("ascii")
    separator = "&" if "?" in sso_url else "?"
    url = f"{sso_url}{separator}SAMLRequest={quote(encoded)}"
    if relay_state:
        url = f"{url}&RelayState={quote(relay_state)}"
    return url


def _build_authn_request(connection: Any) -> str:
    """Build a minimal SAML 2.0 ``AuthnRequest`` XML string (unsigned)."""
    import secrets
    from datetime import datetime, timezone

    request_id = "_" + secrets.token_hex(16)
    issue_instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    acs = connection.sp_acs_url or ""
    destination = connection.idp_sso_url or ""
    # SP entity id defaults to the ACS URL (mirrors _saml_settings).
    issuer = connection.sp_acs_url or ""
    return (
        '<samlp:AuthnRequest '
        'xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{request_id}" Version="2.0" '
        f'IssueInstant="{issue_instant}" '
        'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'AssertionConsumerServiceURL="{acs}" '
        f'Destination="{destination}">'
        f'<saml:Issuer>{issuer}</saml:Issuer>'
        '<samlp:NameIDPolicy '
        'Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress" '
        'AllowCreate="true"/>'
        '</samlp:AuthnRequest>'
    )


def _deflate(data: bytes) -> bytes:
    """Raw-DEFLATE compress ``data`` (no zlib header/checksum) for HTTP-Redirect."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    return compressor.compress(data) + compressor.flush()


__all__ = [
    "InMemoryReplayCache",
    "RedisReplayCache",
    "ReplayCache",
    "SsoConfigError",
    "SsoDomainError",
    "SsoError",
    "SsoGrant",
    "SsoReplayError",
    "SsoUnavailableError",
    "SsoValidationError",
    "ValidatedAssertion",
    "build_login_redirect",
    "configure_connection",
    "default_replay_cache",
    "get_connection",
    "process_acs",
    "rotate_certificate",
    "saml_available",
]
