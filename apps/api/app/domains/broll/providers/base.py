"""BrollGenProvider Protocol + provider registry (AI B-roll studio).

Deliberately mirrors ``app/services/avatar/base.py`` (the ``TalkingHeadProvider``
registry): a name-keyed map the service/orchestration layer can consult to gate
a run (``is_enabled()``) before spending credits/GPU, and that tests can
monkeypatch with a fake provider.

Where the avatar registry drives *lip-synced talking heads*, this one drives
*AI-generated motion B-roll* — text→video (``t2v``) or image→video (``i2v``)
clips produced by a ComfyUI/Wan workflow deployed as a serverless GPU endpoint
(comfyui-deploy on RunPod). Providers register themselves at import time (see
``broll_gen/comfyui_runpod.py``); ``get_broll_provider`` lazily triggers the
default provider import so callers never touch a concrete backend module.

Contract (identical graceful-degradation guarantee as the avatar Protocol):
implementations MUST NOT raise on external I/O failure — they return ``None``
(or ``[]`` for ``list_workflows``) so a failing generation degrades gracefully
instead of crashing the pipeline. A B-roll failure never fails a reel job.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from loguru import logger


@runtime_checkable
class BrollGenProvider(Protocol):
    """Duck-typed contract every AI B-roll generation backend must satisfy.

    Implementations MUST NOT raise on external I/O failure; they return
    ``None`` (or an empty list for ``list_workflows``) so a failing generation
    degrades gracefully instead of crashing the pipeline.
    """

    name: str

    def is_enabled(self) -> bool:
        """True when the provider is configured (api key + endpoint present)."""
        ...

    def list_workflows(self) -> list[dict]:
        """Return the provider's available workflows / motion presets.

        Some backends (a static comfyui-deploy endpoint) have no queryable
        catalog; those return an empty list and rely on ReelForge's own preset
        table instead. Never raises.
        """
        ...

    def generate_clip(
        self,
        prompt: str,
        *,
        mode: str = "t2v",
        image_url: str | None = None,
        width: int = 1080,
        height: int = 1920,
        duration_s: float = 5.0,
        workflow_id: str | None = None,
        seed: int | None = None,
        extra_inputs: dict | None = None,
        timeout_s: float = 1800.0,
        correlation_id: str = "",
    ) -> dict | None:
        """Generate a short AI motion clip from a prompt (and optional image).

        ``mode`` selects the generation primitive: ``'t2v'`` (text→video, the
        default) or ``'i2v'`` (image→video, which requires ``image_url`` — a
        public/R2 reference image). ``workflow_id`` selects the deployed
        ComfyUI workflow / motion preset; ``extra_inputs`` carries
        workflow-specific knobs (LoRA weights, motion strength, camera path,
        fps) forwarded verbatim to the worker. ``correlation_id`` is the stable
        product workflow id propagated to provider requests and logs.

        Returns ``{'clip_path': <local_path>, 'duration': float,
        'provider_job_id': str}`` (plus best-effort ``clip_key`` / ``clip_url``
        from the R2 re-host) or ``None`` on failure/timeout.
        """
        ...


# Populated at import time by concrete provider modules (e.g. comfyui_runpod).
BROLL_GEN_PROVIDERS: dict[str, BrollGenProvider] = {}

# Providers imported to seed the registry. Kept here (not in each module) so
# ``get_broll_provider`` can lazily import without hardcoding module paths in
# multiple places.
_DEFAULT_PROVIDER_MODULES: tuple[str, ...] = (
    "app.domains.broll.providers.comfyui_deploy",
    "app.domains.broll.providers.pixelle",
    "app.domains.broll.providers.replicate_wan",
)
_DEFAULT_PROVIDER_ID: str = "comfyui"
_providers_loaded: bool = False


def register_broll_provider(provider: BrollGenProvider) -> None:
    """Register a provider instance under its ``name``.

    Idempotent: re-registering the same name overwrites the prior entry,
    which is what tests want when swapping in a fake provider.
    """
    name = getattr(provider, "name", "")
    if not name:
        logger.error("broll_gen provider missing a 'name' attribute; not registered")
        return
    BROLL_GEN_PROVIDERS[name] = provider
    logger.debug(f"registered broll_gen provider: {name}")


def _ensure_providers_loaded() -> None:
    """Import default provider modules once so they self-register.

    Import failures are logged and swallowed — a missing optional dependency
    for one backend must not prevent resolving another already-registered one.
    """
    global _providers_loaded
    if _providers_loaded:
        return
    _providers_loaded = True
    for module_path in _DEFAULT_PROVIDER_MODULES:
        try:
            __import__(module_path)
        except Exception as exc:  # noqa: BLE001 - defensive: keep registry usable
            logger.error(
                f"failed to import broll_gen provider module {module_path}: {exc}"
            )


def _configured_default_id() -> str:
    """The default provider id: ``BROLL_GEN_PROVIDER`` env wins, else ``comfyui``.

    Read from the environment (not app.config) so this module stays import-safe.
    Lets a deployer switch the AI B-roll backend (e.g. to ``pixelle``) without a
    code change.
    """
    import os

    return (os.getenv("BROLL_GEN_PROVIDER") or "").strip() or _DEFAULT_PROVIDER_ID


def get_broll_provider(provider_id: str = "") -> BrollGenProvider:
    """Resolve a registered provider by id.

    With no ``provider_id`` the configured default (``BROLL_GEN_PROVIDER`` env, else
    ``comfyui``) is used. Falls back to that default when an unknown id is
    requested, so an out-of-date client value cannot hard-fail generation. Raises
    ``KeyError`` only if the registry is empty (no provider configured at all),
    which is a genuine deployment error worth surfacing.
    """
    _ensure_providers_loaded()

    default_id = _configured_default_id()
    if not provider_id:
        provider_id = default_id

    provider = BROLL_GEN_PROVIDERS.get(provider_id)
    if provider is not None:
        return provider

    if provider_id != default_id:
        logger.warning(
            f"unknown broll_gen provider '{provider_id}', "
            f"falling back to '{default_id}'"
        )
        fallback = BROLL_GEN_PROVIDERS.get(default_id)
        if fallback is not None:
            return fallback

    raise KeyError(
        f"no broll_gen provider registered for '{provider_id}'; "
        f"available: {sorted(BROLL_GEN_PROVIDERS)}"
    )
