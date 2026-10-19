"""Resolve one authenticated ReelForge principal from Supabase, Clerk or API keys."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import resolve_user_by_api_key
from app.models.db.models import User
from app.models.exception import HttpException


def resolve_principal(request: Request, session: Any, request_id: str):
    """Resolve bearer auth (Supabase mobile, then Clerk web), then API credentials."""
    user = resolve_supabase_principal(request, session, request_id)
    if user is not None:
        return user
    user = resolve_clerk_principal(request, session, request_id)
    if user is not None:
        return user

    api_key = base.get_api_key(request)
    if not api_key:
        raise HttpException(
            task_id=request_id,
            status_code=401,
            message=f"{request_id}: missing x-api-key header",
        )
    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    user = session.query(User).filter(User.api_key_hash == key_hash).first()
    if user is None:
        user = resolve_user_by_api_key(session, api_key, request_id)
    if user is None:
        raise HttpException(
            task_id=request_id,
            status_code=401,
            message=f"{request_id}: invalid api key",
        )
    return user


def resolve_supabase_principal(request: Request, session: Any, request_id: str):
    """Resolve a verified Supabase (mobile sign-in) bearer, or ``None`` for fallback.

    Only tokens issued by Supabase Auth are handled here; any other bearer
    (Clerk) falls through untouched.
    """
    try:
        from app.core import clerk, supabase_auth
    except Exception as exc:  # noqa: BLE001 - optional bridge must not crash startup
        logger.debug(f"supabase bridge unavailable, request_id: {request_id}: {exc}")
        return None
    if not supabase_auth.is_configured():
        return None
    token = clerk.extract_bearer_token(request)
    if not token or not supabase_auth.looks_like_supabase_token(token):
        return None
    try:
        claims = supabase_auth.verify_supabase_jwt(token)
    except supabase_auth.SupabaseUnavailableError as exc:
        # Fail closed, but say it is our side: the auth project's keys are unreachable.
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: sign-in is temporarily unavailable, try again shortly",
        ) from exc
    except supabase_auth.SupabaseAuthError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=401,
            message=f"{request_id}: invalid bearer token: {exc}",
        ) from exc
    return get_or_create_supabase_user(session, claims, request_id)


def get_or_create_supabase_user(session: Any, claims: dict, request_id: str):
    """Map verified Supabase claims to one stable ``User`` (linking by verified email)."""
    from app.core import supabase_auth

    user = supabase_auth.find_identity_user(session, claims)
    if user is not None:
        return user
    from app.core.launch.policy import require_signup_enabled

    # Only a provider-VERIFIED email can redeem a private-beta approval.
    require_signup_enabled(
        request_id, session=session, verified_email=supabase_auth.verified_email(claims)
    )
    user = User(
        email=supabase_auth.identity_email(claims),
        display_name=supabase_auth.display_name(claims),
    )
    session.add(user)
    session.flush()
    try:
        from app.models.db.repositories import CreditRepository
        from app.services.billing.plans import SIGNUP_GRANT

        CreditRepository(session).grant(user.id, SIGNUP_GRANT, "mobile_identity_signup")
    except Exception as exc:  # noqa: BLE001 - never block sign-in on the welcome grant
        logger.warning(f"signup grant failed for supabase user {user.id}: {exc}")
    logger.info(f"provisioned user for supabase subject, request_id: {request_id}")
    _rally_signed_up(user, "supabase")
    return user


def resolve_clerk_principal(request: Request, session: Any, request_id: str):
    """Resolve a verified Clerk bearer token, or return ``None`` for fallback."""
    try:
        from app.core import clerk
    except Exception as exc:  # noqa: BLE001 - optional bridge must not crash startup
        logger.debug(f"clerk bridge unavailable, request_id: {request_id}: {exc}")
        return None

    if not clerk.is_configured():
        return None
    token = clerk.extract_bearer_token(request)
    if not token:
        return None
    try:
        claims = clerk.verify_clerk_jwt(token)
    except clerk.ClerkAuthError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=401,
            message=f"{request_id}: invalid bearer token: {exc}",
        ) from exc
    return get_or_create_clerk_user(session, claims, request_id)


def get_or_create_clerk_user(session: Any, claims: dict, request_id: str):
    """Map verified Clerk claims to the existing stable User identity row."""
    sub = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    if not sub and not email:
        raise HttpException(
            task_id=request_id,
            status_code=401,
            message=f"{request_id}: bearer token has no subject",
        )
    synthetic = f"clerk_{sub}@users.reelforge"
    if not email and sub:
        # Default Clerk session tokens carry no email claim: ask the Backend
        # API for the primary verified address so receipts, job mail and the
        # card check reach a real inbox.
        from app.core import clerk

        email = clerk.fetch_primary_email(sub)
    lookup_email = email or synthetic
    user = session.query(User).filter(User.email == lookup_email).first()
    if user is not None:
        return user
    if email and sub:
        legacy = session.query(User).filter(User.email == synthetic).first()
        if legacy is not None:
            # Account made before the lookup existed: move it to the real address.
            legacy.email = email
            session.flush()
            logger.info(f"clerk user {legacy.id} email upgraded from synthetic, request_id: {request_id}")
            return legacy
    # First sight of this subject provisions a new account — a public signup.
    # Existing users return above, so pilot logins are never blocked. Imported
    # locally to avoid pulling the launch router into the auth import chain.
    from app.core.launch.policy import require_signup_enabled

    # Clerk only puts an email claim in a verified session token when the
    # instance's JWT template maps the primary (verified) address; the
    # synthetic ``clerk_<sub>@users.reelforge`` fallback can never match.
    require_signup_enabled(request_id, session=session, verified_email=email)
    display_name = str(claims.get("name") or claims.get("username") or "").strip()
    user = User(email=lookup_email, display_name=display_name)
    session.add(user)
    session.flush()
    # No credits here: a web account unlocks its free reels with the $1 card
    # check (app.services.billing.card_check), which grants SIGNUP_GRANT under
    # the same idempotent ledger reason ("signup").
    logger.info(
        f"provisioned user for clerk subject {sub or '<none>'} "
        f"({lookup_email}), request_id: {request_id}"
    )
    _rally_signed_up(user, "clerk")
    return user

def _rally_signed_up(user: Any, method: str) -> None:
    """Best-effort Rally ``signed_up`` event (no-op unless RALLY_EVENTS_KEY is set)."""
    try:
        from app.integrations.rally import track_signed_up

        track_signed_up(str(user.id), getattr(user, "email", None), method=method)
    except Exception as exc:  # noqa: BLE001 - lifecycle events never block sign-in
        logger.debug(f"rally signed_up skipped: {exc}")
