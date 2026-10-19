"""Server-side renderer for Design Studio canvases: PNG pages, a PDF and a slideshow MP4.

The browser editor renders with Canvas 2D; this module renders the same
``canvas_json`` with Pillow so carousels can be produced without a browser
(API request, CLI, worker). Text is wrapped with real font metrics and shrunk
until it fits its box. Image layers are loaded through a caller-supplied
``load_image(key) -> bytes`` (R2 in production, a dict in tests).

The MP4 is a 9:16 / 4:5 slideshow with a slow push-in on every slide and a
short crossfade, made with FFmpeg (already in the API and worker images).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from typing import Any, Callable

from loguru import logger

BOLD_FONTS = ("Inter-Bold.ttf", "Montserrat-ExtraBold.ttf", "BeVietnamPro-Bold.ttf")
REGULAR_FONTS = ("BeVietnamPro-Medium.ttf", "Inter-Bold.ttf")
SLIDE_SECONDS = 3.0
FADE_SECONDS = 0.4
FPS = 24
FFMPEG_TIMEOUT_S = 240

ImageLoader = Callable[[str], bytes]


class RasterError(RuntimeError):
    pass


def _font_dir() -> str:
    try:
        from app.utils import utils

        return utils.font_dir()
    except Exception:  # noqa: BLE001 - fall back to Pillow's bundled font
        return ""


@lru_cache(maxsize=128)
def _font(size: int, bold: bool) -> Any:
    from PIL import ImageFont

    directory = _font_dir()
    for name in BOLD_FONTS if bold else REGULAR_FONTS:
        path = os.path.join(directory, name)
        if directory and os.path.isfile(path):
            return ImageFont.truetype(path, max(6, size))
    return ImageFont.load_default(size=max(6, size))


def _rgba(hex_color: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    raw = (hex_color or "#000000").lstrip("#")
    if len(raw) != 6:
        raw = "000000"
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), int(255 * max(0.0, min(1.0, opacity)))


def wrap(draw: Any, text: str, font: Any, width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        current = ""
        for word in paragraph.split():
            trial = f"{current} {word}".strip()
            if not current or draw.textlength(trial, font=font) <= width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _fit(draw: Any, text: str, props: dict, w: float, h: float) -> tuple[Any, list[str], float]:
    bold = int(props.get("fontWeight") or 400) >= 600
    size = int(props.get("fontSize") or 48)
    line_h = float(props.get("lineHeight") or 1.15)
    while True:
        font = _font(size, bold)
        lines = wrap(draw, text, font, w)
        if len(lines) * size * line_h <= h * 1.08 or size <= 14:
            return font, lines, size * line_h
        size = max(14, int(size * 0.92))


def _draw_text(img: Any, layer: dict) -> None:
    from PIL import ImageDraw

    props = layer["props"]
    text = props.get("text") or ""
    if props.get("uppercase"):
        text = text.upper()
    draw = ImageDraw.Draw(img)
    x, y, w, h = layer["x"], layer["y"], layer["width"], layer["height"]
    font, lines, step = _fit(draw, text, props, w, h)
    fill = _rgba(props.get("color") or "#111111", layer.get("opacity", 1))
    align = props.get("align") or "left"
    for i, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        lx = x + (w - width) / 2 if align == "center" else (x + w - width if align == "right" else x)
        draw.text((lx, y + i * step), line, font=font, fill=fill)


def _draw_shape(img: Any, layer: dict) -> None:
    from PIL import ImageDraw

    props = layer["props"]
    box = [layer["x"], layer["y"], layer["x"] + layer["width"], layer["y"] + layer["height"]]
    opacity = layer.get("opacity", 1)
    fill = None if props.get("fill") in (None, "", "transparent") else _rgba(props["fill"], opacity)
    stroke = props.get("stroke")
    outline = _rgba(stroke, opacity) if stroke and stroke != "transparent" else None
    width = int(props.get("strokeWidth") or 0)
    draw = ImageDraw.Draw(img)
    if layer["type"] == "ellipse":
        draw.ellipse(box, fill=fill, outline=outline, width=width)
    elif layer["type"] == "line":
        draw.line([box[0], box[1], box[2], box[3]], fill=_rgba(props.get("stroke") or "#111111", opacity),
                  width=max(1, width or 4))
    else:
        radius = int(min(props.get("radius") or 0, layer["width"] / 2, layer["height"] / 2))
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _draw_image(img: Any, layer: dict, load_image: ImageLoader | None) -> None:
    from PIL import Image

    if load_image is None:
        return
    try:
        src = Image.open(io.BytesIO(load_image(layer["props"]["key"]))).convert("RGBA")
    except Exception as exc:  # noqa: BLE001 - a missing logo never fails the deck
        logger.info(f"raster: image layer skipped: {exc}")
        return
    bw, bh = int(layer["width"]), int(layer["height"])
    iw, ih = src.size
    cover = layer["props"].get("fit") == "cover"
    scale = max(bw / iw, bh / ih) if cover else min(bw / iw, bh / ih)
    resized = src.resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.LANCZOS)
    left = int(layer["x"] + (bw - resized.width) / 2)
    top = int(layer["y"] + (bh - resized.height) / 2)
    if cover:
        crop = resized.crop(((resized.width - bw) // 2, (resized.height - bh) // 2,
                             (resized.width - bw) // 2 + bw, (resized.height - bh) // 2 + bh))
        resized, left, top = crop, int(layer["x"]), int(layer["y"])
    img.alpha_composite(resized, (max(0, left), max(0, top)))


def render_page(page: dict, width: int, height: int, *, load_image: ImageLoader | None = None) -> bytes:
    """One canvas page -> PNG bytes."""
    from PIL import Image

    img = Image.new("RGBA", (width, height), _rgba(page.get("background") or "#ffffff"))
    for layer in page.get("layers") or []:
        if layer.get("hidden"):
            continue
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        kind = layer.get("type")
        if kind == "text":
            _draw_text(overlay, layer)
        elif kind == "image":
            _draw_image(overlay, layer, load_image)
        else:
            _draw_shape(overlay, layer)
        img.alpha_composite(overlay)
    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_pages(canvas: dict, width: int, height: int, *, load_image: ImageLoader | None = None) -> list[bytes]:
    return [render_page(p, width, height, load_image=load_image) for p in canvas.get("pages") or []]


def to_pdf(pngs: list[bytes]) -> bytes:
    from PIL import Image

    if not pngs:
        raise RasterError("nothing to put in the PDF")
    pages = [Image.open(io.BytesIO(p)).convert("RGB") for p in pngs]
    out = io.BytesIO()
    pages[0].save(out, format="PDF", save_all=True, append_images=pages[1:], resolution=144)
    return out.getvalue()


def ffmpeg_binary() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise RasterError("ffmpeg is not installed on this server") from exc


def slideshow_args(paths: list[str], width: int, height: int, out: str, *, ffmpeg: str = "ffmpeg") -> list[str]:
    """FFmpeg command: push-in on every slide, crossfades between slides, H.264 MP4."""
    frames = int(SLIDE_SECONDS * FPS)
    args = [ffmpeg, "-y", "-loglevel", "error"]
    for path in paths:
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{SLIDE_SECONDS}", "-i", path]
    parts = []
    for i in range(len(paths)):
        parts.append(
            f"[{i}:v]scale={int(width * 1.25) // 2 * 2}:{int(height * 1.25) // 2 * 2},zoompan=z='min(zoom+0.0007,1.06)':d={frames}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={FPS},"
            f"trim=duration={SLIDE_SECONDS},setpts=PTS-STARTPTS,fps={FPS},settb=AVTB,format=yuv420p[v{i}]")
    last = "v0"
    for i in range(1, len(paths)):
        offset = i * (SLIDE_SECONDS - FADE_SECONDS)
        parts.append(f"[{last}][v{i}]xfade=transition=fade:duration={FADE_SECONDS}:offset={offset:.2f}[x{i}]")
        last = f"x{i}"
    args += ["-filter_complex", ";".join(parts), "-map", f"[{last}]", "-r", str(FPS), "-c:v", "libx264",
             "-preset", "superfast", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    return args


def to_mp4(pngs: list[bytes], width: int, height: int, *, run: Callable[..., Any] = subprocess.run) -> bytes:
    """PNG pages -> slideshow MP4 bytes."""
    if not pngs:
        raise RasterError("nothing to put in the video")
    ffmpeg = ffmpeg_binary()
    with tempfile.TemporaryDirectory(prefix="month-mp4-") as work:
        paths = []
        for i, data in enumerate(pngs):
            path = os.path.join(work, f"s{i:02d}.png")
            with open(path, "wb") as fp:
                fp.write(data)
            paths.append(path)
        out = os.path.join(work, "slides.mp4")
        result = run(slideshow_args(paths, width, height, out, ffmpeg=ffmpeg), capture_output=True,
                     timeout=FFMPEG_TIMEOUT_S, check=False)
        if getattr(result, "returncode", 1) != 0 or not os.path.isfile(out):
            err = (getattr(result, "stderr", b"") or b"")[-600:]
            raise RasterError(f"the slideshow video failed: {err.decode('utf-8', 'replace').strip()}")
        with open(out, "rb") as fp:
            return fp.read()


__all__ = ["RasterError", "render_page", "render_pages", "slideshow_args", "to_mp4", "to_pdf", "wrap"]
