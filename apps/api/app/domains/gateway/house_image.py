"""House-paid image generation (no user wallet), with optional reference images.

Used by flows that already priced the work for the user (story frames, character
turnaround sheets): the image is paid by us, so no gateway debit happens here.

``reference_urls`` are public (presigned) URLs in @ImageN order. Only a catalogue
row that takes references (``"images"`` in ``inputs``) can receive them; any other
row refuses them instead of dropping them silently.
"""

from __future__ import annotations

from typing import Sequence

DOWNLOAD_TIMEOUT_S = 90.0
MAX_PROMPT_CHARS = 1800


def _download(url: str, timeout_s: float = DOWNLOAD_TIMEOUT_S) -> bytes:
    import requests

    response = requests.get(url, timeout=timeout_s)
    response.raise_for_status()
    return response.content


def _model(model_id: str):
    from app.domains.gateway.media_catalog import image_models

    wanted = str(model_id or "").strip()
    model = next((m for m in image_models() if m.id == wanted), None)
    if model is None:
        raise LookupError(f"image model {wanted!r} is not configured")
    return model


def house_image(prompt: str, *, model_id: str, reference_urls: Sequence[str] = (), correlation_id: str = "",
                negative: str = "", download=_download) -> bytes:
    """One image from ``model_id`` (house-paid); returns the image bytes."""
    from app.domains.gateway.media_gateway import _provider_request
    from app.domains.gateway.provider_execution import MediaProviderExecutor

    text = " ".join(str(prompt or "").split())
    if not text:
        raise ValueError("an image needs a prompt")
    model = _model(model_id)
    refs = tuple(str(u) for u in reference_urls or () if u)
    if refs and "images" not in model.inputs:
        raise ValueError(f"{model.id} does not take reference images; pick a reference image model")
    if negative:
        text = f"{text}. Avoid: {negative}"
    execution = MediaProviderExecutor().submit(_provider_request(
        model, correlation_id=correlation_id or "house-image", prompt=text[:MAX_PROMPT_CHARS],
        cost_micros=model.price_micros, input_refs=refs))
    return download(execution.outputs[0].reference)


__all__ = ["house_image"]
