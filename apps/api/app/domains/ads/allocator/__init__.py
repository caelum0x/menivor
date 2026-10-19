"""Cross-network budget allocator: which network pays off, and a proposed split.

* :mod:`.engine` - pure Gamma-Poisson Thompson sampling over *results per unit
  of spend* per network, with an exploration floor and a per-run step cap.
* :mod:`.stats` - folds the paid-campaign stats already synced into
  ``AdVariant.spec['paid_ads']`` (plus optional hand-entered results for
  networks with no API, e.g. organic boosts) into one row per network.
* :mod:`.service` - daily proposal (``ad_allocation_proposals``) mirrored into
  the approvals feed (``approval_items``, source ``ad_budget``); applying an
  approved proposal re-budgets the network's active campaigns and lets the
  existing per-creative optimizer push ad-set budgets.
* :mod:`.routes` - HTTP routes under ``/ads/allocator``.

Nothing spends money without a human decision unless the operator opts into
auto-apply for small moves (``MENIVOR_ALLOCATOR_AUTO_APPLY_DELTA``).
"""
