"""Cut a rendered Ad Clone: lip-synced talk clips + voiced still push-ins + end card, in 9:16 or 16:9.

Follows the plan's edit list exactly (the make_episode.py contract): a talk segment runs from
``pre`` before its line to ``post`` after it inside the shot's clip (line onsets come from the
shot's lead/gap and the measured line lengths); a still segment is a slow push-in with the line
voiced 0.3 s in; the brand end card closes. Every segment is normalised to the canvas
(1080x1920 for 9:16, 1920x1080 for 16:9, 30 fps, AAC 44.1 kHz stereo) and then concatenated.
Talk segments always play OUR shot audio (the engine's own audio track is never used), and each
spoken line is burned in as a game-style subtitle while it is heard (:mod:`captions`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any

CANVAS = {"9:16": (1080, 1920), "16:9": (1920, 1080)}
FPS = 30
STILL_VO_LEAD, STILL_VO_TAIL = 0.3, 0.4
END_CARD_S = 1.8
CARD_BG, CARD_FG = (21, 18, 15), (239, 232, 220)


class AssembleError(RuntimeError):
    pass


def canvas(aspect: str) -> tuple[int, int]:
    if aspect not in CANVAS:
        raise AssembleError(f"aspect is one of {', '.join(CANVAS)}")
    return CANVAS[aspect]


def onsets(shot: Mapping[str, Any], line_len: Mapping[str, float]) -> dict[str, float]:
    """Where each line starts inside its shot's audio (lead, then line + gap ...)."""
    t, out = float(shot.get("lead", 0.25)), {}
    for lid in shot.get("lines") or []:
        out[lid] = round(t, 3)
        t += float(line_len[lid]) + float((shot.get("gaps") or {}).get(lid, shot.get("gap", 0.3)))
    return out


def timeline(plan: Mapping[str, Any], line_len: Mapping[str, float]) -> list[dict[str, Any]]:
    """Plan edit list -> concrete segments (pure)."""
    shots = {s["id"]: s for s in plan.get("shots") or []}
    starts = {sid: onsets(s, line_len) for sid, s in shots.items()}
    segs: list[dict[str, Any]] = []
    for g in plan.get("edit") or []:
        lines = list(g.get("lines") or [])
        if "shot" in g:
            sh = shots[g["shot"]]
            first, last = lines[0], lines[-1]
            a = max(0.0, starts[sh["id"]][first] - float(g.get("pre", 0.25)))
            b = starts[sh["id"]][last] + float(line_len[last]) + float(g.get("post", 0.35)) + float(g.get("hold", 0.0)) / 2
            segs.append({"type": "clip", "shot": sh["id"], "start": round(a, 3), "len": round(b - a, 3), "lines": lines,
                         "cap_y": g.get("cap_y")})
        else:
            need = (STILL_VO_LEAD + sum(float(line_len[lid]) for lid in lines) + 0.3 * max(len(lines) - 1, 0)
                    + STILL_VO_TAIL) if lines else 0.0
            segs.append({"type": "still", "still": g["still"], "len": round(max(float(g.get("len", 1.0)), need), 3),
                         "push": float(g.get("push", 1.06)), "lines": lines, "cap_y": g.get("cap_y")})
    segs.append({"type": "card", "len": END_CARD_S, "lines": []})
    return segs


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise AssembleError("ffmpeg is not installed")
    return path


def _enc(out: str) -> list[str]:
    return ["-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "160k", "-movflags", "+faststart", out]


Caption = tuple[str, float, float]  # (png path, start s, end s) inside the segment


def _overlays(first_input: int, captions: list[Caption], base: str = "v0") -> tuple[str, str]:
    """Overlay chain for caption PNG inputs starting at ``first_input``; returns (filters, last label)."""
    chain, label = "", base
    for k, (_png, t0, t1) in enumerate(captions):
        nxt = f"v{k + 1}"
        chain += f";[{label}][{first_input + k}:v]overlay=0:0:enable='between(t,{t0:.3f},{t1:.3f})'[{nxt}]"
        label = nxt
    return chain, label


def _caption_inputs(captions: list[Caption]) -> list[str]:
    return [arg for png, _a, _b in captions for arg in ("-i", png)]


def clip_command(src: str, out: str, *, start: float, length: float, size: tuple[int, int], has_audio: bool,
                 audio_src: str | None = None, captions: list[Caption] | None = None) -> list[str]:
    """A talk segment: the engine clip cut at [start, start+length] on the canvas, with ``audio_src`` (our
    shot audio, cut at the same times) or the clip's own audio, and the captions on top."""
    w, h = size
    caps = list(captions or [])
    args = [_ffmpeg(), "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", src]
    if audio_src:
        args += ["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", audio_src]
        audio_in = "1:a"
    elif has_audio:
        audio_in = "0:a"
    else:
        args += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
        audio_in = "1:a"
    first_cap = 2 if (audio_src or not has_audio) else 1
    args += _caption_inputs(caps)
    chain, last = _overlays(first_cap, caps)
    graph = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1[v0]{chain};"
             f"[{audio_in}]aresample=44100,aformat=channel_layouts=stereo,apad,atrim=0:{length:.3f}[a]")
    return args + ["-filter_complex", graph, "-map", f"[{last}]", "-map", "[a]", "-t", f"{length:.3f}"] + _enc(out)


def still_command(image: str, out: str, *, length: float, push: float, size: tuple[int, int],
                  audio: str | None, captions: list[Caption] | None = None) -> list[str]:
    """A slow push-in on a still; ``audio`` (one voiced line) starts STILL_VO_LEAD in; captions on top."""
    w, h = size
    caps = list(captions or [])
    frames = max(int(round(length * FPS)), 1)
    video = (f"[0:v]scale={2 * w}:{2 * h}:force_original_aspect_ratio=increase,crop={2 * w}:{2 * h},"
             f"zoompan=z='1+({push:.3f}-1)*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:"
             f"fps={FPS},setsar=1[v0]")
    args = [_ffmpeg(), "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-t", f"{length:.3f}", "-i", image]
    if audio:
        ms = int(round(STILL_VO_LEAD * 1000))
        args += ["-i", audio]
        sound = (f"[1:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms},apad,"
                 f"atrim=0:{length:.3f}[a]")
    else:
        args += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
        sound = f"[1:a]atrim=0:{length:.3f}[a]"
    args += _caption_inputs(caps)
    chain, last = _overlays(2, caps)
    return args + ["-filter_complex", f"{video}{chain};{sound}", "-map", f"[{last}]", "-map", "[a]",
                   "-t", f"{length:.3f}"] + _enc(out)


def end_card(text: str, out_png: str, size: tuple[int, int]) -> str:
    """Brand end card (PIL; no ffmpeg text filters needed)."""
    from PIL import Image, ImageDraw, ImageFont

    w, h = size
    img = Image.new("RGB", (w, h), CARD_BG)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=max(int(min(w, h) * 0.055), 18))
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((w - (box[2] - box[0])) / 2, (h - (box[3] - box[1])) / 2), text, fill=CARD_FG, font=font)
    img.save(out_png)
    return out_png


def _run(args: list[str]) -> None:
    out = subprocess.run(args, capture_output=True, text=True, timeout=600, check=False)  # noqa: S603
    if out.returncode != 0:
        raise AssembleError(f"ffmpeg failed: {out.stderr.strip()[:300]}")


def _has_audio(path: str) -> bool:
    from .media import probe

    return probe(path).has_audio


def _segment_captions(seg: Mapping[str, Any], plan: Mapping[str, Any], line_len: Mapping[str, float],
                      shot_onsets: Mapping[str, Mapping[str, float]], size: tuple[int, int], workdir: str,
                      index: int) -> list[Caption]:
    from . import captions as C

    style = plan.get("captions") or {}
    if not style.get("enabled", True) or seg["type"] == "card":
        return []
    texts = {ln["id"]: str(ln.get("caption") or ln.get("text") or "") for ln in plan.get("lines") or []}
    plan_h = float((plan.get("canvas") or {}).get("h") or size[1])
    center = float(seg["cap_y"]) / plan_h * size[1] if seg.get("cap_y") is not None else None
    out = []
    for lid, t0, t1 in C.windows(seg, line_len, shot_onsets, STILL_VO_LEAD):
        png = C.render_png(texts.get(lid, ""), os.path.join(workdir, f"cap{index:02d}-{lid}.png"), size,
                           {**C.style_from_brief(None, str(plan.get("aspect") or "9:16")), **style}, center)
        out.append((png, t0, t1))
    return out


def render(plan: Mapping[str, Any], *, line_len: Mapping[str, float], clips: Mapping[str, str],
           stills: Mapping[str, str], line_audio: Mapping[str, str], card_text: str, workdir: str, out: str,
           shot_audio: Mapping[str, str] | None = None) -> dict:
    """Run the cut. ``clips``: shot id -> engine mp4; ``shot_audio``: shot id -> our audio for that shot
    (used instead of the clip's own track); ``stills``: still id -> image file."""
    size = canvas(str(plan.get("aspect") or "9:16"))
    os.makedirs(workdir, exist_ok=True)
    shots = {s["id"]: s for s in plan.get("shots") or []}
    shot_onsets = {sid: onsets(s, line_len) for sid, s in shots.items()}
    parts, captioned = [], 0
    for i, seg in enumerate(timeline(plan, line_len)):
        part = os.path.join(workdir, f"seg{i:02d}.mp4")
        caps = _segment_captions(seg, plan, line_len, shot_onsets, size, workdir, i)
        captioned += len(caps)
        if seg["type"] == "clip":
            src = clips.get(seg["shot"])
            if not src:
                raise AssembleError(f"missing rendered clip for {seg['shot']}")
            own = (shot_audio or {}).get(seg["shot"])
            _run(clip_command(src, part, start=seg["start"], length=seg["len"], size=size,
                              has_audio=bool(own) or _has_audio(src), audio_src=own, captions=caps))
        elif seg["type"] == "still":
            img = stills.get(seg["still"])
            if not img:
                raise AssembleError(f"missing image for still {seg['still']}")
            if len(seg["lines"]) > 1:
                raise AssembleError(f"still {seg['still']} voices more than one line")
            _run(still_command(img, part, length=seg["len"], push=seg["push"], size=size,
                               audio=line_audio[seg["lines"][0]] if seg["lines"] else None, captions=caps))
        else:
            png = end_card(card_text, os.path.join(workdir, "card.png"), size)
            _run(still_command(png, part, length=seg["len"], push=1.0, size=size, audio=None))
        parts.append(part)
    listing = os.path.join(workdir, "parts.txt")
    with open(listing, "w", encoding="utf-8") as fh:
        fh.writelines(f"file '{p}'\n" for p in parts)
    _run([_ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy",
          "-movflags", "+faststart", out])
    return {"path": out, "size": size, "segments": len(parts), "captions": captioned}
