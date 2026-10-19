"""USD wallet domain: accounts, append-only ledger, purchase quotes, checkout.

Durable user-spend accounting for the pay-as-you-go marketplace
(``docs/reelforge/PROVIDER_MARKETPLACE_PLAN.md`` §1/§3). Money is integer
microdollars; balances are derived from an append-only ledger, credit grants
occur only from verified payment webhooks, and job dispatch reserves the max
quoted cost before any provider call.
"""

from .router import router

__all__ = ["router"]
