"""Reviewed model-catalog domain: providers, model listings, prices, profiles.

Read-only browse + generation-quote surface for the pay-as-you-go marketplace
(``docs/reelforge/PROVIDER_MARKETPLACE_PLAN.md`` §2/§4.3). Clients select a
catalog ``model_id`` / profile ``slug`` and receive a server-created price
snapshot; they never send a raw provider identifier or price.
"""

from .router import router

__all__ = ["router"]
