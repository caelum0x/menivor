"""Render-worker bridge — identity lock → provider IPAdapter/LoRA conditioning.

The compiler attaches a pure :class:`~app.domains.templates.render_spec.IdentityLock`
(or its serialized dict form, as persisted in ``Job.params["character"]["shots"]``)
to every shot of a character reel. This module turns ONE such lock into the
provider-request keys the deployed WAN graph's real "IPAdapter Apply" + "LoraLoader"
nodes read (``ip_reference_url`` / ``ip_weight`` / ``lora_url`` / ``lora_weight``),
minting SHORT-LIVED signed GETs for the creator's OWN reference sheet + trained
LoRA weights — never a raw client URL (SSRF §8).

Pure + deterministic: ``presign`` is injected (``presign(r2_key) -> url``) so this
is fully unit-testable without network/R2. Empty locks yield ``{}`` so a
character-less shot is unaffected.
"""

from __future__ import annotations

from typing import Any, Callable

# Model-native conditioning defaults (mirrors ``render_spec.IdentityLock``).
_DEFAULT_IP_WEIGHT = 0.8
_DEFAULT_LORA_WEIGHT = 0.9


def _get(lock: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a dataclass IdentityLock or its dict form."""
    if isinstance(lock, dict):
        return lock.get(key, default)
    return getattr(lock, key, default)


def provider_identity_lock(lock: Any, *, presign: Callable[[str], str]) -> dict[str, Any]:
    """Map one identity lock into the wan_camera/wan_replicate conditioning dict.

    The FIRST reference image is the primary IPAdapter face/sheet; the LoRA ref is
    the trained weights object. Each OWNED r2 key is presigned into a signed GET.
    Absent inputs are omitted so a partial lock never overwrites a node with a
    blank; a ``None`` lock (character-less shot) yields ``{}``.
    """
    if lock is None:
        return {}
    out: dict[str, Any] = {}

    refs = _get(lock, "reference_images", ()) or ()
    first_ref = next((str(r).strip() for r in refs if str(r).strip()), "")
    if first_ref:
        out["ip_reference_url"] = presign(first_ref)
        out["ip_weight"] = float(_get(lock, "ip_adapter_weight", _DEFAULT_IP_WEIGHT) or _DEFAULT_IP_WEIGHT)

    lora_ref = str(_get(lock, "lora_ref", "") or "").strip()
    if lora_ref:
        out["lora_url"] = presign(lora_ref)
        out["lora_weight"] = float(_get(lock, "lora_weight", _DEFAULT_LORA_WEIGHT) or _DEFAULT_LORA_WEIGHT)

    return out


def build_shot_request(
    lock: Any,
    *,
    presign: Callable[[str], str],
    prompt: str = "",
    num_frames: int = 0,
) -> dict[str, Any]:
    """Assemble the wan_camera provider request for ONE character shot.

    Carries the deterministic per-shot ``seed`` + drift-guard ``negative_prompt``
    from the lock and the presigned IPAdapter/LoRA conditioning under
    ``identity_lock`` (the key ``wan_camera._build_inputs`` copies from). Routing
    a character reel through wan_camera/wan_replicate feeds these to the real
    conditioning nodes so the bound reference reaches the pixels every shot.
    """
    return {
        "prompt": str(prompt or ""),
        "negative_prompt": str(_get(lock, "negative_prompt", "") or ""),
        "num_frames": int(num_frames or 0),
        "seed": int(_get(lock, "seed", 0) or 0),
        "identity_lock": provider_identity_lock(lock, presign=presign),
    }


def presign_r2_get(key: str, *, expires: int = 900) -> str:
    """Mint a short-lived signed GET for an OWNED bucket key (default 15 min).

    Ownership is validated upstream (bind + reel-create guards), so this only
    presigns our OWN keys — never a raw client URL. Import is lazy so this module
    stays import-safe where R2 is unconfigured.
    """
    from app.platform.storage.r2 import get_r2_client

    return get_r2_client().presign_get(str(key).strip(), expires=expires)
