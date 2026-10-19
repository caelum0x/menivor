"""Build a style's 1080x1920 visual track (the "screen" the reel composes over).

The compose stage burns narration captions over a screen track. For a style
reel there is no uploaded screen recording, so this renders one with FFmpeg
from the style's product visuals (page image, AI scenes or a title card) and
its looping companion clip:

* ``stack``        - visuals on top (1080x960), loop below (1080x960), gold seam.
* ``meme``         - white meme-caption band with the hook, visuals, then loop.
* ``full``         - visuals full screen.
* ``pov``          - dimmed loop full screen, visuals as a card, POV line on top.
* ``before_after`` - a grey "before" half over a vivid "after" half, labelled.

:func:`build_command` is pure (it only returns the argv), so every layout is
unit-tested without FFmpeg; :func:`render_scene` writes the text files and runs
it. Text is always passed through ``textfile=`` (never inline) so user-derived
words can not break out of the filtergraph.
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from dataclasses import dataclass, field

WIDTH = 1080
HEIGHT = 1920
FPS = 30
HALF = HEIGHT // 2
MEME_BAND = 560
GOLD = "0xE8B64C"
SCENES = ("stack", "meme", "full", "pov", "before_after", "story", "character")
# Scenes whose base layer is the looping companion clip.
LOOP_SCENES = ("stack", "meme", "pov", "story", "character")
# Scenes that draw no product visuals (the story card carries the words).
NO_VISUAL_SCENES = ("story",)
STORY_CARD_S = 5.0
CHARACTER_SIZE = 440
_MAX_TEXT = 160


@dataclass(frozen=True)
class SceneSpec:
    scene: str
    images: tuple[str, ...]
    duration_s: float
    font_path: str
    loop_path: str = ""
    texts: dict = field(default_factory=dict)  # name -> text file path
    # A moving product visual (page recording); replaces ``images`` when set.
    visual_video: str = ""


def _escape(value: str) -> str:
    """Escape a path/value for use inside an FFmpeg filter option."""
    return str(value).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def wrap(text: str, width: int, max_lines: int) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()[:_MAX_TEXT]
    lines = textwrap.wrap(clean, width=width) or [""]
    if len(lines) > max_lines:
        # A hook's first sentence is the meme line; show it whole before cutting with "…".
        first = re.split(r"(?<=[.!?])\s+", clean, maxsplit=1)[0]
        first_lines = textwrap.wrap(first, width=width)
        if first != clean and 0 < len(first_lines) <= max_lines:
            return "\n".join(first_lines)
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;:") + "…"
    return "\n".join(lines)


def split_before_after(hook: str, fallback_after: str) -> tuple[str, str]:
    """``("before text", "after text")`` from a before/after hook."""
    text = re.sub(r"\s+", " ", str(hook or "")).strip()
    match = re.search(r"before[^:]*:\s*(.+?)\s*after[^:]*:\s*(.+)", text, re.IGNORECASE)
    if not match:
        match = re.search(r"önce[^:]*:\s*(.+?)\s*sonra[^:]*:\s*(.+)", text, re.IGNORECASE)
    if match:
        return _sentence_case(match.group(1)), _sentence_case(match.group(2))
    return "Doing it the slow way", (fallback_after or "Doing it with one click")


def _sentence_case(text: str) -> str:
    clean = str(text or "").strip(" .,;")
    return clean[:1].upper() + clean[1:]


def texts_for(scene: str, hook: str, title: str) -> dict[str, str]:
    """The on-screen strings a scene draws (already wrapped)."""
    if scene == "meme":
        return {"band": wrap(hook, 26, 5)}
    if scene == "pov":
        return {"pov": wrap(hook, 24, 4)}
    if scene in ("story", "character"):
        return {"card_head": "Story time", "card": wrap(hook, 30, 5)}
    if scene == "before_after":
        before, after = split_before_after(hook, title)
        return {
            "before_label": "BEFORE",
            "after_label": "AFTER",
            "before": wrap(before, 28, 3),
            "after": wrap(after, 28, 3),
        }
    return {}


def _oversize(value: int) -> int:
    return int(value * 1.08) // 2 * 2


def panel_size(scene: str) -> tuple[int, int]:
    """The visuals panel size a scene draws its images into."""
    if scene == "full":
        return WIDTH, HEIGHT
    if scene == "meme":
        return WIDTH, (HEIGHT - MEME_BAND) // 2
    if scene == "pov":
        return 960, 900
    return WIDTH, HALF


def plate_command(image: str, width: int, height: int, out_path: str, *, ffmpeg: str = "ffmpeg") -> list[str]:
    """One still "plate": the image fitted over its own blurred cover, 8% oversized.

    Rendered once per image so the per-frame work is only a crop (a slow pan).
    """
    wide, tall = _oversize(width), _oversize(height)
    graph = (
        f"split[a][b];[a]scale={wide}:{tall}:force_original_aspect_ratio=increase,"
        f"crop={wide}:{tall},boxblur=24:2,eq=brightness=-0.10[bg];"
        f"[b]scale={wide}:{tall}:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
    )
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", image,
            "-filter_complex", graph, "-frames:v", "1", out_path]


def _panel(index: int, width: int, height: int, seg: float, out: str) -> str:
    """A slowly panning ``width``x``height`` window over plate input ``index``."""
    direction = f"t/{seg:.3f}" if index % 2 == 0 else f"(1-t/{seg:.3f})"
    return (
        f"[{index}:v]fps={FPS},crop={width}:{height}:x='(iw-ow)*{direction}':y='(ih-oh)/2',"
        f"setsar=1,trim=duration={seg:.3f},setpts=PTS-STARTPTS[{out}]"
    )


def _visuals(spec: SceneSpec, width: int, height: int, out: str) -> str:
    if spec.visual_video:
        return (
            f"[0:v]fps={FPS},scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,format=yuv420p[{out}]"
        )
    count = len(spec.images)
    seg = max(0.5, spec.duration_s / count)
    parts = [_panel(i, width, height, seg, f"v{i}") for i in range(count)]
    labels = "".join(f"[v{i}]" for i in range(count))
    parts.append(f"{labels}concat=n={count}:v=1:a=0,format=yuv420p[{out}]")
    return ";".join(parts)


def _loop(index: int, width: int, height: int, out: str, dim: float = 0.0) -> str:
    adjust = f",eq=brightness={-abs(dim):.2f}" if dim else ""
    return (
        f"[{index}:v]fps={FPS},scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1{adjust},format=yuv420p[{out}]"
    )


def _text(spec: SceneSpec, name: str, *, size: int, color: str, x: str, y: str, box: str = "") -> str:
    path = spec.texts.get(name, "")
    if not path:
        return ""
    extra = f":box=1:boxcolor={box}:boxborderw=28" if box else ""
    return (
        f"drawtext=fontfile='{_escape(spec.font_path)}':textfile='{_escape(path)}':"
        f"fontsize={size}:fontcolor={color}:line_spacing=14:x={x}:y={y}{extra}"
    )


def _chain(label_in: str, filters: list[str], label_out: str) -> str:
    active = [f for f in filters if f]
    if not active:
        return f"[{label_in}]null[{label_out}]"
    return f"[{label_in}]{','.join(active)}[{label_out}]"


def build_filtergraph(spec: SceneSpec) -> str:
    """The ``-filter_complex`` graph for ``spec`` (output label ``[out]``)."""
    if spec.scene not in SCENES:
        raise ValueError(f"unknown scene {spec.scene!r}")
    if not spec.images and not spec.visual_video and spec.scene not in NO_VISUAL_SCENES:
        raise ValueError("a scene needs at least one image or a page recording")
    loop_index = len(spec.images) + (1 if spec.visual_video else 0)
    needs_loop = spec.scene in LOOP_SCENES
    if needs_loop and not spec.loop_path:
        raise ValueError(f"scene {spec.scene!r} needs a loop clip")

    if spec.scene == "full":
        return _visuals(spec, WIDTH, HEIGHT, "vis") + ";[vis]null[out]"

    if spec.scene == "stack":
        return ";".join([
            _visuals(spec, WIDTH, HALF, "top"),
            _loop(loop_index, WIDTH, HALF, "bottom"),
            f"[top][bottom]vstack=inputs=2,drawbox=x=0:y={HALF - 3}:w={WIDTH}:h=6:color={GOLD}:t=fill[out]",
        ])

    if spec.scene == "meme":
        rest = (HEIGHT - MEME_BAND) // 2
        band_text = _text(spec, "band", size=62, color="black", x="64", y="(h-text_h)/2+60")
        return ";".join([
            f"color=c=white:s={WIDTH}x{MEME_BAND}:r={FPS}:d={spec.duration_s:.3f},format=yuv420p[band0]",
            _chain("band0", [band_text], "band"),
            _visuals(spec, WIDTH, rest, "mid"),
            _loop(loop_index, WIDTH, HEIGHT - MEME_BAND - rest, "low"),
            "[band][mid][low]vstack=inputs=3[out]",
        ])

    if spec.scene == "pov":
        card_w, card_h = 960, 900
        pov_text = _text(spec, "pov", size=66, color="white", x="(w-text_w)/2", y="230", box="black@0.55")
        return ";".join([
            _loop(loop_index, WIDTH, HEIGHT, "base", dim=0.22),
            _visuals(spec, card_w, card_h, "card"),
            "[base][card]overlay=(W-w)/2:520:shortest=1[mix]",
            _chain("mix", [pov_text], "out"),
        ])

    if spec.scene in ("story", "character"):
        return _story_graph(spec, loop_index)

    # before_after
    label_before = _text(spec, "before_label", size=54, color="white", x="60", y="150", box="black@0.6")
    label_after = _text(spec, "after_label", size=54, color="black", x="60", y="150", box=f"{GOLD}@0.95")
    before_text = _text(spec, "before", size=58, color="white", x="60", y="290")
    after_text = _text(spec, "after", size=58, color="white", x="60", y="h-text_h-110", box="black@0.78")
    return ";".join([
        f"color=c=0x2B2B30:s={WIDTH}x{HALF}:r={FPS}:d={spec.duration_s:.3f},"
        "noise=alls=14:allf=u,format=yuv420p[grey]",  # static grain compresses well
        _chain("grey", [label_before, before_text], "before"),
        _visuals(spec, WIDTH, HALF, "vivid"),
        _chain("vivid", [label_after, after_text], "after"),
        f"[before][after]vstack=inputs=2,drawbox=x=0:y={HALF - 3}:w={WIDTH}:h=6:color={GOLD}:t=fill[out]",
    ])


def _story_graph(spec: SceneSpec, loop_index: int) -> str:
    """Gameplay full screen, a forum-style story card for the first seconds,
    and (character scene) an original cartoon narrator in a bobbing bubble."""
    shown = f"enable='lt(t,{STORY_CARD_S:.1f})'"
    card = [
        f"drawbox=x=60:y=250:w={WIDTH - 120}:h=520:color=white@0.97:t=fill:{shown}",
        f"drawbox=x=100:y=290:w=64:h=64:color={GOLD}:t=fill:{shown}",
    ]
    head = _text(spec, "card_head", size=40, color="0x555555", x="190", y="302")
    body = _text(spec, "card", size=54, color="black", x="100", y="390")
    card += [f"{head}:{shown}" if head else "", f"{body}:{shown}" if body else ""]
    parts = [_loop(loop_index, WIDTH, HEIGHT, "base")]
    if spec.scene == "character" and spec.images:
        size = CHARACTER_SIZE
        parts.append(
            f"[0:v]fps={FPS},scale={size}:{size}:force_original_aspect_ratio=increase,"
            f"crop={size}:{size},setsar=1,format=yuv420p[narrator]"
        )
        parts.append(
            f"[base]drawbox=x=48:y={HEIGHT - size - 212}:w={size + 24}:h={size + 24}:"
            f"color={GOLD}:t=fill[framed]"
        )
        parts.append(
            f"[framed][narrator]overlay=60:{HEIGHT - size - 200}+12*sin(2*PI*t):shortest=1[mix]"
        )
        parts.append(_chain("mix", card, "out"))
    else:
        parts.append(_chain("base", card, "out"))
    return ";".join(parts)


def input_args(spec: SceneSpec) -> list[str]:
    """The ``-i`` arguments for ``spec``'s inputs, in the graph's index order.

    Shared by the stand-alone scene render and the single-pass compose, which
    appends the narration, music and watermark inputs after these.
    """
    duration = f"{spec.duration_s:.3f}"
    seg = f"{max(0.5, spec.duration_s / max(1, len(spec.images))) + 0.5:.3f}"
    argv: list[str] = []
    if spec.visual_video:
        # Skip the recording's first second (page load), loop it to length.
        argv += ["-ss", "1.2", "-stream_loop", "-1", "-t", duration, "-i", spec.visual_video]
    for image in spec.images:
        argv += ["-loop", "1", "-framerate", str(FPS), "-t", seg, "-i", image]
    if spec.scene in LOOP_SCENES:
        argv += ["-stream_loop", "-1", "-t", duration, "-i", spec.loop_path]
    return argv


def input_count(spec: SceneSpec) -> int:
    """How many FFmpeg inputs :func:`input_args` declares."""
    return input_args(spec).count("-i")


def build_command(spec: SceneSpec, out_path: str, *, ffmpeg: str = "ffmpeg") -> list[str]:
    """The full FFmpeg argv that renders ``spec`` to ``out_path`` (no audio)."""
    duration = f"{spec.duration_s:.3f}"
    argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *input_args(spec)]
    argv += [
        "-filter_complex", build_filtergraph(spec),
        "-map", "[out]",
        "-t", duration,
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart",
        out_path,
    ]
    return argv


def title_card(title: str, dest: str, font_path: str, *, ffmpeg: str = "ffmpeg") -> str:
    """A 1080x1080 branded card with the product title (no network)."""
    work = os.path.dirname(dest) or "."
    os.makedirs(work, exist_ok=True)
    text_path = os.path.join(work, "card-title.txt")
    with open(text_path, "w", encoding="utf-8") as handle:
        handle.write(wrap(title or "Menivor", 18, 4))
    graph = (
        f"drawtext=fontfile='{_escape(font_path)}':textfile='{_escape(text_path)}':"
        f"fontsize=92:fontcolor={GOLD}:line_spacing=18:x=(w-text_w)/2:y=(h-text_h)/2"
    )
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=0x14110D:s=1080x1080", "-vf", graph, "-frames:v", "1", dest],
        check=True, timeout=60,
    )
    return dest


def prepare_scene(
    *,
    scene: str,
    images: list[str],
    loop_path: str,
    hook: str,
    title: str,
    duration_s: float,
    font_path: str,
    work_dir: str,
    ffmpeg: str = "ffmpeg",
    visual_video: str = "",
) -> SceneSpec:
    """Write the scene's text files and still plates; the ready :class:`SceneSpec`.

    Plates are single PNG frames (no video encode). The spec renders on its own
    (:func:`render_scene`) or inside the single-pass compose.
    """
    os.makedirs(work_dir, exist_ok=True)
    texts: dict[str, str] = {}
    for name, value in texts_for(scene, hook, title).items():
        path = os.path.join(work_dir, f"scene-{name}.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(value)
        texts[name] = path
    visuals = list(images)
    if scene in NO_VISUAL_SCENES:
        plates: list[str] = []
        visual_video = ""
    elif visual_video and scene != "character":
        plates = []
    elif scene == "character":
        plates = visuals[:1]  # the narrator portrait is used as-is
        if not plates:
            scene = "story"
    else:
        if not visuals:
            visuals = [title_card(title, os.path.join(work_dir, "card.png"), font_path, ffmpeg=ffmpeg)]
        width, height = panel_size(scene)
        plates = []
        for index, image in enumerate(visuals):
            plate = os.path.join(work_dir, f"plate-{index}.png")
            subprocess.run(plate_command(image, width, height, plate, ffmpeg=ffmpeg), check=True, timeout=120)
            plates.append(plate)
    return SceneSpec(
        scene=scene,
        images=tuple(plates),
        duration_s=max(3.0, float(duration_s)),
        font_path=font_path,
        loop_path=loop_path,
        texts=texts,
        visual_video=visual_video if scene not in ("character", "story") else "",
    )


def render_scene(
    *,
    scene: str,
    images: list[str],
    loop_path: str,
    hook: str,
    title: str,
    duration_s: float,
    font_path: str,
    work_dir: str,
    out_path: str,
    ffmpeg: str = "ffmpeg",
    timeout_s: int = 600,
    visual_video: str = "",
) -> str:
    """Write the scene's text files, run FFmpeg and return ``out_path``.

    The two-pass path (``COMPOSE_SINGLE_PASS=off``): the scene is its own full
    encode and the compose encodes again on top of it.
    """
    spec = prepare_scene(
        scene=scene, images=images, loop_path=loop_path, hook=hook, title=title,
        duration_s=duration_s, font_path=font_path, work_dir=work_dir, ffmpeg=ffmpeg,
        visual_video=visual_video,
    )
    subprocess.run(build_command(spec, out_path, ffmpeg=ffmpeg), check=True, timeout=timeout_s)
    from app.services.compose import encode_count

    encode_count.count("scene")
    return out_path


__all__ = [
    "HEIGHT",
    "LOOP_SCENES",
    "SCENES",
    "WIDTH",
    "SceneSpec",
    "build_command",
    "build_filtergraph",
    "input_args",
    "input_count",
    "panel_size",
    "plate_command",
    "prepare_scene",
    "render_scene",
    "split_before_after",
    "texts_for",
    "title_card",
    "wrap",
]
