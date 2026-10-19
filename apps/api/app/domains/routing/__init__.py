"""Provider routing domain (worker-internal; no public HTTP surface).

Selects which reviewed provider/model serves a job capability and, only with
explicit policy consent, an equivalent fallback under a max-cost cap
(``docs/reelforge/PROVIDER_MARKETPLACE_PLAN.md`` §4.1/§5). Provider adapters own
outbound protocol calls only — they never debit wallets, mutate jobs, or decide
the client price; the wallet/reels domains own those transactions.
"""

from .base import (
    ModelListing,
    NormalizedUsage,
    ProviderAdapter,
    ProviderError,
    ProviderRun,
    QuoteResult,
    ProviderRegistry,
    registry,
)
from .policy import RoutePolicy
from .service import RoutingError, RoutingService

__all__ = [
    "ModelListing",
    "NormalizedUsage",
    "ProviderAdapter",
    "ProviderError",
    "ProviderRegistry",
    "ProviderRun",
    "QuoteResult",
    "RoutePolicy",
    "RoutingError",
    "RoutingService",
    "registry",
]
