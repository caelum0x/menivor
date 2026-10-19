"""Plan-based entitlement resolution (Enterprise Billing Platform, Epic 3).

Entitlements answer one question: *does this workspace's plan grant this
feature?* The decision is delegated to **OpenFeature** (open-feature/python-sdk,
Apache-2.0) — a vendor-neutral feature-flag / entitlement layer — rather than
hand-rolled. We register a small **in-process provider**
(:class:`_PlanEntitlementProvider`) backed by the pure-data
:data:`PLAN_ENTITLEMENTS` map (plan -> {feature: value}); the provider resolves a
requested feature against the *plan supplied in the evaluation context*, so the
same enforcer is reused for every workspace with no per-tenant state.

Money-correctness invariants honored here:

* **Safe fallback to base/free.** A workspace with NO active subscription — or one
  whose subscription is ``past_due`` / ``canceled`` (not ``active``/``trialing``)
  — resolves against the base **free** plan. A lapsed subscription can therefore
  never keep granting a premium extra.
* **Default-deny extras.** An unknown plan, an unknown feature, or any value that
  cannot be resolved falls back to the **free** plan's value (and then a typed
  zero/``False``), so a gap can only ever *deny* a premium capability, never
  grant one.
* **Guarded dependency.** ``import openfeature`` is guarded: if the SDK is absent
  the module still imports and every resolution degrades to a direct read of the
  same :data:`PLAN_ENTITLEMENTS` map with the identical base/free safe default —
  the suite stays green and no entitlement is ever bypassed.

Public API::

    PLAN_ENTITLEMENTS                          # plan -> {feature: value}
    plan_entitlements(plan_key) -> dict        # safe (unknown plan -> free)
    active_plan_key(session, workspace_id)     # free when no LIVE subscription
    is_entitled(session, workspace_id, feature) -> bool
    entitlement_value(session, workspace_id, feature, default=None) -> Any
    resolve(plan_key, feature, default=None) -> Any   # pure plan->value
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from loguru import logger

# --------------------------------------------------------------------------- #
# Plan / feature catalogue
# --------------------------------------------------------------------------- #
FREE_PLAN: str = "free"
STARTER_PLAN: str = "starter"
PRO_PLAN: str = "pro"
ENTERPRISE_PLAN: str = "enterprise"

# Feature keys (stable dotted-free identifiers referenced by every gated call
# site so a typo is caught, not silently allowed).
FEAT_MAX_VARIANTS: str = "max_variants"
FEAT_API_ACCESS: str = "api_access"
FEAT_SSO: str = "sso"
FEAT_PRIORITY_RENDER: str = "priority_render"
FEAT_SEATS: str = "seats"
FEAT_MONTHLY_CREDITS: str = "monthly_credits"
FEAT_WATERMARK_REMOVAL: str = "watermark_removal"

#: The single source of truth: plan -> {feature: entitlement value}. ``free`` is
#: the base plan and the safe fallback for every unresolved case. ``monthly_credits``
#: mirrors the locked plan credits in ``app.services.billing.plans`` (free 3,
#: starter 30, pro 120) so the credit grant and the entitlement never disagree.
#: Numeric features are *limits* (max_variants, seats, monthly_credits); boolean
#: features are *capabilities* (api_access, sso, priority_render, watermark_removal).
PLAN_ENTITLEMENTS: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        FREE_PLAN: MappingProxyType(
            {
                FEAT_MAX_VARIANTS: 1,
                FEAT_API_ACCESS: False,
                FEAT_SSO: False,
                FEAT_PRIORITY_RENDER: False,
                FEAT_SEATS: 1,
                FEAT_MONTHLY_CREDITS: 3,
                FEAT_WATERMARK_REMOVAL: False,
            }
        ),
        STARTER_PLAN: MappingProxyType(
            {
                FEAT_MAX_VARIANTS: 3,
                FEAT_API_ACCESS: True,
                FEAT_SSO: False,
                FEAT_PRIORITY_RENDER: False,
                FEAT_SEATS: 2,
                FEAT_MONTHLY_CREDITS: 30,
                FEAT_WATERMARK_REMOVAL: True,
            }
        ),
        PRO_PLAN: MappingProxyType(
            {
                FEAT_MAX_VARIANTS: 6,
                FEAT_API_ACCESS: True,
                FEAT_SSO: False,
                FEAT_PRIORITY_RENDER: True,
                FEAT_SEATS: 5,
                FEAT_MONTHLY_CREDITS: 120,
                FEAT_WATERMARK_REMOVAL: True,
            }
        ),
        ENTERPRISE_PLAN: MappingProxyType(
            {
                FEAT_MAX_VARIANTS: 20,
                FEAT_API_ACCESS: True,
                FEAT_SSO: True,
                FEAT_PRIORITY_RENDER: True,
                FEAT_SEATS: 100,
                FEAT_MONTHLY_CREDITS: 1000,
                FEAT_WATERMARK_REMOVAL: True,
            }
        ),
    }
)

#: OpenFeature flag domain / client name for the entitlement provider.
_CLIENT_NAME: str = "reelforge-entitlements"


# --------------------------------------------------------------------------- #
# Pure plan -> value resolution (the source of truth, SDK-independent)
# --------------------------------------------------------------------------- #
def plan_entitlements(plan_key: str | None) -> dict[str, Any]:
    """Return a plain-dict copy of a plan's entitlements (unknown plan -> free).

    Case/space-insensitive. An unknown/blank plan resolves to the base **free**
    plan (default-deny extras) so a bad plan key can never grant a premium
    capability.
    """
    key = (plan_key or "").strip().lower()
    bundle = PLAN_ENTITLEMENTS.get(key) or PLAN_ENTITLEMENTS[FREE_PLAN]
    return dict(bundle)


def resolve(plan_key: str | None, feature: str, default: Any = None) -> Any:
    """Return ``feature``'s value for ``plan_key`` — the pure, SDK-free decision.

    Resolution order (each a strict *narrowing* toward deny):
        1. the plan's own value for ``feature``;
        2. else the base **free** plan's value for ``feature`` (safe default);
        3. else the caller-supplied ``default``.

    This is the function the OpenFeature in-process provider delegates to, and the
    function used directly when the SDK is absent — so behaviour is identical with
    or without OpenFeature installed.
    """
    key = (plan_key or "").strip().lower()
    feat = (feature or "").strip()
    bundle = PLAN_ENTITLEMENTS.get(key)
    if bundle is not None and feat in bundle:
        return bundle[feat]
    free_bundle = PLAN_ENTITLEMENTS[FREE_PLAN]
    if feat in free_bundle:
        return free_bundle[feat]
    return default


# --------------------------------------------------------------------------- #
# OpenFeature integration (guarded) — vendor-neutral entitlement layer
# --------------------------------------------------------------------------- #
try:  # OpenFeature is a first-class dep, but guard so absence degrades safely.
    from openfeature import api as _of_api
    from openfeature.evaluation_context import EvaluationContext
    from openfeature.flag_evaluation import FlagResolutionDetails, Reason
    from openfeature.provider import AbstractProvider
    from openfeature.provider.metadata import Metadata

    _OPENFEATURE_IMPORT_ERROR: Exception | None = None
    _OPENFEATURE_AVAILABLE: bool = True
except Exception as exc:  # pragma: no cover - exercised only without the SDK
    _of_api = None  # type: ignore[assignment]
    EvaluationContext = None  # type: ignore[assignment,misc]
    FlagResolutionDetails = None  # type: ignore[assignment,misc]
    Reason = None  # type: ignore[assignment,misc]
    AbstractProvider = object  # type: ignore[assignment,misc]
    Metadata = None  # type: ignore[assignment,misc]
    _OPENFEATURE_IMPORT_ERROR = exc
    _OPENFEATURE_AVAILABLE = False


def _context_plan_key(evaluation_context: Any) -> str:
    """Extract the plan key from an OpenFeature evaluation context (blank -> free)."""
    if evaluation_context is None:
        return FREE_PLAN
    attributes = getattr(evaluation_context, "attributes", None) or {}
    plan = str(attributes.get("plan_key", "") or "").strip().lower()
    return plan or FREE_PLAN


if _OPENFEATURE_AVAILABLE:

    class _PlanEntitlementProvider(AbstractProvider):  # type: ignore[misc]
        """In-process OpenFeature provider backed by :data:`PLAN_ENTITLEMENTS`.

        Resolves each requested flag (a feature key) against the plan carried in
        the evaluation context (``attributes['plan_key']``) via the pure
        :func:`resolve`, so the provider holds no per-tenant state. Every resolver
        returns a STATIC-reason detail; the default value the client passes is used
        only when :func:`resolve` itself yields ``None`` (an unknown feature),
        preserving default-deny.
        """

        def get_metadata(self) -> Metadata:  # type: ignore[override]
            return Metadata(name=_CLIENT_NAME)

        def get_provider_hooks(self):  # type: ignore[override]
            return []

        def _resolve(self, flag_key, default_value, evaluation_context):
            plan_key = _context_plan_key(evaluation_context)
            value = resolve(plan_key, flag_key, default_value)
            if value is None:
                value = default_value
            return FlagResolutionDetails(value=value, reason=Reason.STATIC)

        def resolve_boolean_details(
            self, flag_key, default_value, evaluation_context=None
        ):  # type: ignore[override]
            details = self._resolve(flag_key, default_value, evaluation_context)
            details.value = bool(details.value)
            return details

        def resolve_integer_details(
            self, flag_key, default_value, evaluation_context=None
        ):  # type: ignore[override]
            details = self._resolve(flag_key, default_value, evaluation_context)
            try:
                details.value = int(details.value)
            except (TypeError, ValueError):
                details.value = int(default_value)
            return details

        def resolve_float_details(
            self, flag_key, default_value, evaluation_context=None
        ):  # type: ignore[override]
            details = self._resolve(flag_key, default_value, evaluation_context)
            try:
                details.value = float(details.value)
            except (TypeError, ValueError):
                details.value = float(default_value)
            return details

        def resolve_string_details(
            self, flag_key, default_value, evaluation_context=None
        ):  # type: ignore[override]
            details = self._resolve(flag_key, default_value, evaluation_context)
            details.value = str(details.value)
            return details

        def resolve_object_details(
            self, flag_key, default_value, evaluation_context=None
        ):  # type: ignore[override]
            return self._resolve(flag_key, default_value, evaluation_context)

    _provider_registered: bool = False

    def _ensure_provider() -> None:
        """Register the in-process provider with OpenFeature exactly once."""
        global _provider_registered
        if _provider_registered:
            return
        try:
            _of_api.set_provider(_PlanEntitlementProvider(), _CLIENT_NAME)
            _provider_registered = True
        except Exception as exc:  # noqa: BLE001 - degrade to direct map resolution
            logger.warning(
                f"entitlements: OpenFeature provider registration failed, "
                f"falling back to direct plan resolution: {exc}"
            )

    def _sdk_resolve(plan_key: str, feature: str, default: Any) -> Any:
        """Resolve ``feature`` for ``plan_key`` through the OpenFeature client.

        Chooses the typed getter matching the (free-plan) baseline value so the
        vendor-neutral layer returns a correctly-typed result, and passes the plan
        via the evaluation context. Any SDK-level failure degrades to the direct
        :func:`resolve` so an entitlement decision is never lost.
        """
        _ensure_provider()
        context = EvaluationContext(attributes={"plan_key": plan_key})
        client = _of_api.get_client(_CLIENT_NAME)
        baseline = resolve(plan_key, feature, default)
        try:
            if isinstance(baseline, bool):
                return client.get_boolean_value(feature, bool(baseline), context)
            if isinstance(baseline, int):
                return client.get_integer_value(feature, int(baseline), context)
            if isinstance(baseline, float):
                return client.get_float_value(feature, float(baseline), context)
            if isinstance(baseline, str):
                return client.get_string_value(feature, str(baseline), context)
            return client.get_object_value(feature, baseline, context)
        except Exception as exc:  # noqa: BLE001 - never lose a decision to the SDK
            logger.warning(
                f"entitlements: OpenFeature resolution failed for "
                f"feature={feature!r} plan={plan_key!r}; using direct map: {exc}"
            )
            return baseline

else:  # pragma: no cover - exercised only without the SDK installed

    def _sdk_resolve(plan_key: str, feature: str, default: Any) -> Any:
        """SDK absent: resolve directly against the plan map (same safe default)."""
        return resolve(plan_key, feature, default)


# --------------------------------------------------------------------------- #
# Subscription-aware resolution (the public entitlement gate)
# --------------------------------------------------------------------------- #
def active_plan_key(session: Any, workspace_id: str) -> str:
    """Return the workspace's LIVE plan key, or the base **free** plan.

    A subscription grants its plan only while ``status`` is LIVE
    (``active`` / ``trialing`` — see
    :data:`app.models.db.repositories.SUBSCRIPTION_LIVE_STATUSES`). No
    subscription, a lapsed one, or any lookup failure all resolve to **free** so
    a premium entitlement is never granted without a paying, current subscription.
    """
    normalized = (workspace_id or "").strip()
    if not normalized:
        return FREE_PLAN
    try:
        from app.models.db.repositories import (
            SUBSCRIPTION_LIVE_STATUSES,
            SubscriptionRepository,
        )

        sub = SubscriptionRepository(session).get_for_workspace(normalized)
    except Exception as exc:  # noqa: BLE001 - safe default on any lookup failure
        logger.warning(
            f"entitlements: subscription lookup failed for workspace="
            f"{normalized!r}; defaulting to free plan: {exc}"
        )
        return FREE_PLAN
    if sub is None or (sub.status or "") not in SUBSCRIPTION_LIVE_STATUSES:
        return FREE_PLAN
    return (sub.plan_key or FREE_PLAN).strip().lower() or FREE_PLAN


def entitlement_value(
    session: Any, workspace_id: str, feature: str, default: Any = None
) -> Any:
    """Return ``feature``'s entitlement value for a workspace's active plan.

    Resolves the workspace's LIVE plan (:func:`active_plan_key`) then the feature
    value through the OpenFeature client (or the direct map when the SDK is
    absent). The safe default is the base/free plan's value for the feature.
    """
    plan_key = active_plan_key(session, workspace_id)
    return _sdk_resolve(plan_key, feature, default)


def is_entitled(session: Any, workspace_id: str, feature: str) -> bool:
    """Return whether the workspace's active plan grants ``feature`` (boolean gate).

    Truthy resolution counts as entitled: a boolean capability (``sso``,
    ``api_access``) resolves to its plan value, and a numeric limit
    (``max_variants``) counts as entitled when positive. The safe default is the
    base/free plan, so a workspace with no LIVE subscription only ever gets the
    free plan's grants — a premium extra is default-denied.
    """
    value = entitlement_value(session, workspace_id, feature, default=False)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    return bool(value)


# --------------------------------------------------------------------------- #
# Personal entitlements (web plans, packs, mobile Pro) -- one entry point
# --------------------------------------------------------------------------- #
def entitlements(user_id: str) -> dict[str, Any]:
    """``{plan, source, credits_left, clean_download, publish, watermark,
    premium_voice_credits, ai_video_credits, ...}``.

    The per-user view used by paid actions (download, share, publish, editor,
    winner loop). Workspace plans above stay the per-workspace feature gate;
    this delegates to :mod:`app.services.user_entitlements` (fail-closed).
    """
    from app.services.billing.premium_credits import balances
    from app.services.user_entitlements import user_entitlements

    premium = balances(user_id)
    return {
        **user_entitlements(user_id).as_dict(),
        # Separate SKUs: a standard credit never pays for these providers.
        "premium_voice_credits": int(premium.get("premium_voice", 0)),
        "ai_video_credits": int(premium.get("ai_video", 0)),
    }


__all__ = [
    "ENTERPRISE_PLAN",
    "entitlements",
    "FEAT_API_ACCESS",
    "FEAT_MAX_VARIANTS",
    "FEAT_MONTHLY_CREDITS",
    "FEAT_PRIORITY_RENDER",
    "FEAT_SEATS",
    "FEAT_SSO",
    "FEAT_WATERMARK_REMOVAL",
    "FREE_PLAN",
    "PLAN_ENTITLEMENTS",
    "PRO_PLAN",
    "STARTER_PLAN",
    "active_plan_key",
    "entitlement_value",
    "is_entitled",
    "plan_entitlements",
    "resolve",
]
