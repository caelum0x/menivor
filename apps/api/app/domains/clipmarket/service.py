"""Clipmarket service — persistent campaigns + fraud-gated payout on submissions.

Bridges the pure cores (``payout.compute_payout`` + ``payout.fraud_score``) to the
DB rows (``models.db.clipmarket``): create a campaign, accept a submission, and
review it — a suspected viewbot is HELD for manual review (never auto-paid), a
clean submission is APPROVED with its budget-capped payout and the campaign's
spent budget advanced atomically in the same transaction.

Money moves through the USD wallet ledger in the same transaction:

* creating a campaign ESCROWS its full budget from the brand's wallet
  (available -> reserved; 402 when the wallet cannot cover it);
* an approved submission moves ``payable_micros`` out of the brand's escrow and
  credits the clipper's wallet;
* ending a campaign (or exhausting it) releases the unspent escrow back to the
  brand's available balance.

Only the campaign's brand may review its submissions, and the view signals are
attested by that brand (the payer), so a clipper can never approve or inflate
their own payout.
"""

from __future__ import annotations

from typing import Any

from app.domains.clipmarket.payout import (
    Campaign,
    ViewSignals,
    compute_payout,
    fraud_score,
)
from app.models.db.clipmarket import ClipCampaign, ClipSubmission

# Ledger reasons for clipmarket money movements (append-only wallet entries).
_REASON_ESCROW = "clipmarket_escrow"
_REASON_PAYOUT_OUT = "clipmarket_payout"
_REASON_PAYOUT_IN = "clipmarket_earning"
_REASON_ESCROW_RELEASE = "clipmarket_escrow_release"
_REVIEWABLE = ("pending", "held_review")


class ClipmarketError(ValueError):
    """An invalid clipmarket operation (unknown campaign, inactive, etc.).

    ``status_code`` lets the router map the failure to the right HTTP status.
    """

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def _wallet_repo(session: Any):
    from app.domains.wallet.repository import WalletRepository

    return WalletRepository(session)


def _escrow_budget(session: Any, campaign: ClipCampaign) -> None:
    """Hold the campaign budget in the brand's wallet (available -> reserved)."""
    from app.domains.wallet.repository import ENTRY_RESERVE, InsufficientFundsError

    repo = _wallet_repo(session)
    account = repo.get_or_create_personal_account(str(campaign.brand_id))
    try:
        repo.append_entry(
            account.id,
            entry_type=ENTRY_RESERVE,
            reason=_REASON_ESCROW,
            available_delta=-int(campaign.budget_micros),
            reserved_delta=int(campaign.budget_micros),
            meta={"campaign_id": campaign.id},
        )
    except InsufficientFundsError as exc:
        raise ClipmarketError(
            "insufficient wallet balance to fund this campaign budget; top up your wallet first",
            status_code=402,
        ) from exc


def _pay_clipper(session: Any, campaign: ClipCampaign, sub: ClipSubmission, amount: int) -> None:
    """Move ``amount`` from the brand's escrow to the clipper's wallet."""
    from app.domains.wallet.repository import ENTRY_ADJUSTMENT, InsufficientFundsError

    if amount <= 0:
        return
    repo = _wallet_repo(session)
    brand_account = repo.get_or_create_personal_account(str(campaign.brand_id))
    try:
        repo.append_entry(
            brand_account.id,
            entry_type=ENTRY_ADJUSTMENT,
            reason=_REASON_PAYOUT_OUT,
            reserved_delta=-amount,
            meta={"campaign_id": campaign.id, "submission_id": sub.id},
        )
    except InsufficientFundsError as exc:
        raise ClipmarketError(
            "campaign escrow cannot cover this payout", status_code=409
        ) from exc
    clipper_account = repo.get_or_create_personal_account(str(sub.clipper_id))
    repo.append_entry(
        clipper_account.id,
        entry_type=ENTRY_ADJUSTMENT,
        reason=_REASON_PAYOUT_IN,
        available_delta=amount,
        meta={"campaign_id": campaign.id, "submission_id": sub.id},
    )


def _release_unspent(session: Any, campaign: ClipCampaign) -> None:
    """Return the unspent escrow to the brand's available balance (once)."""
    from app.domains.wallet.repository import ENTRY_RELEASE, InsufficientFundsError

    remaining = int(campaign.budget_micros) - int(campaign.spent_micros)
    if remaining <= 0:
        return
    repo = _wallet_repo(session)
    account = repo.get_or_create_personal_account(str(campaign.brand_id))
    try:
        repo.append_entry(
            account.id,
            entry_type=ENTRY_RELEASE,
            reason=_REASON_ESCROW_RELEASE,
            available_delta=remaining,
            reserved_delta=-remaining,
            meta={"campaign_id": campaign.id},
        )
    except InsufficientFundsError:
        # A campaign created before escrow existed holds nothing to release.
        return
    # Record the release as spent-down so the escrow can never be freed twice.
    campaign.spent_micros = int(campaign.budget_micros)


def _campaign_dataclass(row: ClipCampaign) -> Campaign:
    return Campaign(
        campaign_id=row.id,
        cpm_micros=row.cpm_micros,
        budget_micros=row.budget_micros,
        spent_micros=row.spent_micros,
        min_views=row.min_views,
    )


def create_campaign(
    session: Any, *, brand_id: str, cpm_micros: int, budget_micros: int,
    title: str = "", min_views: int = 0,
) -> ClipCampaign:
    if cpm_micros <= 0 or budget_micros <= 0:
        raise ClipmarketError("cpm and budget must be positive")
    row = ClipCampaign(
        brand_id=brand_id, cpm_micros=cpm_micros, budget_micros=budget_micros,
        title=title, min_views=min_views,
    )
    session.add(row)
    session.flush()
    _escrow_budget(session, row)
    session.flush()
    return row


def set_campaign_status(session: Any, *, campaign_id: str, brand_id: str, status: str) -> ClipCampaign:
    """Transition a campaign's lifecycle (owner-scoped): active↔paused, or ended.

    Only the owning brand may change it; ``ended`` is terminal (an exhausted or
    ended campaign cannot be reactivated). Valid targets: ``active``, ``paused``,
    ``ended``.
    """
    valid = {"active", "paused", "ended"}
    if status not in valid:
        raise ClipmarketError(f"status must be one of {sorted(valid)}")
    campaign = session.get(ClipCampaign, campaign_id)
    if campaign is None or str(campaign.brand_id) != str(brand_id):
        raise ClipmarketError(f"unknown campaign {campaign_id!r}")
    if campaign.status in ("ended", "exhausted") and status != "ended":
        raise ClipmarketError(f"campaign is {campaign.status} and cannot be reactivated")
    if status == "ended" and campaign.status != "ended":
        pending = (
            session.query(ClipSubmission)
            .filter(
                ClipSubmission.campaign_id == campaign.id,
                ClipSubmission.status.in_(_REVIEWABLE),
            )
            .count()
        )
        if pending:
            raise ClipmarketError(
                f"review the {pending} open submission(s) before ending this campaign",
                status_code=409,
            )
        _release_unspent(session, campaign)
    campaign.status = status
    session.flush()
    return campaign


def submit_clip(session: Any, *, campaign_id: str, clipper_id: str, clip_url: str) -> ClipSubmission:
    campaign = session.get(ClipCampaign, campaign_id)
    if campaign is None:
        raise ClipmarketError(f"unknown campaign {campaign_id!r}")
    if campaign.status != "active":
        raise ClipmarketError(f"campaign is {campaign.status}")
    if str(campaign.brand_id) == str(clipper_id):
        raise ClipmarketError("you cannot submit clips to your own campaign", status_code=403)
    url = str(clip_url or "").strip()
    if not url.startswith("https://"):
        raise ClipmarketError("clip_url must be a public https:// link to the posted clip")
    duplicate = (
        session.query(ClipSubmission)
        .filter(ClipSubmission.campaign_id == campaign_id, ClipSubmission.clip_url == url)
        .first()
    )
    if duplicate is not None:
        raise ClipmarketError("this clip was already submitted to the campaign", status_code=409)
    clip_url = url
    row = ClipSubmission(campaign_id=campaign_id, clipper_id=clipper_id, clip_url=clip_url)
    session.add(row)
    session.flush()
    return row


def review_submission(
    session: Any,
    *,
    submission_id: str,
    reviewer_id: str,
    signals: ViewSignals,
    hold_threshold: float = 0.55,
    override_hold: bool = False,
) -> ClipSubmission:
    """Fraud-gate + pay out a submission (campaign brand only).

    Suspected viewbot -> ``held_review`` (fraud score + flags recorded) unless the
    brand explicitly overrides the hold after a manual check. Clean ->
    ``approved`` with the budget-capped payout, moved from the brand's escrow to
    the clipper's wallet in the same transaction; the campaign is marked
    ``exhausted`` (and any dust released) when its budget is depleted.
    """
    sub = session.get(ClipSubmission, submission_id)
    if sub is None:
        raise ClipmarketError(f"unknown submission {submission_id!r}", status_code=404)
    campaign = session.get(ClipCampaign, sub.campaign_id)
    if campaign is None:
        raise ClipmarketError("submission's campaign is missing", status_code=404)
    if str(campaign.brand_id) != str(reviewer_id):
        # Same 404 as an unknown id: never confirm a foreign submission exists.
        raise ClipmarketError(f"unknown submission {submission_id!r}", status_code=404)
    if sub.status not in _REVIEWABLE:
        raise ClipmarketError(f"submission is already {sub.status}", status_code=409)
    if campaign.status in ("ended",):
        raise ClipmarketError("campaign has ended", status_code=409)

    verdict = fraud_score(signals, hold_threshold=hold_threshold)
    sub.verified_views = signals.views
    sub.fraud_score = int(round(verdict.score * 100))
    sub.fraud_flags = ",".join(verdict.flags)

    if verdict.hold_for_review and not override_hold:
        sub.status = "held_review"
        session.flush()
        return sub

    result = compute_payout(_campaign_dataclass(campaign), signals.views)
    sub.payable_micros = result.payable_micros
    sub.status = "approved" if result.payable_micros > 0 else "rejected"
    _pay_clipper(session, campaign, sub, result.payable_micros)
    campaign.spent_micros = campaign.spent_micros + result.payable_micros
    if campaign.spent_micros >= campaign.budget_micros:
        campaign.status = "exhausted"
    session.flush()
    return sub


def reject_submission(session: Any, *, submission_id: str, reviewer_id: str) -> ClipSubmission:
    """Reject an open submission without payout (campaign brand only)."""
    sub = session.get(ClipSubmission, submission_id)
    campaign = session.get(ClipCampaign, sub.campaign_id) if sub is not None else None
    if sub is None or campaign is None or str(campaign.brand_id) != str(reviewer_id):
        raise ClipmarketError(f"unknown submission {submission_id!r}", status_code=404)
    if sub.status not in _REVIEWABLE:
        raise ClipmarketError(f"submission is already {sub.status}", status_code=409)
    sub.status = "rejected"
    sub.payable_micros = 0
    session.flush()
    return sub


def list_campaign_submissions(session: Any, *, campaign_id: str, brand_id: str) -> list[ClipSubmission]:
    """Every submission to one of the caller's campaigns (newest first)."""
    campaign = session.get(ClipCampaign, campaign_id)
    if campaign is None or str(campaign.brand_id) != str(brand_id):
        raise ClipmarketError(f"unknown campaign {campaign_id!r}", status_code=404)
    return (
        session.query(ClipSubmission)
        .filter(ClipSubmission.campaign_id == campaign_id)
        .order_by(ClipSubmission.created_at.desc())
        .all()
    )


def list_my_submissions(session: Any, *, clipper_id: str, limit: int = 100) -> list[ClipSubmission]:
    """The caller's own submissions across campaigns (newest first)."""
    return (
        session.query(ClipSubmission)
        .filter(ClipSubmission.clipper_id == clipper_id)
        .order_by(ClipSubmission.created_at.desc())
        .limit(max(1, min(200, limit)))
        .all()
    )


def list_my_campaigns(session: Any, *, brand_id: str, limit: int = 100) -> list[ClipCampaign]:
    """The caller's own campaigns in every status (newest first)."""
    return (
        session.query(ClipCampaign)
        .filter(ClipCampaign.brand_id == brand_id)
        .order_by(ClipCampaign.created_at.desc())
        .limit(max(1, min(200, limit)))
        .all()
    )
