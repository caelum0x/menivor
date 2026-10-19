"""The "Made with Menivor" end card (a short silent clip, spliced as the reel's outro).

Calm and plain on purpose: black background, the product name and address in
white, then "Made with Menivor" and menivor.com in grey. No emoji, no logo
art, so it reads on any feed. Built with ffmpeg ``drawtext``; text goes
through files (``textfile=``) so no product name can break the filter graph.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CARD_SECONDS = 3.0
WIDTH, HEIGHT = 1080, 1920


@dataclass(frozen=True)
class CardText:
    name: str
    address: str
    tagline: str = "Made with Menivor"
    footer: str = "menivor.com"


CARDS: dict[str, CardText] = {
    "bidstage": CardText("Bidstage", "bidstage.app"),
    "mail": CardText("Scribase Mail", "mail.scribase.com"),
    "oxhan": CardText("Oxhan Atelier", "oxhanatelier.com"),
    "menivor": CardText("Menivor", "menivor.com", tagline="Made with Menivor", footer="Make yours free"),
}


def _drawtext(textfile: str, font: str, size: int, color: str, y: str) -> str:
    return (
        f"drawtext=fontfile={font}:textfile={textfile}:fontsize={size}:fontcolor={color}"
        f":x=(w-text_w)/2:y={y}"
    )


def build_command(card: CardText, out_path: str, workdir: str) -> list[str]:
    """The ffmpeg argv for ``card`` (text written to files under ``workdir``)."""
    files = {}
    for key, value in (("name", card.name), ("address", card.address), ("tagline", card.tagline), ("footer", card.footer)):
        path = os.path.join(workdir, f"{key}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(value.replace("\n", " ").strip())
        files[key] = path
    vf = ",".join(
        [
            _drawtext(files["name"], FONT_BOLD, 104, "white", "h*0.40"),
            _drawtext(files["address"], FONT_REGULAR, 56, "white@0.85", "h*0.40+150"),
            _drawtext(files["tagline"], FONT_REGULAR, 44, "0x9a9a9a", "h*0.78"),
            _drawtext(files["footer"], FONT_REGULAR, 38, "0x6e6e6e", "h*0.78+70"),
            f"fade=t=in:st=0:d=0.35",
        ]
    )
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r=30:d={CARD_SECONDS}",
        "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-movflags", "+faststart", "-an", out_path,
    ]


def render(product: str, out_path: str) -> str:
    card = CARDS[product]
    with tempfile.TemporaryDirectory(prefix="megaphone-card-") as work:
        subprocess.run(build_command(card, out_path, work), check=True, timeout=120)
    if not os.path.getsize(out_path):
        raise RuntimeError(f"end card for {product} is empty")
    return out_path
