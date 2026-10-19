"""Store-friendly device onboarding for the ReelForge mobile client.

The endpoint exchanges a high-entropy, SecureStore-backed install id for a
server-derived API credential. The install id is not a credential by itself:
the raw key is an HMAC produced with a server-only secret and only its SHA-256
digest is persisted. Repeating the exchange on the same installation restores
the same account without storing recoverable secrets in the database.

Identity linking: when the app is signed in (Apple / Google via Supabase Auth)
it sends the Supabase access token as ``Authorization: Bearer <token>`` (or
``identity_token`` in the body). The verified identity then owns the account:

* first link on a device with no identity account yet -> the device account is
  ADOPTED by the identity (its credits and reels carry over);
* the identity already has an account (another phone, a reinstall, or the web
  app with the same verified email) -> this install's device key is attached to
  THAT account, so every device of one person shares one account.

Free-grant gate (MN3): a new anonymous device account starts with 0 credits.
Its one-time free reels are granted when the install passes App Attest (iOS)
or Play Integrity (Android) — see :mod:`app.services.abuse.device_attest` and
``POST /auth/device/challenge`` — or when it links a verified identity whose
normalized email has not funded another account's free reels. New anonymous
accounts are capped per client IP and per /24 per day (durable, in the DB),
and every call is rate limited per IP and per /24 (Redis, with an in-process
fallback), so random install ids cannot farm accounts or credits.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

from fastapi import Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.controllers.v1.base import new_router
from app.core.launch.policy import require_signup_enabled
from app.models.db.base import get_session
from app.models.db.models import User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services.abuse import device_attest, grant_markers
from app.services.billing.card_check import has_signup_grant
from app.services.billing.plans import SIGNUP_GRANT
from app.utils import utils

router = new_router()

_INSTALL_ID = re.compile(r"^[A-Za-z0-9._:-]{20,200}$")
_PLATFORMS = {"ios", "android"}


class DeviceAttestation(BaseModel):
    """Proof the install is the real app on a real device (MN3)."""

    challenge: str = Field(min_length=16, max_length=128)
    # iOS App Attest: base64 key id + base64 CBOR attestation object.
    key_id: str | None = Field(default=None, max_length=256)
    attestation: str | None = Field(default=None, max_length=16384)
    # Android Play Integrity token (nonce = challenge).
    integrity_token: str | None = Field(default=None, max_length=16384)


class DeviceSessionRequest(BaseModel):
    install_id: str = Field(min_length=20, max_length=200)
    platform: str
    # Optional Supabase access token (alternative to the Authorization header).
    identity_token: str | None = Field(default=None, max_length=8192)
    # Same token under the field name the mobile client sends.
    supabase_access_token: str | None = Field(default=None, max_length=8192)
    # Optional device attestation; unlocks the free reels of a device account.
    attestation: DeviceAttestation | None = None


class DeviceChallengeRequest(BaseModel):
    install_id: str = Field(min_length=20, max_length=200)
    platform: str


def _device_secret(request_id: str) -> bytes:
    value = os.getenv("REELFORGE_DEVICE_AUTH_SECRET", "").strip()
    if len(value) < 32:
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=(
                f"{request_id}: device onboarding is unavailable; "
                "configure REELFORGE_DEVICE_AUTH_SECRET with at least 32 characters"
            ),
        )
    return value.encode("utf-8")


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", "") or "device-auth")


def _validated_install(request_id: str, install_id: str, platform: str) -> tuple[str, str]:
    install_id = install_id.strip()
    platform = platform.strip().lower()
    if platform not in _PLATFORMS:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: platform must be ios or android",
        )
    if not _INSTALL_ID.fullmatch(install_id):
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: install_id has an invalid format",
        )
    return install_id, platform


@router.post("/auth/device/challenge")
def create_device_challenge(request: Request, body: DeviceChallengeRequest):
    """A 10-minute challenge the app attests (App Attest / Play Integrity nonce)."""
    request_id = _request_id(request)
    device_attest.enforce_request_budget(request_id, device_attest.client_ip(request))
    install_id, platform = _validated_install(request_id, body.install_id, body.platform)
    challenge = device_attest.issue_challenge(_device_secret(request_id), platform, install_id)
    return utils.get_response(
        status=200,
        data={
            "challenge": challenge,
            "expires_in": device_attest.CHALLENGE_TTL_S,
            "available": device_attest.availability()[platform],
        },
        message="challenge ready",
    )


def _refuse_account_flood(session, request_id: str, ip: str) -> None:
    """429 once this address or its /24 made today's quota of new accounts."""
    if grant_markers.device_account_quota_left(session, ip):
        return
    raise HttpException(
        task_id=request_id,
        status_code=429,
        message=(
            "Too many new accounts were made from this network today. "
            "Sign in with Apple or Google to continue."
        ),
        data={"code": "device_account_limit"},
    )


def _settle_device_grant(session, user, *, platform, install_id, attestation, secret, ip) -> str:
    """Grant a device account's free reels once it attests. Returns the status.

    ``granted`` (now or earlier), ``pending`` (no valid attestation yet) or
    ``withheld`` (this device already funded another account's free reels).
    """
    if not device_attest.grant_gate_enabled():
        return "granted" if has_signup_grant(session, user.id) else "pending"
    credits = CreditRepository(session)
    credits._locked_balance(user.id)  # noqa: SLF001 - serialize racing grants
    if has_signup_grant(session, user.id):
        return "granted"
    payload = attestation.model_dump() if attestation is not None else None
    result = device_attest.verify(secret, platform, install_id, payload)
    if not result.passed:
        return "pending"
    signals = {grant_markers.KIND_ATTEST: result.device_key}
    if not grant_markers.grant_allowed(session, user.id, signals):
        return "withheld"
    credits.grant(user.id, SIGNUP_GRANT, "mobile_device_signup")
    grant_markers.record_grant(session, user.id, signals, ip=ip)
    return "granted"


def _grant_identity_signup(session, user, claims, ip: str) -> bool:
    """Free reels for a verified identity whose normalized email is unused."""
    from app.core import supabase_auth

    if has_signup_grant(session, user.id):
        return False
    # Only a provider-verified email counts as a verified identity; a bare
    # Supabase subject could be minted in bulk.
    signals = grant_markers.email_signals(supabase_auth.verified_email(claims))
    if not any(signals.values()) or not grant_markers.grant_allowed(session, user.id, signals):
        return False
    CreditRepository(session).grant(user.id, SIGNUP_GRANT, "mobile_identity_signup")
    grant_markers.record_grant(session, user.id, signals, ip=ip)
    return True


@router.post("/auth/device")
def create_device_session(request: Request, body: DeviceSessionRequest):
    request_id = _request_id(request)
    ip = device_attest.client_ip(request)
    device_attest.enforce_request_budget(request_id, ip)
    install_id, platform = _validated_install(request_id, body.install_id, body.platform)
    secret = _device_secret(request_id)

    digest = hmac.new(
        secret,
        f"reelforge-device-v1:{platform}:{install_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    token = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    raw_key = f"rf_device_{token}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    account_key = hashlib.sha256(
        f"{platform}:{install_id}".encode("utf-8")
    ).hexdigest()[:32]
    email = f"device+{account_key}@accounts.reelforge.app"

    claims = _identity_claims(request, body, request_id)

    with get_session() as session:
        if claims is not None:
            return _linked_session(
                session, claims, raw_key, key_hash, email, platform, request_id, ip=ip
            )
        # An install already linked to an identity keeps resolving to it.
        linked = _user_for_device_key(session, key_hash)
        if linked is not None:
            return _session_response(session, linked, raw_key, created=False)
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        created = user is None
        if user is None:
            # Web browsers (which always send Origin) no longer get guest
            # accounts: the web requires a real sign-up plus the card check.
            # Native apps send no Origin and keep their device onboarding.
            _refuse_browser_guest(request, request_id)
            # Provisioning a brand-new account is a public signup; returning an
            # existing device account below is a login and stays open in pilot.
            require_signup_enabled(request_id)
            _refuse_account_flood(session, request_id, ip)
            user = User(
                email=email,
                display_name="ReelForge Creator",
                api_key_hash=key_hash,
            )
            session.add(user)
            session.flush()
            grant_markers.record_device_account(session, user.id, ip)
            if not device_attest.grant_gate_enabled():
                # Owner rollback switch (MENIVOR_DEVICE_GRANT_GATE=off).
                CreditRepository(session).grant(
                    user.id,
                    SIGNUP_GRANT,
                    "mobile_device_signup",
                )
            _rally_signed_up(user, "device")
        elif not hmac.compare_digest(str(user.api_key_hash or ""), key_hash):
            user.api_key_hash = key_hash
            session.flush()

        grant = _settle_device_grant(
            session, user, platform=platform, install_id=install_id,
            attestation=body.attestation, secret=secret, ip=ip,
        )
        return _session_response(
            session, user, raw_key, created=created, grant=grant, platform=platform
        )


def _refuse_browser_guest(request: Request, request_id: str) -> None:
    """403 for a NEW device account requested from a web page (has Origin)."""
    if not str(request.headers.get("origin") or "").strip():
        return
    raise HttpException(
        task_id=request_id,
        status_code=403,
        message=(
            "Guest sessions are not available on the web. Create a free account "
            "at https://menivor.com/sign-up to make reels."
        ),
        data={"code": "web_guest_disabled", "sign_up_url": "https://menivor.com/sign-up"},
    )


def _session_response(
    session, user, raw_key: str, *, created: bool, linked: bool = False,
    grant: str | None = None, platform: str = "",
):
    credits = CreditRepository(session).balance(user.id)
    if grant is None:
        grant = "granted" if has_signup_grant(session, user.id) else "none"
    return utils.get_response(
        status=200,
        data={
            "api_key": raw_key,
            "created": created,
            "credits": credits,
            "user_id": user.id,
            "linked": linked,
            # granted | pending (attest or sign in to unlock) | withheld | none
            "free_credits": {
                "status": grant,
                "amount": int(SIGNUP_GRANT),
                "attestation_available": bool(
                    device_attest.availability().get(platform, False)
                ) if platform else False,
            },
        },
        message="device session ready",
    )


def _identity_claims(request: Request, body: DeviceSessionRequest, request_id: str):
    """Verified Supabase claims when the app sent a sign-in token, else ``None``."""
    from app.core import clerk, supabase_auth

    token = (
        (body.identity_token or "").strip()
        or (body.supabase_access_token or "").strip()
        or clerk.extract_bearer_token(request)
    )
    if not token:
        return None
    if not supabase_auth.is_configured():
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=(
                f"{request_id}: account sign-in linking is unavailable; "
                "configure SUPABASE_URL"
            ),
        )
    try:
        return supabase_auth.verify_supabase_jwt(token)
    except supabase_auth.SupabaseUnavailableError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: account sign-in is temporarily unavailable",
        ) from exc
    except supabase_auth.SupabaseAuthError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=401,
            message=f"{request_id}: invalid sign-in token",
        ) from exc


def _user_for_device_key(session, key_hash: str):
    """The user a device key already resolves to (legacy slot, then linked key)."""
    from app.models.db.repositories import UserApiKeyRepository

    user = session.execute(
        select(User).where(User.api_key_hash == key_hash)
    ).scalar_one_or_none()
    if user is not None:
        return user
    row = UserApiKeyRepository(session).get_by_hash(key_hash)
    return session.get(User, row.user_id) if row is not None else None


def _attach_device_key(session, user, key_hash: str, platform: str) -> None:
    """Make this install's device key authenticate as ``user`` (idempotent)."""
    from app.models.db.models import UserApiKey
    from app.models.db.repositories import UserApiKeyRepository

    existing = session.execute(
        select(UserApiKey).where(UserApiKey.key_hash == key_hash)
    ).scalar_one_or_none()
    if existing is not None:
        existing.user_id = user.id
        existing.revoked = False
    else:
        row = UserApiKeyRepository(session).create(
            user.id, f"Mobile device ({platform})", key_hash, "rf_device"
        )
        # First-party app traffic: no per-minute throttle, no monthly cap.
        row.rate_limit_per_min = 0
    session.flush()


def _linked_session(session, claims, raw_key, key_hash, device_email, platform, request_id, *, ip=""):
    """Resolve the identity account for this install and bind the device key to it."""
    from app.core import supabase_auth

    identity_user = supabase_auth.find_identity_user(session, claims)
    device_user = session.execute(
        select(User).where(User.email == device_email)
    ).scalar_one_or_none()
    created = False

    if identity_user is None and device_user is not None:
        # First sign-in on this phone: the identity adopts the device account,
        # keeping its credits, reels and settings.
        device_user.email = supabase_auth.identity_email(claims)
        name = supabase_auth.display_name(claims)
        if name:
            device_user.display_name = name
        device_user.api_key_hash = key_hash
        session.flush()
        # A verified identity unlocks the device account's free reels (once).
        _grant_identity_signup(session, device_user, claims, ip)
        return _session_response(session, device_user, raw_key, created=False, linked=True)

    if identity_user is None:
        require_signup_enabled(request_id)
        identity_user = User(
            email=supabase_auth.identity_email(claims),
            display_name=supabase_auth.display_name(claims) or "ReelForge Creator",
        )
        session.add(identity_user)
        session.flush()
        _grant_identity_signup(session, identity_user, claims, ip)
        _rally_signed_up(identity_user, "mobile_identity")
        created = True

    if device_user is not None and device_user.id != identity_user.id:
        # The device key must stop resolving to the anonymous device account.
        if device_user.api_key_hash == key_hash:
            device_user.api_key_hash = ""
    if identity_user.api_key_hash != key_hash:
        _attach_device_key(session, identity_user, key_hash, platform)
    return _session_response(session, identity_user, raw_key, created=created, linked=True)


# --------------------------------------------------------------------------- #
# POST /auth/device/claim — fold a web/mobile GUEST device account into the
# signed-in account (web GuestClaimCard). The caller authenticates with their
# real credential (Clerk/Supabase bearer) and proves guest ownership with the
# install id + device key the browser holds.
# --------------------------------------------------------------------------- #
_DEVICE_EMAIL_SUFFIX = "@accounts.reelforge.app"


class DeviceClaimRequest(BaseModel):
    install_id: str = Field(min_length=20, max_length=200)
    device_api_key: str = Field(min_length=16, max_length=512)


def _device_key_matches_install(install_id: str, key_hash: str, request_id: str) -> bool:
    secret = _device_secret(request_id)
    for platform in sorted(_PLATFORMS):
        digest = hmac.new(
            secret,
            f"reelforge-device-v1:{platform}:{install_id}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        token = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        candidate = hashlib.sha256(f"rf_device_{token}".encode("utf-8")).hexdigest()
        if hmac.compare_digest(candidate, key_hash):
            return True
    return False


@router.post("/auth/device/claim")
def claim_device_account(request: Request, body: DeviceClaimRequest):
    """Move a guest device account's reels (and purchased credits) to the caller."""
    from app.core.auth.principal import resolve_principal
    from app.models.db.models import Job, UserApiKey

    request_id = _request_id(request)
    install_id = body.install_id.strip()
    raw_key = body.device_api_key.strip()
    if not _INSTALL_ID.fullmatch(install_id) or not raw_key.startswith("rf_device_"):
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: invalid guest session",
        )
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    if not _device_key_matches_install(install_id, key_hash, request_id):
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: guest key does not belong to this install",
        )

    with get_session() as session:
        owner = resolve_principal(request, session, request_id)
        if str(owner.email or "").endswith(_DEVICE_EMAIL_SUFFIX):
            raise HttpException(
                task_id=request_id,
                status_code=403,
                message=f"{request_id}: sign in to a real account before moving guest work",
            )
        guest = session.execute(
            select(User).where(User.api_key_hash == key_hash)
        ).scalar_one_or_none()
        if guest is None or guest.id == owner.id:
            # Already claimed (or linked): nothing left to move.
            return utils.get_response(
                status=200, data={"moved_jobs": 0, "moved_credits": 0}, message="nothing to move"
            )
        if not str(guest.email or "").endswith(_DEVICE_EMAIL_SUFFIX):
            raise HttpException(
                task_id=request_id,
                status_code=403,
                message=f"{request_id}: this session is not a guest account",
            )

        jobs = list(session.execute(select(Job).where(Job.user_id == guest.id)).scalars())
        for job in jobs:
            job.user_id = owner.id

        credits = CreditRepository(session)
        balance = credits.balance(guest.id)
        # The guest's unspent free signup grant is not transferable (it would let
        # one person farm grants across throwaway guest sessions); anything above
        # it (referral rewards, earlier purchases) moves with the reels. A guest
        # that never received the grant (MN3 gate) keeps nothing back.
        free = SIGNUP_GRANT if has_signup_grant(session, guest.id) else 0
        moved_credits = max(0, balance - free)
        if moved_credits > 0:
            credits.debit(guest.id, moved_credits, None, "guest_claim_out")
            credits.grant(owner.id, moved_credits, "guest_claim_in")

        # The browser's device key must stop resolving to the emptied guest.
        guest.api_key_hash = ""
        for row in session.execute(
            select(UserApiKey).where(UserApiKey.key_hash == key_hash)
        ).scalars():
            row.revoked = True
        session.flush()
        return utils.get_response(
            status=200,
            data={"moved_jobs": len(jobs), "moved_credits": moved_credits},
            message="guest work moved",
        )


def _rally_signed_up(user, method: str) -> None:
    """Best-effort Rally ``signed_up`` event (no-op unless RALLY_EVENTS_KEY is set)."""
    try:
        from app.integrations.rally import track_signed_up

        track_signed_up(str(user.id), getattr(user, "email", None), method=method)
    except Exception as exc:  # noqa: BLE001 - lifecycle events never block sign-in
        from loguru import logger

        logger.debug(f"rally signed_up skipped: {exc}")
