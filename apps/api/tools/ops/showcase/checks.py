"""Showcase QA: the rules every landing reel must pass before it is published.

Plan checks (no media needed, run in tests):
* one niche per reel, and no two reels share a niche, a footage clip, a
  background loop or a narrator voice (``Multilingual`` variants count as the
  same voice);
* at most two own-product reels, in different styles;
* each script is long enough for a 20-40 s reel at a normal speaking pace;
* fact check: example-business scripts carry no digit figures, and every
  number (digits or number words) in an own-product script appears in the text
  of the page that reel records.

Media checks (ffprobe/ffmpeg on the rendered masters):
* duration 20-40 s and at least one audio stream;
* motion: the mean frame-to-frame difference of a small grayscale sample
  must clear a floor, so a near-static still fails.

Full reel checks (Wave P PM1.1, on ``full/<key>-full.mp4`` with sound):
* 720x1280, one audio stream, duration 20-40 s;
* integrated loudness inside the -16 to -14 LUFS target (EBU R128 ``ebur128``);
* no silent tail (at most ``MAX_SILENT_TAIL_S`` of silence at the end);
* caption burn-in follows the M2.4 rule: every caption line of the render's
  ASS file holds 2-4 words (a one-word script is the only one-word line);
* no vendor or model names in the reel's script, label or niche (denylist
  ``vendor`` rules plus the model-name list below).

    python apps/api/tools/ops/showcase/checks.py            # plan only
    python apps/api/tools/ops/showcase/checks.py --media    # plus masters
    python apps/api/tools/ops/showcase/checks.py --pages    # plus live page fact check
    python apps/api/tools/ops/showcase/checks.py --full     # plus full reels with sound

Exit status is non-zero when any check fails. ``--json PATH`` writes the
per-reel media verdicts that ``publish.py`` reads.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
STAGING = os.environ.get("SHOWCASE_OUT", os.path.join(REPO, "public-samples-staging"))

MIN_SECONDS = 20.0
MAX_SECONDS = 40.0
#: Edge-tts neural voices speak about 2.4-2.9 words a second at rate 0.
WORDS_PER_SECOND = 2.6
MIN_WORDS = 52
MAX_WORDS = int(MAX_SECONDS * 2.4)
MAX_OWN_PRODUCT_REELS = 2
#: Mean absolute luma difference (0-255) between sampled frames. Real footage
#: montages score well above 4; a still with only captions changing is near 1.
MOTION_FLOOR = 2.5
MOTION_SAMPLE_FPS = 2
MOTION_SIZE = (54, 96)

_NUMBER_WORDS = (
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "twenty", "thirty", "forty", "fifty", "hundred", "thousand",
    "million", "billion", "half", "double", "triple",
)
_NUMBER_WORD_RE = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE)
_DIGIT_RE = re.compile(r"\d[\d,.]*%?")


@dataclass(frozen=True)
class Violation:
    rule: str
    keys: tuple[str, ...]
    detail: str

    def __str__(self) -> str:
        return f"{self.rule}: {', '.join(self.keys)}: {self.detail}"


def voice_persona(voice: str) -> str:
    """``en-US-EmmaMultilingualNeural`` and ``en-US-EmmaNeural`` are one persona."""
    name = voice.split(":", 1)[-1]
    return re.sub(r"(Multilingual)?Neural$", "", name).lower()


def loop_identity(reel: Mapping) -> str:
    """The background loop a reel shows ("" when the reel has no companion loop)."""
    spec = str(reel.get("loop") or "")
    if spec == "@footage":
        return "footage:" + "+".join(reel.get("footage") or [])
    return spec


def _duplicates(reels: Sequence[Mapping], value) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = defaultdict(list)
    for reel in reels:
        for item in value(reel):
            if item:
                seen[item].append(str(reel["key"]))
    return {item: keys for item, keys in seen.items() if len(keys) > 1}


def repeat_violations(reels: Sequence[Mapping]) -> list[Violation]:
    """Shared niches, footage clips, loops or voices across reels."""
    out: list[Violation] = []
    rules = (
        ("key", lambda r: [str(r["key"])]),
        ("niche", lambda r: [str(r.get("niche") or "").strip().lower()]),
        ("footage", lambda r: [str(f) for f in r.get("footage") or []]),
        ("loop", lambda r: [loop_identity(r)]),
        ("voice", lambda r: [voice_persona(str(r.get("voice") or ""))]),
    )
    for rule, value in rules:
        for item, keys in sorted(_duplicates(reels, value).items()):
            out.append(Violation(f"repeat-{rule}", tuple(keys), item))
    for reel in reels:
        if not str(reel.get("niche") or "").strip():
            out.append(Violation("niche-missing", (str(reel["key"]),), "every reel names one niche"))
    return out


def self_ad_violations(reels: Sequence[Mapping]) -> list[Violation]:
    """At most two own-product reels, never in the same style."""
    own = [r for r in reels if r.get("page")]
    out: list[Violation] = []
    if len(own) > MAX_OWN_PRODUCT_REELS:
        out.append(Violation("self-ads", tuple(str(r["key"]) for r in own),
                             f"at most {MAX_OWN_PRODUCT_REELS} own-product reels"))
    for style, keys in _duplicates(own, lambda r: [str(r.get("style") or "voiceover")]).items():
        out.append(Violation("self-ads-style", tuple(keys), f"two own-product reels in {style}"))
    return out


def estimated_seconds(script: str) -> float:
    return len(script.split()) / WORDS_PER_SECOND


def length_violations(reels: Sequence[Mapping]) -> list[Violation]:
    out: list[Violation] = []
    for reel in reels:
        words = len(str(reel.get("script") or "").split())
        if not MIN_WORDS <= words <= MAX_WORDS:
            out.append(Violation("script-length", (str(reel["key"]),),
                                 f"{words} words, need {MIN_WORDS}-{MAX_WORDS} for a 20-40 s reel"))
    return out


def numbers_in(text: str) -> list[str]:
    """Digit figures and number words in ``text``, lower-cased, in order."""
    found = [m.group(0).rstrip(".,") for m in _DIGIT_RE.finditer(text)]
    found += [m.group(0).lower() for m in _NUMBER_WORD_RE.finditer(text)]
    return found


def fact_check(script: str, page_text: str | None) -> list[str]:
    """Numbers in ``script`` that the source page does not back.

    Without a source page (an example business on stock footage) any digit
    figure is unbacked; number words there are plain speech ("three drops").
    With a page, every number, digits or words, must appear in its text.
    """
    if page_text is None:
        return [m.group(0).rstrip(".,") for m in _DIGIT_RE.finditer(script)]
    haystack = " ".join(page_text.lower().split())
    return [n for n in numbers_in(script) if n.lower() not in haystack]


def fact_violations(reels: Sequence[Mapping], pages: Mapping[str, str] | None = None) -> list[Violation]:
    """Fact check every script; own-product reels need ``pages[url]`` text."""
    out: list[Violation] = []
    for reel in reels:
        url = reel.get("page")
        if url and pages is None:
            continue  # page text not fetched: checked with --pages
        page_text = (pages or {}).get(url, "") if url else None
        missing = fact_check(str(reel.get("script") or ""), page_text)
        if missing:
            out.append(Violation("fact-check", (str(reel["key"]),),
                                 f"not in the source page: {', '.join(sorted(set(missing)))}"))
    return out


def plan_violations(reels: Sequence[Mapping], pages: Mapping[str, str] | None = None) -> list[Violation]:
    return [*repeat_violations(reels), *self_ad_violations(reels),
            *length_violations(reels), *fact_violations(reels, pages)]


# --------------------------------------------------------------------------- #
# Media checks
# --------------------------------------------------------------------------- #
def probe(path: str) -> dict:
    """``{"duration_s": float, "audio_streams": int, "video_streams": int}`` via ffprobe."""
    raw = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", path],
        capture_output=True, text=True, check=True, timeout=120,
    ).stdout
    data = json.loads(raw or "{}")
    kinds = [s.get("codec_type") for s in data.get("streams", [])]
    return {
        "duration_s": float((data.get("format") or {}).get("duration") or 0.0),
        "audio_streams": kinds.count("audio"),
        "video_streams": kinds.count("video"),
    }


def motion_score(path: str, *, fps: int = MOTION_SAMPLE_FPS, size: tuple[int, int] = MOTION_SIZE) -> float:
    """Mean absolute luma difference between consecutive sampled frames."""
    width, height = size
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={fps},scale={width}:{height},format=gray",
         "-f", "rawvideo", "-"],
        capture_output=True, check=True, timeout=300,
    ).stdout
    frame = width * height
    frames = [raw[i:i + frame] for i in range(0, len(raw) - frame + 1, frame)]
    if len(frames) < 2:
        return 0.0
    total = 0
    for prev, cur in zip(frames, frames[1:]):
        total += sum(abs(a - b) for a, b in zip(prev, cur))
    return total / (frame * (len(frames) - 1))


def media_verdict(path: str) -> dict:
    """Probe + motion verdict for one rendered master."""
    if not os.path.isfile(path):
        return {"path": path, "ok": False, "errors": ["missing"]}
    info = probe(path)
    errors: list[str] = []
    if not MIN_SECONDS <= info["duration_s"] <= MAX_SECONDS:
        errors.append(f"duration {info['duration_s']:.1f}s outside {MIN_SECONDS:.0f}-{MAX_SECONDS:.0f}s")
    if info["audio_streams"] < 1:
        errors.append("no audio stream")
    if info["video_streams"] < 1:
        errors.append("no video stream")
    motion = motion_score(path) if info["video_streams"] else 0.0
    if motion < MOTION_FLOOR:
        errors.append(f"near-static (motion {motion:.2f} < {MOTION_FLOOR})")
    return {"path": path, "ok": not errors, "errors": errors, "motion": round(motion, 2), **info}


# --------------------------------------------------------------------------- #
# Full reel checks (Wave P PM1.1)
# --------------------------------------------------------------------------- #
FULL_SIZE = (720, 1280)
#: Loudness target for the full reels (a target, not a public claim).
LUFS_TARGET = -15.0
LUFS_MIN = -16.0
LUFS_MAX = -14.0
#: Silence at the end longer than this fails ("no silent tail").
MAX_SILENT_TAIL_S = 1.5
SILENCE_NOISE_DB = -45
SILENCE_MIN_S = 0.4
DENYLIST_PATH = os.path.join(REPO, "policy", "copy-denylist.json")
#: Model names the vendor rules do not list (showcase copy never names a model).
_MODEL_NAMES = re.compile(
    r"\b(?:kling|veo ?\d|sora|runway|seedance|hailuo|minimax|luma|pika|pixverse|midjourney|"
    r"stable diffusion|sdxl|flux(?:\.1| pro| dev| schnell)|wan ?2(?:\.\d)?|hunyuan|mochi|ltx-?video|"
    r"cogvideox?|claude|llama|whisper|replicate|fal\.ai)\b",
    re.IGNORECASE,
)
_LUFS_RE = re.compile(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+|-inf)\s*LUFS")
_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")
_ASS_TAG = re.compile(r"\{[^}]*\}")


def parse_integrated_lufs(ebur128_log: str) -> float | None:
    """The integrated loudness from an ``ebur128`` summary, or ``None``."""
    matches = _LUFS_RE.findall(ebur128_log or "")
    if not matches:
        return None
    value = matches[-1]
    return float("-inf") if value == "-inf" else float(value)


def integrated_lufs(path: str) -> float | None:
    log = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn", "-af", "ebur128=framelog=quiet",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=300,
    ).stderr
    return parse_integrated_lufs(log)


def silence_log(path: str) -> str:
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn", "-af",
         f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_S}", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300,
    ).stderr


def silent_tail_seconds(log: str, duration_s: float) -> float:
    """Seconds of silence that run into the end of the file (0 when none)."""
    events: list[tuple[float, str]] = [(float(m), "start") for m in _SIL_START.findall(log or "")]
    events += [(float(m), "end") for m in _SIL_END.findall(log or "")]
    events.sort()
    if not events:
        return 0.0
    last_start = max((t for t, kind in events if kind == "start"), default=None)
    if last_start is None:
        return 0.0
    ends_after = [t for t, kind in events if kind == "end" and t >= last_start]
    if not ends_after:
        return max(0.0, duration_s - last_start)
    if ends_after[0] >= duration_s - 0.05:
        return max(0.0, ends_after[0] - last_start)
    return 0.0


def caption_phrase_violations(ass_text: str) -> list[str]:
    """M2.4: each caption line holds 2-4 words (one word only for a one-word script)."""
    lines = []
    for raw in (ass_text or "").splitlines():
        if not raw.startswith("Dialogue:"):
            continue
        text = raw.split(",", 9)[-1] if raw.count(",") >= 9 else ""
        words = _ASS_TAG.sub("", text).replace("\\N", " ").split()
        lines.append(len(words))
    if not lines:
        return ["no caption lines"]
    if len(lines) == 1 and lines[0] == 1:
        return []
    out = []
    for index, count in enumerate(lines, start=1):
        if not 2 <= count <= 4:
            out.append(f"line {index} has {count} word{'s' if count != 1 else ''}")
    return out


def _vendor_rules() -> list[dict]:
    try:
        with open(DENYLIST_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    return [r for r in data.get("rules", []) if r.get("category") == "vendor"
            and "menivor" in r.get("products", []) and (r.get("match") or {}).get("type") == "regex"]


def vendor_hits(text: str) -> list[str]:
    """Vendor or model names in ``text`` (denylist vendor rules plus model names)."""
    unit = " ".join(str(text or "").split())
    hits: list[str] = []
    for rule in _vendor_rules():
        scrubbed = unit
        for token in rule.get("exceptTokens", []):
            scrubbed = re.sub(re.escape(token), " ", scrubbed, flags=re.I)
        match = re.search(rule["match"]["value"], scrubbed, re.I)
        if match:
            hits.append(match.group(0))
    hits += [m.group(0) for m in _MODEL_NAMES.finditer(unit)]
    return hits


def probe_full(path: str) -> dict:
    """``probe`` plus the first video stream's width and height."""
    raw = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
         "-of", "json", path],
        capture_output=True, text=True, check=True, timeout=120,
    ).stdout
    data = json.loads(raw or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    kinds = [s.get("codec_type") for s in streams]
    return {
        "duration_s": float((data.get("format") or {}).get("duration") or 0.0),
        "audio_streams": kinds.count("audio"),
        "video_streams": kinds.count("video"),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
    }


def full_verdict(path: str, ass_path: str, reel: Mapping) -> dict:
    """Every full-reel rule for one ``<key>-full.mp4`` and its caption file."""
    if not os.path.isfile(path):
        return {"path": path, "ok": False, "errors": ["missing"]}
    info = probe_full(path)
    errors: list[str] = []
    if (info["width"], info["height"]) != FULL_SIZE:
        errors.append(f"{info['width']}x{info['height']}, need {FULL_SIZE[0]}x{FULL_SIZE[1]}")
    if info["audio_streams"] < 1:
        errors.append("no audio stream")
    if not MIN_SECONDS <= info["duration_s"] <= MAX_SECONDS:
        errors.append(f"duration {info['duration_s']:.1f}s outside {MIN_SECONDS:.0f}-{MAX_SECONDS:.0f}s")
    lufs = integrated_lufs(path) if info["audio_streams"] else None
    if lufs is None or not LUFS_MIN <= lufs <= LUFS_MAX:
        errors.append(f"loudness {lufs} LUFS outside {LUFS_MIN:.0f} to {LUFS_MAX:.0f} (target)")
    tail = silent_tail_seconds(silence_log(path), info["duration_s"]) if info["audio_streams"] else 0.0
    if tail > MAX_SILENT_TAIL_S:
        errors.append(f"silent tail {tail:.1f}s")
    try:
        with open(ass_path, encoding="utf-8") as handle:
            ass_text = handle.read()
    except OSError:
        ass_text = ""
    errors += [f"captions: {v}" for v in caption_phrase_violations(ass_text)]
    names = vendor_hits(" ".join(str(reel.get(k) or "") for k in ("script", "label", "niche")))
    if names:
        errors.append(f"vendor or model names: {', '.join(sorted(set(names)))}")
    return {"path": path, "ok": not errors, "errors": errors,
            "lufs": None if lufs is None else round(lufs, 1), "silent_tail_s": round(tail, 2), **info}


def fetch_page_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "menivor-showcase-qa"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed own-product URLs
        html = resp.read().decode("utf-8", "replace")
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def main(argv: Iterable[str] | None = None) -> int:
    sys.path.insert(0, HERE)
    import plan

    parser = argparse.ArgumentParser(description="Showcase QA")
    parser.add_argument("--media", action="store_true", help="probe the rendered masters too")
    parser.add_argument("--pages", action="store_true", help="fetch own-product pages for the fact check")
    parser.add_argument("--masters", default=os.path.join(STAGING, "masters"))
    parser.add_argument("--full", action="store_true", help="check the full reels with sound (PM1.1)")
    parser.add_argument("--full-dir", default=os.path.join(STAGING, "full"))
    parser.add_argument("--json", dest="json_out", default="")
    parser.add_argument("keys", nargs="*")
    args = parser.parse_args(list(argv) if argv is not None else None)

    pages = None
    if args.pages:
        pages = {r["page"]: fetch_page_text(r["page"]) for r in plan.REELS if r.get("page")}
    failures = [str(v) for v in plan_violations(plan.REELS, pages)]
    verdicts: dict[str, dict] = {}
    if args.media:
        keys = args.keys or [r["key"] for r in plan.REELS]
        for key in keys:
            verdict = media_verdict(os.path.join(args.masters, f"{key}.mp4"))
            verdicts[key] = verdict
            if not verdict["ok"]:
                failures.append(f"media {key}: {'; '.join(verdict['errors'])}")
    full: dict[str, dict] = {}
    if args.full:
        reels = {r["key"]: r for r in plan.REELS}
        for key in args.keys or list(reels):
            verdict = full_verdict(os.path.join(args.full_dir, f"{key}-full.mp4"),
                                   os.path.join(args.full_dir, f"{key}-captions.ass"), reels[key])
            full[key] = verdict
            if not verdict["ok"]:
                failures.append(f"full {key}: {'; '.join(verdict['errors'])}")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump({"plan_ok": not any(not f.startswith(("media ", "full ")) for f in failures),
                       "media": verdicts, "full": full}, handle, indent=1)
    for line in failures:
        print("FAIL", line)
    print(f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
