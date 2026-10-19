"""BYOK domain: customer-owned provider credentials (encrypted at rest).

Lets a user store their own upstream API key so a job can route through their
provider account (PROVIDER_MARKETPLACE_PLAN.md §8.4). The raw secret is never
returned; every use is audited and a key can be revoked immediately.
"""

from .router import router

__all__ = ["router"]
