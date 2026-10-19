"""Pure input validation for template compilation.

Turns a bad instantiation request into a clean, specific error at the boundary
(the router maps :class:`TemplateError` → 422) instead of a confusing failure
deep in the compiler or the render worker. No DB, no IO.
"""

from __future__ import annotations

from .definitions import ShotTemplateDef


class TemplateError(ValueError):
    """An unknown template or an invalid instantiation input (surfaced as 422)."""


def validate_duration(template: ShotTemplateDef, duration_s: float | None) -> float:
    """Clamp/resolve the requested reel duration to the template's bounds."""
    if duration_s is None:
        return template.default_duration_s
    try:
        value = float(duration_s)
    except (TypeError, ValueError) as exc:
        raise TemplateError(f"duration must be a number, got {duration_s!r}") from exc
    if value < template.min_duration_s or value > template.max_duration_s:
        raise TemplateError(
            f"duration {value}s out of range for {template.slug!r} "
            f"[{template.min_duration_s}, {template.max_duration_s}]"
        )
    return value


def validate_inputs(template: ShotTemplateDef, inputs: dict | None) -> dict:
    """Validate the supplied inputs against the template's declared schema.

    Rejects unknown keys and missing required keys; returns a normalized dict
    (string values stripped, choices verified). Optional keys keep their given
    value or the declared default.
    """
    raw = dict(inputs or {})
    known = template.input_keys()
    unknown = set(raw) - set(known)
    if unknown:
        raise TemplateError(f"unknown input(s) for {template.slug!r}: {sorted(unknown)}")

    out: dict = {}
    by_key = {i.key: i for i in template.inputs}
    for key, spec in by_key.items():
        present = key in raw and str(raw[key] or "").strip() != ""
        if not present:
            if spec.required:
                raise TemplateError(f"missing required input {key!r} for {template.slug!r}")
            if spec.default:
                out[key] = spec.default
            continue
        value = raw[key]
        if spec.kind in ("text", "url", "clip", "image", "choice"):
            value = str(value).strip()
        if spec.kind == "choice" and spec.choices and value not in spec.choices:
            raise TemplateError(
                f"input {key!r} must be one of {list(spec.choices)}, got {value!r}"
            )
        out[key] = value
    return out
