"""Genre shot-template definition model (system templates).

A :class:`ShotTemplateDef` is the authored, versioned description of a viral
short-form genre: its segment-slot graph, default layout / aspect / camera / VFX,
its audio plan, its caption style, and the ``inputs`` a creator must supply to
instantiate it. System templates are defined as pure code under ``presets/`` and
registered in ``registry.py``; custom user templates (DB-backed) are a later
phase that reuses this exact shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .slots import AudioPlanDef, SlotSpec


@dataclass(frozen=True)
class TemplateInput:
    """One input a creator supplies to instantiate a template.

    ``kind`` ∈ {``text``, ``clip``, ``image``, ``url``, ``choice``, ``number``}.
    ``target`` names the slot role(s) or reel field the value feeds (documentation
    + validation hint). ``required`` gates compilation.
    """

    key: str
    kind: str
    label: str
    required: bool = True
    help: str = ""
    choices: tuple[str, ...] = ()
    default: str = ""


@dataclass(frozen=True)
class ShotTemplateDef:
    """A named, versioned genre template."""

    slug: str
    name: str
    genre: str
    version: str
    description: str
    slots: tuple[SlotSpec, ...]
    inputs: tuple[TemplateInput, ...]
    aspect: str = "9:16"
    layout: str = "full"            # pip | hook_intro | split | full
    default_duration_s: float = 45.0
    min_duration_s: float = 5.0
    max_duration_s: float = 90.0
    caption_style: str = "karaoke_yellow"
    camera_motion: str = "none"
    effects: tuple[str, ...] = ()
    vfx_intensity: int = 50
    audio: AudioPlanDef = field(default_factory=AudioPlanDef)
    loopable: bool = False
    # Default background-library id for the secondary/looping visual track, used
    # when the caller supplies no gameplay/B-roll clip (content.background_library).
    default_background: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.slots:
            raise ValueError(f"template {self.slug!r} has no slots")
        # Slot orders must be unique + contiguous-ish (strictly increasing).
        orders = [s.order for s in self.slots]
        if orders != sorted(orders) or len(set(orders)) != len(orders):
            raise ValueError(f"template {self.slug!r} slot orders must be strictly increasing + unique")
        if not (self.min_duration_s <= self.default_duration_s <= self.max_duration_s):
            raise ValueError(
                f"template {self.slug!r} duration bounds invalid: "
                f"min={self.min_duration_s} default={self.default_duration_s} max={self.max_duration_s}"
            )
        # Exactly-one hook gate keeps the retention contract unambiguous.
        gates = [s for s in self.slots if s.hook_gate]
        if len(gates) > 1:
            raise ValueError(f"template {self.slug!r} has multiple hook_gate slots")

    def input_keys(self) -> frozenset[str]:
        return frozenset(i.key for i in self.inputs)

    def required_input_keys(self) -> frozenset[str]:
        return frozenset(i.key for i in self.inputs if i.required)
