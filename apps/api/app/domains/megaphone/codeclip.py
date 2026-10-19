"""A plain code-card clip for the Mail Studio demo ("switch from Resend in one line").

Two beats on a dark editor-like background: the Resend client as it is, then
the same code with the one changed line highlighted. Rendered with ffmpeg
``drawtext`` from text files, used as the reel's footage via the public
upload API.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

from app.domains.megaphone.endcard import HEIGHT, WIDTH

FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BEAT_SECONDS = 16.0
#: Bump when the look changes so the weekly job is re-rendered, not replayed.
VERSION = 2
#: Menivor burns captions in the top third; keep that band empty.
CODE_TOP = 760
HEADLINE_Y = 1420

BEFORE = (
    'import { Resend } from "resend";',
    "",
    "const resend = new Resend(",
    "  process.env.RESEND_API_KEY",
    ");",
    "",
    "await resend.emails.send({ ... });",
)
AFTER = (
    'import { Resend } from "resend";',
    "",
    "const resend = new Resend(",
    "  process.env.RESEND_API_KEY,",
    '  { baseUrl: "https://mail-api.scribase.com" }',
    ");",
    "",
    "await resend.emails.send({ ... });",
)
CHANGED_LINE = 4  # index in AFTER


def _write(workdir: str, name: str, text: str) -> str:
    path = os.path.join(workdir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _code_filters(workdir: str, lines: tuple[str, ...], start: float, end: float, highlight: int | None) -> list[str]:
    out: list[str] = []
    top, step = CODE_TOP, 78
    enable = f"enable='between(t,{start},{end})'"
    for i, line in enumerate(lines):
        if not line:
            continue
        path = _write(workdir, f"l{start:.0f}_{i}.txt", line)
        y = top + i * step
        if highlight == i:
            out.append(f"drawbox=x=40:y={y - 16}:w={WIDTH - 80}:h=70:color=0x1f6f3f@0.55:t=fill:{enable}")
        color = "0xb8f5c8" if highlight == i else "0xe6e6e6"
        out.append(
            f"drawtext=fontfile={FONT_MONO}:textfile={path}:fontsize=38:fontcolor={color}:x=70:y={y}:{enable}"
        )
    return out


def build_command(out_path: str, workdir: str) -> list[str]:
    total = BEAT_SECONDS * 2
    head1 = _write(workdir, "h1.txt", "Your Resend code today")
    head2 = _write(workdir, "h2.txt", "Scribase Mail: change one line")
    filters = [
        f"drawtext=fontfile={FONT_BOLD}:textfile={head1}:fontsize=56:fontcolor=white:x=70:y={HEADLINE_Y}:enable='between(t,0,{BEAT_SECONDS})'",
        f"drawtext=fontfile={FONT_BOLD}:textfile={head2}:fontsize=56:fontcolor=white:x=70:y={HEADLINE_Y}:enable='between(t,{BEAT_SECONDS},{total})'",
        *_code_filters(workdir, BEFORE, 0, BEAT_SECONDS, None),
        *_code_filters(workdir, AFTER, BEAT_SECONDS, total, CHANGED_LINE),
    ]
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=0x0d1117:s={WIDTH}x{HEIGHT}:r=30:d={total}",
        "-vf", ",".join(filters), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-movflags", "+faststart", "-an", out_path,
    ]


def render(out_path: str) -> str:
    with tempfile.TemporaryDirectory(prefix="megaphone-code-") as work:
        subprocess.run(build_command(out_path, work), check=True, timeout=300)
    return out_path
