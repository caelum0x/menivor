"""Spend controls: per-user/workspace monthly budget cap + BYOK consent.

Enforced at wallet-reservation time so a job cannot be dispatched once the
calendar-month spend would exceed the budget; ``byok_allowed`` gates whether a
customer's own provider key may fund outbound calls.
"""

from .router import router

__all__ = ["router"]
