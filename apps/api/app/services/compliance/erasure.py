"""Right-to-erasure — in-place PII anonymization (GDPR Art. 17 — Compliance, Epic 5).

:func:`erase_user` ANONYMIZES a user's PII WITHOUT breaking referential
integrity: it keeps every row (so foreign keys stay valid and legally-required
financial / audit records are preserved) and instead NULLs / tombstones the PII
columns and revokes credentials. It never cascade-deletes.

STRICTLY SCOPED: every mutation filters on the target ``user_id`` — a DIFFERENT
user's rows are never touched. IDEMPOTENT: re-running is a no-op on already
anonymized data (the tombstone email is deterministic per user id, so the UNIQUE
email constraint is never violated). Every run writes an audit row and marks the
:class:`ErasureRequest` completed.

PII FIELD MAP (what is anonymized):

===========================  ==========================================
Column                       New value
===========================  ==========================================
User.email                   ``deleted+<id>@tombstone.invalid``
User.display_name            ``""`` (NOT NULL — blanked, not nulled)
User.handle                  ``None``
User.bio                     ``None``
User.api_key_hash            ``""`` (legacy inline key revoked)
UserApiKey.revoked           ``True`` (every personal API key revoked)
SocialAccount.access_token_enc   ``""`` (OAuth credential revoked)
SocialAccount.refresh_token_enc  ``None``
SocialAccount.external_account_id  ``""``
SocialAccount.scopes             ``""``
SocialAccount.token_expires_at   ``None``
Job.script                   ``""`` (narration PII blanked)
Job.error                    ``""``
Job.params                   prompt/PII keys stripped (recursively)
Job.result/poster/preview/cover_key  ``""`` (R2 media keys blanked)
Asset.r2_key / Asset.meta    ``""`` / ``{}`` (uploaded/rendered media)
ShareLink.revoked            ``True`` (public share access revoked)
UserVoice.sample_key         ``""`` (biometric voice sample key)
UserVoice.provider_voice_id  ``""`` (live provider voice clone revoked)
UserVoice.name / consent     ``""`` / ``False``
ExternalIdentity.email       ``""`` (SSO/SCIM plaintext email)
ExternalIdentity.idp_subject tombstone (IdP NameID)
ExternalIdentity.provisioned ``False`` (IdP access revoked)
MarketplaceTemplate.title/description/prompt  ``""`` (authored free text)
MarketplaceTemplate.params/tags/published  scrubbed / ``[]`` / ``False``
SavedIdea.title/hook/payload ``""`` / ``""`` / ``{}``
Notification.title/body/data ``""`` / ``""`` / ``{}``
===========================  ==========================================

Delete means delete (MG1, ACCOUNT-LIFECYCLE section 3): before any key is
blanked, :func:`erasure_followups.capture` records a manifest of every R2 key,
``jobs/<id>/`` prefix, live plan, open render and Clerk id. After the rows are
anonymized, :func:`erasure_followups.run` cancels billing at the provider,
stops open renders, deletes the R2 objects, deletes the Clerk user, records
``forfeited_on_delete`` on the ledger and sends one confirmation email. Each
step is idempotent; a step that fails is retried by ``workers/tasks_erasure``.
Pass ``followups=False`` to anonymize only (no side effects).

Deliberately PRESERVED (compliance / integrity): ``credit_ledger`` (plus the
``forfeited_on_delete`` row), ``invoices`` / ``subscriptions``, ``audit_log``
rows, and all row ids / foreign keys.
"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db.models import (
    Asset,
    ExternalIdentity,
    Job,
    MarketplaceTemplate,
    Notification,
    SavedIdea,
    ShareLink,
    SocialAccount,
    User,
    UserApiKey,
    UserVoice,
)
from app.models.db.repositories import ErasureRequestRepository
from app.services import audit
from app.services.compliance import erasure_followups

#: Tombstone email domain — a reserved, non-routable domain (RFC 6761 style) so
#: an anonymized address can never collide with, or be mistaken for, a real one.
_TOMBSTONE_DOMAIN: str = "tombstone.invalid"

#: JSON keys inside ``Job.params`` that may carry user-authored PII / prompts and
#: are stripped during erasure. The rest of the params (render knobs) are kept.
_PII_PARAM_KEYS: frozenset[str] = frozenset(
    {
        "prompt",
        "script",
        "brief",
        "topic",
        "description",
        "text",
        "hook",
        "idea",
        "notes",
        "input_text",
    }
)

#: Audit verb recorded on a completed erasure.
_ACTION_ERASE: str = "compliance.user_erased"


def tombstone_email(user_id: str) -> str:
    """Return the deterministic tombstone email for a user id."""
    return f"deleted+{user_id}@{_TOMBSTONE_DOMAIN}"


def _scrub_value(value: object) -> object:
    """Recursively strip PII / prompt keys from nested dicts and lists (immutable).

    Returns a NEW structure — dict keys in :data:`_PII_PARAM_KEYS` are dropped at
    every depth (so nested PII like ``{'variant': {'prompt': ...}}`` or a
    ``captions`` / ``segments`` list of ``{'text': ...}`` items is also removed),
    and every other value is copied through unchanged.
    """
    if isinstance(value, dict):
        return {
            k: _scrub_value(v)
            for k, v in value.items()
            if k not in _PII_PARAM_KEYS
        }
    if isinstance(value, list):
        return [_scrub_value(v) for v in value]
    return value


def _scrub_params(params: dict | None) -> dict:
    """Return a copy of ``params`` with PII / prompt keys removed at every depth."""
    if not params:
        return {}
    return _scrub_value(params)  # type: ignore[return-value]


def erase_user(
    session: Session,
    user_id: str,
    *,
    scope: str = "user",
    actor_user_id: str | None = None,
    request_id: str | None = None,
    followups: bool = True,
    deps: erasure_followups.Deps | None = None,
) -> "object":
    """Anonymize ``user_id``'s PII in place; audit + complete the request.

    Tombstones the user's email, nulls/blanks their profile PII, revokes every
    credential (personal API keys, the legacy inline key, OAuth social
    connections) and blanks each of their jobs' narration script / prompt params
    — while KEEPING every row so foreign keys and financial/audit records stay
    intact. Idempotent and strictly scoped to ``user_id``.

    A tracking :class:`ErasureRequest` is resolved (by ``request_id`` if given,
    else the user's open request, else a fresh one), moved to ``processing``,
    and marked ``completed`` with an audit row on success.

    Returns the completed :class:`ErasureRequest`.

    Raises:
        ValueError: when ``user_id`` is blank or no such user exists.
    """
    normalized = (user_id or "").strip()
    if not normalized:
        raise ValueError("user_id must be a non-empty string")

    user = session.get(User, normalized)
    if user is None:
        raise ValueError(f"user not found: {normalized}")

    req_repo = ErasureRequestRepository(session)
    if request_id:
        request = req_repo.get(request_id)
        if request is None or request.user_id != normalized:
            # Never advance another user's request; fall back to a fresh one.
            request = req_repo.create(normalized, scope=scope)
    else:
        request = req_repo.get_open_for_user(normalized) or req_repo.create(
            normalized, scope=scope
        )
    req_repo.set_status(request.id, "processing")

    # 0) Capture what must be deleted outside the database BEFORE blanking it.
    manifest, email = (None, "")
    if followups:
        manifest, email = erasure_followups.capture(session, normalized, request.id, deps=deps)
        erasure_followups.record_manifest(session, manifest, email)

    # 1) Profile PII — tombstone email, null/blank the rest.
    user.email = tombstone_email(normalized)
    user.display_name = ""  # NOT NULL column -> blank rather than NULL
    user.handle = None
    user.bio = None
    user.api_key_hash = ""  # revoke the legacy inline API key

    # 2) Revoke every personal API key (soft-delete; row retained for audit).
    api_keys = list(
        session.execute(
            select(UserApiKey).where(UserApiKey.user_id == normalized)
        ).scalars().all()
    )
    for key in api_keys:
        key.revoked = True

    # 3) Revoke OAuth social connections — blank the encrypted credential blobs
    #    (rows kept so referential integrity holds; tokens rendered unusable).
    social = list(
        session.execute(
            select(SocialAccount).where(SocialAccount.user_id == normalized)
        ).scalars().all()
    )
    for acct in social:
        acct.access_token_enc = ""
        acct.refresh_token_enc = None
        acct.external_account_id = ""
        acct.scopes = ""
        acct.token_expires_at = None

    # 4) Blank each job's narration script / prompt params AND the R2 media keys
    #    (keep the row + ids). The referenced R2 objects should be purged by the
    #    storage layer as a required companion step (see module docstring).
    jobs = list(
        session.execute(
            select(Job).where(Job.user_id == normalized)
        ).scalars().all()
    )
    for job in jobs:
        job.script = ""
        job.error = ""
        job.params = _scrub_params(job.params)
        job.result_key = ""
        job.poster_key = ""
        job.preview_key = ""
        job.cover_key = ""
        # The persisted WolfCut clip descriptor (generate->edit seam) is stashed
        # under a private ``stages`` key and carries the reel's caption text,
        # which is derived from the narration script blanked above — drop it so
        # no narration PII survives erasure in the stages map.
        if isinstance(job.stages, dict) and "_result_media" in job.stages:
            stages = dict(job.stages)
            stages.pop("_result_media", None)
            job.stages = stages

    # 5) Blank the R2 key + metadata of every asset the user uploaded/rendered
    #    (row kept for FK integrity; the R2 object itself must be purged too).
    assets = list(
        session.execute(
            select(Asset).where(Asset.user_id == normalized)
        ).scalars().all()
    )
    for asset in assets:
        asset.r2_key = ""
        asset.meta = {}

    # 6) Revoke every public share link so a previously-shared reel stops serving
    #    the user's media to anyone holding the link.
    share_links = list(
        session.execute(
            select(ShareLink).where(ShareLink.user_id == normalized)
        ).scalars().all()
    )
    for link in share_links:
        link.revoked = True

    # 7) Erase cloned brand voice: biometric voice sample (R2) + the live
    #    provider voice clone credential. Blank the keys/name and withdraw
    #    consent. The R2 sample object and the provider-side clone should also be
    #    deleted by the storage/provider layer as a required companion step.
    voices = list(
        session.execute(
            select(UserVoice).where(UserVoice.user_id == normalized)
        ).scalars().all()
    )
    for voice in voices:
        voice.sample_key = ""
        voice.provider_voice_id = ""
        voice.name = ""
        voice.consent = False

    # 8) Tombstone SSO/SCIM external identities — blank the plaintext email +
    #    IdP subject and revoke IdP-provisioned access (row kept for FK/audit).
    identities = list(
        session.execute(
            select(ExternalIdentity).where(ExternalIdentity.user_id == normalized)
        ).scalars().all()
    )
    for identity in identities:
        identity.email = ""
        identity.idp_subject = tombstone_email(normalized)
        identity.provisioned = False

    # 9) Scrub authored free-text in the user's published marketplace templates
    #    and soft-hide them from the public browse surface.
    templates = list(
        session.execute(
            select(MarketplaceTemplate).where(
                MarketplaceTemplate.author_user_id == normalized
            )
        ).scalars().all()
    )
    for template in templates:
        template.title = ""
        template.description = ""
        template.prompt = ""
        template.params = _scrub_params(template.params)
        template.tags = []
        template.published = False

    # 10) Scrub authored free-text in saved ideas + notifications.
    saved_ideas = list(
        session.execute(
            select(SavedIdea).where(SavedIdea.user_id == normalized)
        ).scalars().all()
    )
    for idea in saved_ideas:
        idea.title = ""
        idea.hook = ""
        idea.payload = {}

    notifications = list(
        session.execute(
            select(Notification).where(Notification.user_id == normalized)
        ).scalars().all()
    )
    for note in notifications:
        note.title = ""
        note.body = ""
        note.data = {}

    session.flush()

    # 11) Audit the erasure (append-only, immutable).
    audit.record(
        session,
        actor_user_id=(actor_user_id or normalized),
        action=_ACTION_ERASE,
        target_type="user",
        target_id=normalized,
        metadata={
            "scope": scope,
            "jobs_anonymized": len(jobs),
            "assets_anonymized": len(assets),
            "share_links_revoked": len(share_links),
            "voices_erased": len(voices),
            "external_identities_erased": len(identities),
            "marketplace_templates_scrubbed": len(templates),
            "saved_ideas_scrubbed": len(saved_ideas),
            "notifications_scrubbed": len(notifications),
            "api_keys_revoked": len(api_keys),
            "social_accounts_revoked": len(social),
        },
    )

    # 12) Cancel billing, stop work, delete media and the Clerk user, record the
    #     forfeited balance, confirm by email (retried if any step fails).
    steps: dict[str, str] = {}
    if manifest is not None:
        steps = erasure_followups.run(session, manifest, email=email, deps=deps)
        failed = [name for name, status in steps.items() if status == erasure_followups.FAILED]
        if failed:
            logger.warning(f"compliance erasure for user={normalized}: retrying later: {failed}")

    completed = req_repo.set_status(
        request.id, "completed", completed_at=datetime.now(timezone.utc)
    )
    logger.info(
        f"compliance erasure completed for user={normalized} "
        f"(jobs={len(jobs)} api_keys={len(api_keys)} social={len(social)})"
    )
    return completed


__all__ = ["erase_user", "tombstone_email"]
