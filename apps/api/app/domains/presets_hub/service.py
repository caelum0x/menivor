"""Preset shelf service (MH2): visible tiles, tile -> Create body, run timing.

Nothing here charges: a filter preset resolves to the body of the normal
``POST /jobs`` call (standard credits, price shown first by ``/jobs/quote``);
a model preset resolves to the body of ``POST /generation/broll/generate``
(AI-video credits, debited by that route). The shelf only records when the
tile was tapped so the time to the first result can be measured and shown.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from . import catalog, previews

FILTER_TARGET_S = 180
MODEL_TARGET_S = 120
TASK_STATE_COMPLETE = 1
MAX_SUBJECT = 300
MAX_PROMPT = 500
#: Faceless footage behind a filter preset reel (a bundled first-party loop).
DEFAULT_BACKGROUND = "block-runner"
CREDIT_LABELS = {catalog.CREDIT_STANDARD: "Standard credits", catalog.CREDIT_AI_VIDEO: "AI-video credits"}


class PresetNotFound(LookupError):
    pass


class PresetInputError(ValueError):
    pass


def target_seconds(preset: catalog.Preset) -> int:
    return MODEL_TARGET_S if preset.kind == catalog.KIND_MODEL else FILTER_TARGET_S


def tile(preset: catalog.Preset, entry: Mapping) -> dict[str, Any]:
    """The public tile: no camera or prompt internals, no vendor names."""
    return {
        "id": preset.id,
        "name": preset.name,
        "blurb": preset.blurb,
        "kind": preset.kind,
        "credit_kind": preset.credit_kind,
        "credit_label": CREDIT_LABELS[preset.credit_kind],
        "inputs": list(preset.inputs),
        "preview": previews.public_urls(entry),
        "create_url": f"/presets-gallery?use={preset.id}",
        "target_seconds": target_seconds(preset),
    }


def shelf(manifest: Mapping[str, Mapping] | None = None) -> list[dict[str, Any]]:
    manifest = previews.load_manifest() if manifest is None else manifest
    return [tile(p, manifest[p.id]) for p in catalog.all_presets() if previews.visible(p, manifest.get(p.id))]


def visible_preset(preset_id: str, manifest: Mapping[str, Mapping] | None = None) -> catalog.Preset:
    manifest = previews.load_manifest() if manifest is None else manifest
    preset = catalog.get(preset_id)
    if preset is None or not previews.visible(preset, manifest.get(preset.id)):
        raise PresetNotFound(preset_id)
    return preset


def _clean(text: str, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _is_link(text: str) -> bool:
    parts = urlsplit(text)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def subject_params(subject: str) -> dict[str, Any]:
    """Standard faceless reel params for a typed topic or a pasted link."""
    text = _clean(subject, MAX_SUBJECT)
    if not text:
        raise PresetInputError("type a topic or paste a link")
    params: dict[str, Any] = {
        "video_subject": urlsplit(text).netloc if _is_link(text) else text,
        "layout": "captions_only",
        "background_id": DEFAULT_BACKGROUND,
        "aspect": "9:16",
    }
    if _is_link(text):
        params["source_url"] = text
    return params


def brand_params(brand: Mapping[str, Any] | None) -> dict[str, Any]:
    """Standard reel params a brand kit sets: voice, captions, music, language, logo."""
    if not brand:
        return {}
    out: dict[str, Any] = {k: brand[k] for k in ("voice_name", "caption_style", "music_id", "language")
                           if brand.get(k)}
    if brand.get("logo"):
        out["watermark_key"] = str(brand["logo"])
        out["watermark_enabled"] = True
    return out


def _brand_prompt(brand: Mapping[str, Any] | None) -> str:
    if not brand:
        return ""
    parts = []
    if brand.get("name"):
        parts.append(f"{brand['name']} brand look")
    colors = [str(c) for c in (brand.get("colors") or [])][:3]
    if colors:
        parts.append("brand colours " + " and ".join(colors))
    return ", ".join(parts)


def _character_prompt(character: Mapping[str, Any], action: str) -> str:
    from app.domains.characters.consistency import CharacterProfile, build_shot_prompt

    profile = CharacterProfile(
        character_id=str(character.get("id") or ""), name=str(character.get("name") or ""),
        descriptors=tuple(character.get("descriptors") or ()), style=str(character.get("style") or ""),
        reference_images=tuple(character.get("reference_images") or ()), lora_ref=str(character.get("lora_ref") or ""),
        negative=tuple(character.get("negative") or ()),
    )
    return build_shot_prompt(profile, action).prompt


def resolve(
    preset_id: str,
    *,
    subject: str,
    image_key: str | None = None,
    brand: Mapping[str, Any] | None = None,
    character: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The Create call a tile makes: ``{"route", "body"}``.

    ``brand`` (a brand kit view) is accepted by every preset; ``character`` (an
    owned character view) leads the prompt of model presets and fills their
    image slot with its first reference.
    """
    preset = catalog.get(preset_id)
    if preset is None:
        raise PresetNotFound(preset_id)
    text = _clean(subject, MAX_SUBJECT)
    if preset.kind == catalog.KIND_FILTER:
        params = {
            **subject_params(text),
            **brand_params(brand),
            "camera_motion": preset.camera_motion,
            "effects": list(preset.effects),
            "vfx_intensity": preset.intensity,
        }
        return {"route": "jobs", "body": {"params": params, "variants": 1}, "preset_id": preset.id}
    if not text:
        raise PresetInputError("type a topic or paste a link")
    references = list((character or {}).get("reference_images") or [])
    shots = list((brand or {}).get("product_shots") or [])
    image = str(image_key or "").strip() or (references[0] if references else "") or (shots[0] if shots else "")
    if preset.needs_image and not image:
        raise PresetInputError("this preset animates your own image; add one first")
    prompt = preset.prompt_template.format(subject=text)
    if character:
        prompt = _character_prompt(character, prompt)
    extra = _brand_prompt(brand)
    if extra:
        prompt = f"{prompt}, {extra}"
    body: dict[str, Any] = {"prompt": prompt[:MAX_PROMPT], "mode": "i2v" if preset.needs_image else "t2v"}
    if preset.needs_image:
        body["image_key"] = image[:512]
    plan: dict[str, Any] = {"route": "generation/broll/generate", "body": body, "preset_id": preset.id}
    if character:
        plan["character_id"] = str(character.get("id") or "")
    return plan


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def run_view(job: Mapping[str, Any]) -> dict[str, Any] | None:
    """Tap-to-first-result timing for a job that a preset tile started."""
    run = (job.get("params") or {}).get("preset_run")
    if not isinstance(run, Mapping):
        return None
    preset = catalog.get(str(run.get("preset_id") or ""))
    target = target_seconds(preset) if preset else FILTER_TARGET_S
    opened = _as_utc(run.get("opened_at"))
    seconds = None
    if job.get("state") == TASK_STATE_COMPLETE and opened is not None:
        done = _as_utc(job.get("updated_at"))
        if done is not None:
            seconds = max(0, int(round((done - opened).total_seconds())))
    return {
        "preset_id": run.get("preset_id"),
        "seconds_to_result": seconds,
        "target_seconds": target,
        "within_target": None if seconds is None else seconds <= target,
    }
