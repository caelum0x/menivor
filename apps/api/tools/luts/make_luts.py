"""Generate the three shipped grade LUTs (17x17x17 ``.cube``) deterministically.

Pure math, no image library: each look is a per-channel tone curve (lift,
gamma, gain, contrast around mid grey), a saturation scale around Rec. 709 luma
and a split tint (shadows / highlights). Run from ``apps/api``::

    python tools/luts/make_luts.py            # writes assets/luts/*.cube
    python tools/luts/make_luts.py --check    # exit 1 when a shipped file differs

Looks (ids match ``app.services.compose.vfx.LUT_FILES``):

* ``console-480``: punchy early-2000s game render: more contrast and
  saturation, slightly green-cyan shadows, warm bloomy highlights.
* ``flash-lookbook``: direct flash editorial: lifted blacks, crisp contrast,
  a little less saturation, warm mids, cool highlights.
* ``atelier-film``: warm film stock: soft contrast, lifted blacks, warm tint,
  gentle highlight roll-off, lower saturation.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

SIZE = 17
OUT_DIR = Path(__file__).resolve().parents[2] / "assets" / "luts"
LUMA = (0.2126, 0.7152, 0.0722)


@dataclass(frozen=True)
class Look:
    id: str
    title: str
    lift: tuple[float, float, float]  # added at black, fades to 0 at white
    gain: tuple[float, float, float]  # multiplies white
    gamma: tuple[float, float, float]  # >1 brightens mids
    contrast: float  # around 0.5
    saturation: float
    shadow_tint: tuple[float, float, float]
    highlight_tint: tuple[float, float, float]
    shoulder: float  # 0 = none; >0 compresses highlights


LOOKS: tuple[Look, ...] = (
    Look("console-480", "Menivor console cutscene", lift=(0.0, 0.01, 0.015), gain=(1.0, 0.99, 0.97),
         gamma=(1.02, 1.03, 1.0), contrast=1.10, saturation=1.14, shadow_tint=(-0.01, 0.015, 0.02),
         highlight_tint=(0.03, 0.02, -0.01), shoulder=0.25),
    Look("flash-lookbook", "Menivor flash lookbook", lift=(0.03, 0.02, 0.06), gain=(0.97, 0.95, 0.90),
         gamma=(1.03, 0.99, 0.96), contrast=1.08, saturation=0.88, shadow_tint=(0.0, 0.0, 0.01),
         highlight_tint=(-0.01, 0.0, 0.015), shoulder=0.1),
    Look("atelier-film", "Menivor atelier film", lift=(0.045, 0.035, 0.03), gain=(0.98, 0.95, 0.88),
         gamma=(1.04, 1.01, 0.97), contrast=0.94, saturation=0.86, shadow_tint=(0.012, 0.004, -0.01),
         highlight_tint=(0.02, 0.008, -0.02), shoulder=0.35),
)


def _clamp(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _channel(value: float, look: Look, channel: int) -> float:
    lift, gain, gamma = look.lift[channel], look.gain[channel], look.gamma[channel]
    out = value ** (1.0 / gamma)
    out = lift + (gain - lift) * out
    out = 0.5 + (out - 0.5) * look.contrast
    if look.shoulder > 0 and out > 0.75:  # soft highlight roll-off above 0.75
        excess = out - 0.75
        out = 0.75 + excess / (1.0 + look.shoulder * excess * 4.0)
    return out


def grade(rgb: tuple[float, float, float], look: Look) -> tuple[float, float, float]:
    curved = [_channel(rgb[c], look, c) for c in range(3)]
    luma = sum(LUMA[c] * curved[c] for c in range(3))
    saturated = [luma + (curved[c] - luma) * look.saturation for c in range(3)]
    shadow_w = (1.0 - luma) ** 2
    highlight_w = luma ** 2
    tinted = [saturated[c] + look.shadow_tint[c] * shadow_w + look.highlight_tint[c] * highlight_w
              for c in range(3)]
    return tuple(_clamp(v) for v in tinted)  # type: ignore[return-value]


def cube_text(look: Look, size: int = SIZE) -> str:
    """The ``.cube`` file text (red index changes fastest, as the format requires)."""
    rows = [f'TITLE "{look.title}"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    step = 1.0 / (size - 1)
    for b in range(size):
        for g in range(size):
            for r in range(size):
                out = grade((r * step, g * step, b * step), look)
                rows.append(" ".join(f"{v:.4f}" for v in out))
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--check", action="store_true", help="compare with the shipped files, write nothing")
    args = parser.parse_args(argv)
    stale = []
    for look in LOOKS:
        path = args.out / f"{look.id}.cube"
        text = cube_text(look)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
            continue
        args.out.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path} ({len(text)} bytes)")
    if stale:
        print(f"stale LUTs: {', '.join(stale)}; run tools/luts/make_luts.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
