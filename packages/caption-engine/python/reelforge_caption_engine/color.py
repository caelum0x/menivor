"""Hex → ASS ``&HAABBGGRR`` colour conversion (mirror of ``src/ass/color.ts``).

ASS stores colours BGR with a leading alpha byte where ``00`` is fully opaque.
Pure integer/string formatting so TS and Python emit byte-identical output.
"""

from __future__ import annotations


def hex_to_ass(hex_color: str, alpha: int = 0) -> str:
    """``"#RRGGBB"`` → ``"&HAABBGGRR"`` (alpha 0 = opaque, 255 = transparent)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"expected #RRGGBB, got {hex_color!r}")
    rr = int(h[0:2], 16)
    gg = int(h[2:4], 16)
    bb = int(h[4:6], 16)
    a = max(0, min(255, int(alpha)))
    return f"&H{a:02X}{bb:02X}{gg:02X}{rr:02X}"
