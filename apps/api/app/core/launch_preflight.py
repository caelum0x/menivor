"""Deployment-configuration preflight shared by the CLI gate and API startup.

The check logic previously lived only in ``tools/ops/preflight.py`` and ran in
CI / the release gate — the FastAPI app itself would start with any
configuration. This module makes the exact same checks importable so the API
lifespan can run them at startup:

* **Fail-fast** when the operator has opened a public door
  (``REELFORGE_LAUNCH_MODE=public`` or any launch flag enabled): a missing or
  misshaped required variable aborts startup with a clear list of problems.
* **Warn-only** in ``internal_pilot`` / dev, preserving the existing
  never-block-dev design of ``app/config/config.py``.

**Public tier** (``REELFORGE_PUBLIC_TIER``): ``full`` (default) enforces every
paid provider credential below. ``free`` lets the product launch publicly on
the zero-paid-key formats: only launch approval, infrastructure and a script
LLM key are required; Sentry becomes a warning and ElevenLabs / HeyGen /
ComfyUI become optional "premium" items whose formats are locked at request
time (``app.core.launch.formats``) until their key is configured.

Deliberately stdlib-only with no ``app.config`` import: the CLI wrapper must be
runnable in a bare environment, and reading ``os.environ`` directly mirrors the
historical CLI behavior exactly. Never prints or logs secret values — only
variable *names*.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Mapping

_LAUNCH_FLAGS = (
    "REELFORGE_PUBLIC_LAUNCH_APPROVED",
    "REELFORGE_SIGNUP_ENABLED",
    "REELFORGE_CHECKOUT_ENABLED",
    "REELFORGE_PUBLISHING_ENABLED",
)

# Credit-pack product ids that make Creem usable with signed-return
# confirmation (no webhook secret needed).
CREEM_PACK_PRODUCT_ENV: tuple[str, ...] = (
    "CREEM_PRODUCT_ID_STARTER",
    "CREEM_PRODUCT_ID_PRO",
)


def _present(env: Mapping[str, str], name: str) -> bool:
    return bool(env.get(name, "").strip())


def _enabled(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _present_any(env: Mapping[str, str], *names: str) -> bool:
    return any(_present(env, name) for name in names)


@dataclass(frozen=True)
class Requirement:
    """One public-launch requirement: satisfied when ANY of ``names`` is set.

    ``id`` is the stable identifier clients key on; ``error`` is the historical
    preflight message (kept verbatim so the CLI gate output is unchanged).
    Only variable NAMES ever leave this module, never values.
    """

    id: str
    group: str
    label: str
    names: tuple[str, ...]
    error: str


def _setting(name: str, group: str, label: str) -> Requirement:
    return Requirement(name, group, label, (name,), f"missing required production setting: {name}")


def _alternative(req_id: str, group: str, label: str, names: tuple[str, ...]) -> Requirement:
    return Requirement(
        req_id, group, label, names,
        f"missing required production setting: {label} ({' or '.join(names)})",
    )


_INFRA_REQUIREMENTS: tuple[Requirement, ...] = (
    _alternative("database_url", "infrastructure", "database URL",
                 ("REELFORGE_DATABASE_URL", "NEON_DATABASE_URL", "DATABASE_URL")),
    _alternative("r2_bucket", "infrastructure", "R2 bucket name",
                 ("REELFORGE_R2_BUCKET_NAME", "R2_BUCKET_NAME", "R2_BUCKET")),
    _setting("REDIS_HOST", "infrastructure", "Redis host"),
    _setting("R2_ACCOUNT_ID", "infrastructure", "R2 account id"),
    _setting("R2_ACCESS_KEY_ID", "infrastructure", "R2 access key id"),
    _setting("R2_SECRET_ACCESS_KEY", "infrastructure", "R2 secret access key"),
    _setting("R2_PUBLIC_BASE_URL", "infrastructure", "R2 public base URL"),
)

_SENTRY_REQUIREMENT = _setting("SENTRY_DSN", "observability", "Sentry error reporting")


def _provider(name: str, label: str) -> Requirement:
    return Requirement(name, "providers", label, (name,),
                       f"missing required reel provider credential: {name}")


_ANTHROPIC_REQUIREMENT = _provider("ANTHROPIC_API_KEY", "Anthropic (script generation)")
_PREMIUM_REQUIREMENTS: tuple[Requirement, ...] = (
    _provider("ELEVENLABS_API_KEY", "ElevenLabs (premium voices)"),
    _provider("HEYGEN_API_KEY", "HeyGen (AI avatars)"),
)

# Full tier: every requirement is mandatory (historical behavior, same order).
_PRODUCTION_REQUIREMENTS: tuple[Requirement, ...] = (
    *_INFRA_REQUIREMENTS,
    _SENTRY_REQUIREMENT,
    _ANTHROPIC_REQUIREMENT,
    *_PREMIUM_REQUIREMENTS,
)

PUBLIC_TIERS: tuple[str, ...] = ("full", "free")
FULL_TIER, FREE_TIER = PUBLIC_TIERS

# Script-LLM model override (litellm ``<provider>/<model>`` id). Unset means
# the app default ``anthropic/...``. Mirrored in ``app/config/config.py``.
LLM_MODEL_ENV = "REELFORGE_LLM_MODEL"
# litellm model prefix -> the API-key env var litellm reads for it.
_SCRIPT_LLM_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}
_SCRIPT_LLM_ERROR = (
    "missing required script LLM credential: ANTHROPIC_API_KEY "
    f"(or GROQ_API_KEY with {LLM_MODEL_ENV}=groq/<model>)"
)

_COMFYUI_REQUIREMENTS: tuple[Requirement, ...] = tuple(
    Requirement(name, "broll", f"ComfyUI B-roll: {name}", (name,),
                f"missing configured B-roll provider setting: {name}")
    for name in ("COMFYUI_BASE_URL", "COMFYUI_API_KEY", "COMFYUI_DEPLOYMENT_ID")
)


def _requirement_met(env: Mapping[str, str], requirement: Requirement) -> bool:
    return _present_any(env, *requirement.names)


def public_tier(env: Mapping[str, str] | None = None) -> str:
    """Configured public tier string (unvalidated; checks validate it)."""
    env = os.environ if env is None else env
    return env.get("REELFORGE_PUBLIC_TIER", FULL_TIER).strip().lower() or FULL_TIER


def _is_free_tier(env: Mapping[str, str]) -> bool:
    # An unknown tier value fails closed to the strict ``full`` requirement set.
    return public_tier(env) == FREE_TIER


def script_llm_key_name(env: Mapping[str, str] | None = None) -> str:
    """Env var NAME of the key the configured script LLM needs ("" = unknown)."""
    env = os.environ if env is None else env
    model = env.get(LLM_MODEL_ENV, "").strip().lower()
    prefix = model.split("/", 1)[0] if "/" in model else "anthropic"
    return _SCRIPT_LLM_KEYS.get(prefix, "")


def script_llm_met(env: Mapping[str, str] | None = None) -> bool:
    """True when the script LLM the app will call has its key set."""
    env = os.environ if env is None else env
    name = script_llm_key_name(env)
    return bool(name) and _present(env, name)


def _script_llm_item(env: Mapping[str, str]) -> dict:
    return {
        "id": "script_llm",
        "group": "providers",
        "label": "Script LLM (Anthropic, or Groq via REELFORGE_LLM_MODEL=groq/<model>)",
        "env": ["ANTHROPIC_API_KEY", "GROQ_API_KEY", LLM_MODEL_ENV],
        "met": script_llm_met(env),
        "required": True,
    }


def valid_broll_providers(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """B-roll provider ids accepted by the current tier (``none`` = free only)."""
    env = os.environ if env is None else env
    return ("comfyui", "pixelle", "none") if _is_free_tier(env) else ("comfyui", "pixelle")


def public_launch_requirements(env: Mapping[str, str] | None = None) -> list[dict]:
    """Every public-launch requirement with a met/missing flag (names only).

    The same items the strict startup preflight enforces, plus the explicit
    launch approval itself, so a client can render a precise "private beta"
    checklist. Never includes a value — only whether a name is set. Each item
    carries ``required``: in the ``free`` tier Sentry and the premium provider
    items are listed with ``required=False`` (they unlock formats, they do not
    block launch).
    """
    env = os.environ if env is None else env
    free = _is_free_tier(env)
    items: list[dict] = [
        {
            "id": "REELFORGE_PUBLIC_LAUNCH_APPROVED",
            "group": "launch",
            "label": "Owner approval for public launch",
            "env": ["REELFORGE_PUBLIC_LAUNCH_APPROVED"],
            "met": _enabled(env, "REELFORGE_PUBLIC_LAUNCH_APPROVED"),
            "required": True,
        },
        {
            "id": "REELFORGE_LAUNCH_MODE",
            "group": "launch",
            "label": "Launch mode set to public",
            "env": ["REELFORGE_LAUNCH_MODE"],
            "met": launch_mode(env) == "public",
            "required": True,
        },
    ]
    if free:
        items.extend(_requirement_item(env, r) for r in _INFRA_REQUIREMENTS)
        items.append(_script_llm_item(env))
        items.append(_requirement_item(env, _SENTRY_REQUIREMENT, required=False))
        items.extend(_requirement_item(env, r, required=False) for r in _PREMIUM_REQUIREMENTS)
    else:
        items.extend(_requirement_item(env, r) for r in _PRODUCTION_REQUIREMENTS)
    provider = broll_provider(env)
    accepted = valid_broll_providers(env)
    items.append({
        "id": "BROLL_GEN_PROVIDER",
        "group": "broll",
        "label": f"B-roll provider is {' or '.join(accepted)}",
        "env": ["BROLL_GEN_PROVIDER"],
        "met": provider in accepted,
        "required": True,
    })
    if provider == "comfyui":
        items.extend(
            _requirement_item(env, r, required=not free) for r in _COMFYUI_REQUIREMENTS
        )
    return items


def _requirement_item(
    env: Mapping[str, str], requirement: Requirement, *, required: bool = True
) -> dict:
    return {
        "id": requirement.id,
        "group": requirement.group,
        "label": requirement.label,
        "env": list(requirement.names),
        "met": _requirement_met(env, requirement),
        "required": required,
    }


def missing_public_requirements(env: Mapping[str, str] | None = None) -> list[str]:
    """Ids of the REQUIRED public-launch requirements not yet met (names only)."""
    return [
        item["id"]
        for item in public_launch_requirements(env)
        if item["required"] and not item["met"]
    ]


def optional_missing_requirements(env: Mapping[str, str] | None = None) -> list[str]:
    """Ids of optional (free-tier premium/observability) items not yet met."""
    return [
        item["id"]
        for item in public_launch_requirements(env)
        if not item["required"] and not item["met"]
    ]


def launch_mode(env: Mapping[str, str] | None = None) -> str:
    """Configured launch mode string (unvalidated; checks validate it)."""
    env = os.environ if env is None else env
    return env.get("REELFORGE_LAUNCH_MODE", "internal_pilot").strip().lower()


def broll_provider(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return env.get("BROLL_GEN_PROVIDER", "comfyui").strip().lower()


def any_launch_flag_enabled(env: Mapping[str, str] | None = None) -> bool:
    """True when the operator has flipped any public-exposure launch flag."""
    env = os.environ if env is None else env
    return any(_enabled(env, flag) for flag in _LAUNCH_FLAGS)


def collect_preflight_errors(
    production: bool = False,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Return every configuration problem found (empty list = pass).

    Same checks as ``tools/ops/preflight.py`` (which now delegates here):
    launch-flag coherence always; required production settings, provider
    credentials, and payment-rail completeness when ``production`` is set.
    """
    env = os.environ if env is None else env
    errors: list[str] = []
    mode = launch_mode(env)
    public_approved = _enabled(env, "REELFORGE_PUBLIC_LAUNCH_APPROVED")
    checkout = _enabled(env, "REELFORGE_CHECKOUT_ENABLED")
    publishing = _enabled(env, "REELFORGE_PUBLISHING_ENABLED")

    if mode not in {"internal_pilot", "public"}:
        errors.append("REELFORGE_LAUNCH_MODE must be internal_pilot or public")
    if public_tier(env) not in PUBLIC_TIERS:
        errors.append("REELFORGE_PUBLIC_TIER must be full or free")
    if mode == "public" and not public_approved:
        errors.append("public mode requires REELFORGE_PUBLIC_LAUNCH_APPROVED=true")
    if (checkout or publishing) and mode != "public":
        errors.append("checkout/publishing may be enabled only in approved public mode")

    free = _is_free_tier(env)
    if production and free:
        # Free public tier: infra + a script LLM only. Sentry and the premium
        # providers are surfaced by ``collect_preflight_warnings`` instead.
        for requirement in _INFRA_REQUIREMENTS:
            if not _requirement_met(env, requirement):
                errors.append(requirement.error)
        if not script_llm_met(env):
            errors.append(_SCRIPT_LLM_ERROR)
    elif production:
        for requirement in _PRODUCTION_REQUIREMENTS:
            if not _requirement_met(env, requirement):
                errors.append(requirement.error)

    if checkout:
        rails = {
            "stripe": ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"),
            "iyzico": ("IYZICO_API_KEY", "IYZICO_SECRET_KEY"),
            "creem": ("CREEM_API_KEY", "CREEM_WEBHOOK_SECRET"),
            "polar": ("POLAR_ACCESS_TOKEN", "POLAR_WEBHOOK_SECRET"),
        }
        usable = [
            provider
            for provider, names in rails.items()
            if all(_present(env, name) for name in names)
        ]
        # Creem also confirms payments from its SIGNED success redirect
        # (POST /billing/creem/confirm), so a webhook secret is optional once
        # the API key and at least one credit-pack product id are set.
        if "creem" not in usable and _present(env, "CREEM_API_KEY") and any(
            _present(env, name) for name in CREEM_PACK_PRODUCT_ENV
        ):
            usable.append("creem")
        if not usable:
            errors.append(
                "checkout enabled but no payment rail has API and webhook credentials "
                "(Creem: CREEM_API_KEY plus CREEM_WEBHOOK_SECRET or a "
                "CREEM_PRODUCT_ID_<PACK> for signed-return confirmation)"
            )

    provider = broll_provider(env)
    if provider == "comfyui" and production and not free:
        for requirement in _COMFYUI_REQUIREMENTS:
            if not _requirement_met(env, requirement):
                errors.append(requirement.error)
    accepted = valid_broll_providers(env)
    if provider not in accepted:
        errors.append(
            "BROLL_GEN_PROVIDER must be " + (
                "comfyui, pixelle or none" if free else "comfyui or pixelle"
            )
        )

    return errors


def collect_preflight_warnings(env: Mapping[str, str] | None = None) -> list[str]:
    """Non-blocking free-tier notes: optional items not configured (names only).

    Empty for the ``full`` tier (there, the same items are hard errors).
    """
    env = os.environ if env is None else env
    if not _is_free_tier(env):
        return []
    warnings: list[str] = []
    if not _requirement_met(env, _SENTRY_REQUIREMENT):
        warnings.append("free tier: SENTRY_DSN not set; error reporting is disabled")
    for requirement in _PREMIUM_REQUIREMENTS:
        if not _requirement_met(env, requirement):
            warnings.append(
                f"free tier: {requirement.id} not set; its premium formats are locked"
            )
    if broll_provider(env) == "none" or (
        broll_provider(env) == "comfyui"
        and not all(_requirement_met(env, r) for r in _COMFYUI_REQUIREMENTS)
    ):
        warnings.append("free tier: AI B-roll provider not configured; AI B-roll is locked")
    return warnings


def enforce_startup_preflight(
    warn: Callable[[str], None],
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Run the preflight at API startup and enforce it by launch posture.

    * ``REELFORGE_LAUNCH_MODE=public`` or any launch flag enabled → the full
      production check set runs and any problem **raises** ``RuntimeError``
      listing every missing/misshaped variable (names only, never values).
    * Otherwise (internal_pilot / dev) → coherence checks still run but every
      problem is only reported through ``warn`` so local development and the
      hermetic test suites keep starting exactly as before.
    * ``REELFORGE_PUBLIC_TIER=free`` narrows the strict set (see module doc);
      the relaxed items are reported through ``warn`` instead.

    Returns the collected error list so callers/tests can inspect it.
    """
    env = os.environ if env is None else env
    strict = launch_mode(env) == "public" or any_launch_flag_enabled(env)
    errors = collect_preflight_errors(production=strict, env=env)
    if strict:
        for note in collect_preflight_warnings(env):
            warn(f"startup preflight: {note}")
    if not errors:
        return errors
    if strict:
        summary = "; ".join(errors)
        missing = ", ".join(missing_public_requirements(env)) or "none"
        raise RuntimeError(
            "ReelForge startup preflight failed under a public launch posture "
            f"({len(errors)} problem(s)): {summary}. "
            f"Missing public-launch requirements (see GET /api/v1/launch/status): {missing}"
        )
    for error in errors:
        warn(f"startup preflight (warn-only in pilot/dev): {error}")
    return errors
