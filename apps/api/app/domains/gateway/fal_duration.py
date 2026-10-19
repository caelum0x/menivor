"""Per-model ``duration`` argument for fal.ai video endpoints (Wave E M-1, hand-off H4).

fal endpoints do not agree on how a clip length is written. Veo takes
``"8s"``, Hailuo 02 standard takes the strings ``"6"`` or ``"10"``, Pika and
LTX-2 take plain integers, Hailuo 02 Pro has a fixed 6 s and no ``duration``
field at all. The generic Kling adapter sends ``str(int(seconds))`` to every
path, which Veo and Hailuo reject after the queue has already been charged.

This table maps a fal model path to its accepted lengths and the wire form.
Every row was read from fal's public OpenAPI schema
(``https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<path>``) on
2026-09-29. A length a row does not accept raises :class:`DurationUnsupported`
before any reservation or provider call; the gateway answers 422.

Frame-count models (Hunyuan, Mochi, Wan 2.2, LTX-Video, CogVideoX) have no
``duration`` field; they keep the adapter's default body and are only bounded
by the catalog's ``max_seconds``.
"""

from __future__ import annotations

from dataclasses import dataclass

# Wire forms.
STRING = "string"         # "5"
STRING_S = "string_s"     # "8s"
INTEGER = "integer"       # 5
FIXED = "fixed"           # no duration field; one accepted length
FRAMES = "frames"         # no duration field; length set by frame count

SCHEMA_SOURCE = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id="
SCHEMA_DATE = "2026-09-29"


@dataclass(frozen=True)
class DurationSpec:
    form: str
    allowed: tuple[int, ...] = ()


class DurationUnsupported(ValueError):
    """The model does not accept this clip length (refused before any provider call)."""

    status_code = 422

    def __init__(self, model_path: str, seconds: int, allowed: tuple[int, ...]) -> None:
        self.model_path = model_path
        self.seconds = seconds
        self.allowed = allowed
        lengths = ", ".join(f"{s}s" for s in allowed)
        super().__init__(
            f"{model_path} does not render {seconds}s clips; choose one of: {lengths}"
        )


def _range(lo: int, hi: int) -> tuple[int, ...]:
    return tuple(range(lo, hi + 1))


# Aliases the Kling adapter resolves (``KLING_MODELS``) map to the same rows.
_ALIASES: dict[str, str] = {
    "kling-t2v": "fal-ai/kling-video/v1.6/standard/text-to-video",
    "kling-i2v": "fal-ai/kling-video/v1.6/standard/image-to-video",
    "kling-pro-t2v": "fal-ai/kling-video/v2/master/text-to-video",
    "kling-pro-i2v": "fal-ai/kling-video/v2/master/image-to-video",
}

FAL_DURATIONS: dict[str, DurationSpec] = {
    # Veo on fal: "4s" | "6s" | "8s".
    "fal-ai/veo3": DurationSpec(STRING_S, (4, 6, 8)),
    "fal-ai/veo3/fast": DurationSpec(STRING_S, (4, 6, 8)),
    "fal-ai/veo3.1": DurationSpec(STRING_S, (4, 6, 8)),
    "fal-ai/veo3.1/fast": DurationSpec(STRING_S, (4, 6, 8)),
    # MiniMax Hailuo 02: standard "6" | "10"; Pro (1080p) is a fixed 6 s clip.
    "fal-ai/minimax/hailuo-02/standard/text-to-video": DurationSpec(STRING, (6, 10)),
    "fal-ai/minimax/hailuo-02/standard/image-to-video": DurationSpec(STRING, (6, 10)),
    "fal-ai/minimax/hailuo-02/pro/text-to-video": DurationSpec(FIXED, (6,)),
    "fal-ai/minimax/hailuo-02/pro/image-to-video": DurationSpec(FIXED, (6,)),
    # Kling: "5" | "10", except v3 Pro which takes "3" to "15".
    "fal-ai/kling-video/v1.6/standard/text-to-video": DurationSpec(STRING, (5, 10)),
    "fal-ai/kling-video/v1.6/standard/image-to-video": DurationSpec(STRING, (5, 10)),
    "fal-ai/kling-video/v2/master/text-to-video": DurationSpec(STRING, (5, 10)),
    "fal-ai/kling-video/v2/master/image-to-video": DurationSpec(STRING, (5, 10)),
    "fal-ai/kling-video/v2.1/master/text-to-video": DurationSpec(STRING, (5, 10)),
    "fal-ai/kling-video/v2.5-turbo/pro/text-to-video": DurationSpec(STRING, (5, 10)),
    "fal-ai/kling-video/v3/pro/text-to-video": DurationSpec(STRING, _range(3, 15)),
    # Seedance: v1 Pro "2" to "12"; 2.0 (and fast) "4" to "15".
    "fal-ai/bytedance/seedance/v1/pro/text-to-video": DurationSpec(STRING, _range(2, 12)),
    "bytedance/seedance-2.0/text-to-video": DurationSpec(STRING, _range(4, 15)),
    "bytedance/seedance-2.0/fast/text-to-video": DurationSpec(STRING, _range(4, 15)),
    "bytedance/seedance-2.0/image-to-video": DurationSpec(STRING, _range(4, 15)),
    "bytedance/seedance-2.0/reference-to-video": DurationSpec(STRING, _range(4, 15)),
    # Wan 2.5 preview "5" | "10"; Wan 2.2 A14B is frame-count based.
    "fal-ai/wan-25-preview/text-to-video": DurationSpec(STRING, (5, 10)),
    "fal-ai/wan/v2.2-a14b/text-to-video": DurationSpec(FRAMES),
    # Integers.
    "fal-ai/ltx-2/text-to-video": DurationSpec(INTEGER, (6, 8, 10)),
    "fal-ai/pika/v2.2/text-to-video": DurationSpec(INTEGER, (5, 10)),
    # Others.
    "fal-ai/pixverse/v4.5/text-to-video": DurationSpec(STRING, (5, 8)),
    "fal-ai/luma-dream-machine/ray-2": DurationSpec(STRING_S, (5, 9)),
    "fal-ai/hunyuan-video": DurationSpec(FRAMES),
    "fal-ai/mochi-v1": DurationSpec(FRAMES),
    "fal-ai/ltx-video": DurationSpec(FRAMES),
    "fal-ai/cogvideox-5b": DurationSpec(FRAMES),
}


def resolve_path(model_ref: str) -> str:
    return _ALIASES.get(model_ref, model_ref)


def spec_for(model_ref: str) -> DurationSpec | None:
    return FAL_DURATIONS.get(resolve_path(model_ref))


def check_seconds(model_ref: str, seconds: int) -> None:
    """Raise :class:`DurationUnsupported` when the model cannot render ``seconds``."""
    spec = spec_for(model_ref)
    if spec is None or not spec.allowed:
        return
    if int(seconds) not in spec.allowed:
        raise DurationUnsupported(resolve_path(model_ref), int(seconds), spec.allowed)


def duration_extra(model_ref: str, seconds: int) -> dict:
    """The ``duration`` override for the fal request body (empty: keep the adapter default).

    Raises :class:`DurationUnsupported` for a length the model does not accept.
    """
    check_seconds(model_ref, seconds)
    spec = spec_for(model_ref)
    n = int(seconds)
    if spec is None or spec.form in (FIXED, FRAMES):
        return {}
    if spec.form == STRING_S:
        return {"duration": f"{n}s"}
    if spec.form == INTEGER:
        return {"duration": n}
    return {"duration": str(n)}
