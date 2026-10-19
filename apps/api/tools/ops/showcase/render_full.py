"""Render the landing's full showcase reels with sound (Wave P PM1.1).

The job computes the missing set from ``sources.json`` against the checked-in
``full-manifest.json`` (27 keys): a key is missing when its staged
``full/<key>-full.mp4`` is absent or fails ``checks.py --full``. Each missing
reel is rendered with Menivor's own pipeline (``runner.render``: typed script,
free voice, captions, compose; no paid model), then encoded to a 720x1280
full reel whose loudness is normalised to the -15 LUFS target (two-pass
``loudnorm``), with the silent tail trimmed. The web loop and poster are cut
from the same master, and the render's caption file is kept beside the full
reel so ``checks.py`` can hold the burn-in to the M2.4 phrase rule.

Scheduling: renders are bulk work. They run at the lowest CPU priority, only
inside the off-peak window (``SHOWCASE_OFFPEAK_HOURS``, default ``1-7``) unless
``--now`` is passed on a dev machine, and never ahead of paid renders: when
``SHOWCASE_BROKER_URL`` points at the render broker, the job waits while the
paid or first-reel lane queues hold work, and stops after
``SHOWCASE_PAID_WAIT_S`` (default 1800) seconds of waiting.

Any reel whose style needs a paid model (a presenter or AI illustrations) is
skipped and listed in the results, never rendered.

Uploads are a deploy step. ``--plan`` prints the missing set and the planned
uploads (dry run, no deletes); ``--apply`` does not exist here on purpose:
``publish.py --qa ... --apply`` and the private-bucket copy run at deploy.

    REELFORGE_DISABLE_DOTENV=1 IMAGEIO_FFMPEG_EXE=... \\
        python apps/api/tools/ops/showcase/render_full.py [--now] [keys...]
    python apps/api/tools/ops/showcase/render_full.py --plan
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
REPO = os.path.abspath(os.path.join(API, "..", ".."))
STAGING = os.environ.get("SHOWCASE_OUT", os.path.join(REPO, "public-samples-staging"))
WORK = os.environ.get("SHOWCASE_WORK", "/tmp/menivor-showcase")
MANIFEST = os.path.join(HERE, "full-manifest.json")
SOURCES = os.path.join(HERE, "sources.json")
PRIVATE_PREFIX = "marketing/showcase"
PUBLIC_PREFIX = "showcase"
MIN_FREE_GB = 12.0
#: Keep this much audio after the last sound when the silent tail is trimmed.
TAIL_KEEP_S = 0.6
PAID_WAIT_POLL_S = 30.0

if HERE not in sys.path:
    sys.path.insert(0, HERE)

import checks  # noqa: E402


class ManifestDrift(RuntimeError):
    """``sources.json`` and ``full-manifest.json`` name different reels."""


# --------------------------------------------------------------------------- #
# Manifest and missing set
# --------------------------------------------------------------------------- #
def load_manifest(path: str = MANIFEST) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def source_keys(path: str = SOURCES) -> list[str]:
    with open(path, encoding="utf-8") as handle:
        return [str(r["key"]) for r in json.load(handle)["reels"]]


def full_path(key: str, staging: str = STAGING) -> str:
    return os.path.join(staging, "full", f"{key}-full.mp4")


def captions_path(key: str, staging: str = STAGING) -> str:
    return os.path.join(staging, "full", f"{key}-captions.ass")


def missing_set(
    sources: Sequence[str],
    manifest: Sequence[str],
    full_dir: str,
    *,
    passes: Callable[[str, str], bool],
) -> list[str]:
    """Manifest keys (in order) whose full reel is absent or fails its checks."""
    only_sources = sorted(set(sources) - set(manifest))
    only_manifest = sorted(set(manifest) - set(sources))
    if only_sources or only_manifest:
        raise ManifestDrift(
            f"sources.json only: {', '.join(only_sources) or '-'}; "
            f"full-manifest.json only: {', '.join(only_manifest) or '-'}"
        )
    out = []
    for key in manifest:
        path = os.path.join(full_dir, f"{key}-full.mp4")
        if not os.path.isfile(path) or not passes(key, path):
            out.append(key)
    return out


def _passes_checks(reels: dict[str, dict], staging: str) -> Callable[[str, str], bool]:
    def passes(key: str, path: str) -> bool:
        return bool(checks.full_verdict(path, captions_path(key, staging), reels[key])["ok"])

    return passes


# --------------------------------------------------------------------------- #
# Paid-model skip list
# --------------------------------------------------------------------------- #
#: Style visuals the showcase renders for $0 with a free substitute
#: (``character``: the procedural original narrator art, not the paid portrait).
FREE_VISUALS = frozenset({"page", "none", "character"})


def paid_model_reason(reel: dict) -> str | None:
    """Why ``reel`` would need a paid model, or ``None`` when it renders for $0."""
    style_id = str(reel.get("style") or "")
    if not style_id:
        return None
    if API not in sys.path:
        sys.path.insert(0, API)
    from app.domains.styles.catalog import get_style

    style = get_style(style_id)
    if style is None:
        return f"unknown style {style_id!r}"
    if style.needs_presenter:
        return f"style {style.id} needs a presenter (paid talking-head model)"
    if style.visual not in FREE_VISUALS:
        return f"style {style.id} needs {style.visual} visuals (paid image model)"
    return None


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #
def offpeak_hours(raw: str | None = None) -> tuple[int, int]:
    value = (raw if raw is not None else os.environ.get("SHOWCASE_OFFPEAK_HOURS", "1-7")).strip()
    start, _, end = value.partition("-")
    return int(start) % 24, int(end or start) % 24


def in_offpeak(now: _dt.datetime, window: tuple[int, int]) -> bool:
    start, end = window
    if start == end:
        return True
    if start < end:
        return start <= now.hour < end
    return now.hour >= start or now.hour < end


def paid_queue_busy(client=None) -> bool:
    """True while the paid or first-reel render lanes hold queued work."""
    if client is None:
        url = (os.environ.get("SHOWCASE_BROKER_URL") or "").strip()
        if not url:
            return False
        import redis

        client = redis.Redis.from_url(url, socket_timeout=5)
    if API not in sys.path:
        sys.path.insert(0, API)
    from app.domains.reels.policy import LANE_FIRST, LANE_PAID, LANE_QUEUES

    return any(int(client.llen(LANE_QUEUES[lane]) or 0) > 0 for lane in (LANE_PAID, LANE_FIRST))


def may_render(
    now: _dt.datetime,
    *,
    now_flag: bool,
    window: tuple[int, int],
    paid_busy: Callable[[], bool],
) -> tuple[bool, str]:
    if not now_flag and not in_offpeak(now, window):
        return False, "outside the off-peak window (SHOWCASE_OFFPEAK_HOURS); pass --now on a dev machine"
    if paid_busy():
        return False, "paid renders are queued; showcase renders never go ahead of them"
    return True, ""


# --------------------------------------------------------------------------- #
# Encode
# --------------------------------------------------------------------------- #
def _ffmpeg() -> str:
    return os.environ.get("SHOWCASE_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"


def _run(argv: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, check=True, timeout=timeout)


def measure_loudnorm(master: str, target: float) -> dict:
    """First ``loudnorm`` pass: the measured values the second pass needs."""
    log = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-nostats", "-i", master, "-vn",
         "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, timeout=600,
    ).stderr
    blocks = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", log)
    if not blocks:
        raise RuntimeError(f"loudnorm measurement failed for {master}")
    return json.loads(blocks[-1])


def _keep_seconds(master: str) -> float | None:
    """Trimmed length when the master ends in silence, else ``None``."""
    info = checks.probe_full(master)
    duration = info["duration_s"]
    tail = checks.silent_tail_seconds(checks.silence_log(master), duration)
    if tail <= checks.MAX_SILENT_TAIL_S - TAIL_KEEP_S:
        return None
    return max(checks.MIN_SECONDS, duration - tail + TAIL_KEEP_S)


def encode_full(master: str, dest: str, *, target: float = checks.LUFS_TARGET) -> str:
    """720x1280 H.264 + AAC full reel with loudness normalised to ``target``."""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    keep = _keep_seconds(master)
    trim = ["-t", f"{keep:.2f}"] if keep else []
    m = measure_loudnorm(master, target)
    loudnorm = (
        f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
        f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
        "linear=true,aresample=48000"
    )
    width, height = checks.FULL_SIZE
    tmp = dest + ".part.mp4"
    _run([_ffmpeg(), "-v", "error", "-y", "-i", master, *trim,
          "-vf", f"scale={width}:{height}:flags=lanczos,setsar=1", "-af", loudnorm,
          "-c:v", "libx264", "-preset", "slow", "-crf", "25", "-profile:v", "high", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", tmp])
    os.replace(tmp, dest)
    return dest


def encode_web(master: str, key: str, staging: str = STAGING) -> list[str]:
    """The muted wall loop and the poster (same settings as ``encode_web.sh``)."""
    web = os.path.join(staging, "web")
    os.makedirs(web, exist_ok=True)
    loop = os.path.join(web, f"{key}.mp4")
    poster = os.path.join(web, f"{key}-poster.jpg")
    duration = checks.probe_full(master)["duration_s"]
    _run([_ffmpeg(), "-v", "error", "-y", "-t", f"{min(9.0, duration):.2f}", "-i", master, "-an",
          "-vf", "scale=540:960:flags=lanczos,fps=30", "-c:v", "libx264", "-preset", "slow", "-crf", "23",
          "-maxrate", "1100k", "-bufsize", "2600k", "-profile:v", "high", "-pix_fmt", "yuv420p",
          "-g", "60", "-movflags", "+faststart", loop])
    _run([_ffmpeg(), "-v", "error", "-y", "-ss", "0.5", "-i", master, "-vf", "scale=540:960:flags=lanczos",
          "-frames:v", "1", "-q:v", "5", poster])
    return [loop, poster]


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def _master_ok(master: str) -> bool:
    if not os.path.isfile(master):
        return False
    info = checks.probe_full(master)
    return info["audio_streams"] >= 1 and checks.MIN_SECONDS <= info["duration_s"] <= checks.MAX_SECONDS


def _latest_captions(key: str, work: str = WORK) -> str | None:
    found = glob.glob(os.path.join(work, ".store", "jobs", f"landing-{key}-*", "captions.ass"))
    return max(found, key=os.path.getmtime) if found else None


def ensure_narrator(work: str = WORK) -> str:
    """The cartoon narrator portrait, drawn by the procedural original-character art ($0)."""
    path = os.path.join(work, "narrator.png")
    if os.path.isfile(path):
        return path
    if API not in sys.path:
        sys.path.insert(0, API)
    from app.domains.characters import narrator_art, narrators

    character = narrators.list_narrators()[0]
    os.makedirs(work, exist_ok=True)
    narrator_art.render_pose(character, "X", True, 440).save(path)
    return path


def render_key(reel: dict, staging: str = STAGING) -> dict:
    """Render (when needed), encode and check one reel; returns its result row."""
    import runner

    key = reel["key"]
    started = time.time()
    master = os.path.join(staging, "masters", f"{key}.mp4")
    ass_dest = captions_path(key, staging)
    if not (_master_ok(master) and os.path.isfile(ass_dest)):
        ensure_narrator()
        runner.render(reel)
        ass = _latest_captions(key)
        if not ass:
            raise RuntimeError(f"{key}: the render left no caption file")
        os.makedirs(os.path.dirname(ass_dest), exist_ok=True)
        shutil.copyfile(ass, ass_dest)
    dest = encode_full(master, full_path(key, staging))
    encode_web(master, key, staging)
    verdict = checks.full_verdict(dest, ass_dest, reel)
    return {"key": key, "ok": verdict["ok"], "errors": verdict["errors"], "lufs": verdict.get("lufs"),
            "duration_s": round(verdict.get("duration_s") or 0.0, 2), "seconds": round(time.time() - started, 1),
            "lane": "bulk", "spend_usd": 0.0, "full": dest}


# --------------------------------------------------------------------------- #
# Upload plan (dry run) and results
# --------------------------------------------------------------------------- #
def upload_plan(keys: Iterable[str], staging: str = STAGING) -> list[str]:
    """Every upload the deploy step makes, in order. Nothing is ever deleted."""
    lines = []
    for key in keys:
        local = full_path(key, staging)
        lines.append(f"PUT (deploy step) private {PRIVATE_PREFIX}/{key}-full.mp4 <- {local}")
        lines.append(f"PUT (deploy step) public {PUBLIC_PREFIX}/{key}-full.mp4 <- {local}")
        lines.append(f"PUT (deploy step) public {PUBLIC_PREFIX}/{key}.mp4 <- "
                     f"{os.path.join(staging, 'web', key + '.mp4')}")
        lines.append(f"PUT (deploy step) public {PUBLIC_PREFIX}/{key}-poster.jpg <- "
                     f"{os.path.join(staging, 'web', key + '-poster.jpg')}")
    return lines


def write_results(path: str, rendered: list[dict], *, skipped: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"generated": _dt.datetime.now().isoformat(timespec="seconds"),
                   "rendered": rendered, "skipped_paid_model": skipped}, handle, indent=1)
        handle.write("\n")


def _wait_for_paid_lanes(max_wait_s: float) -> bool:
    waited = 0.0
    while paid_queue_busy():
        if waited >= max_wait_s:
            return False
        time.sleep(PAID_WAIT_POLL_S)
        waited += PAID_WAIT_POLL_S
    return True


def main(argv: Iterable[str] | None = None) -> int:
    import plan

    parser = argparse.ArgumentParser(description="Render the full showcase reels with sound (PM1.1)")
    parser.add_argument("keys", nargs="*")
    parser.add_argument("--now", action="store_true", help="skip the off-peak window (dev machine only)")
    parser.add_argument("--plan", action="store_true", help="print the missing set and planned uploads only")
    parser.add_argument("--results", default=os.path.join(WORK, "full-results.json"))
    args = parser.parse_args(list(argv) if argv is not None else None)

    reels = {r["key"]: r for r in plan.REELS}
    manifest = load_manifest()["keys"]
    missing = missing_set(source_keys(), manifest, os.path.join(STAGING, "full"),
                          passes=_passes_checks(reels, STAGING))
    if args.keys:
        missing = [k for k in missing if k in set(args.keys)]
    skipped = {k: why for k in missing if (why := paid_model_reason(reels[k]))}
    todo = [k for k in missing if k not in skipped]
    if args.plan:
        print(json.dumps({"missing": missing, "skipped_paid_model": skipped}, indent=1))
        print("\n".join(upload_plan(manifest)))
        return 0

    ok, why = may_render(_dt.datetime.now(), now_flag=args.now, window=offpeak_hours(), paid_busy=lambda: False)
    if not ok:
        raise SystemExit(why)
    with contextlib.suppress(OSError, AttributeError):
        os.nice(19)
    max_wait = float(os.environ.get("SHOWCASE_PAID_WAIT_S", "1800"))
    rendered: list[dict] = []
    for key in todo:
        free_gb = shutil.disk_usage("/").free / 1e9
        if free_gb < MIN_FREE_GB:
            print(f"only {free_gb:.1f} GB free; stopping before {key}", flush=True)
            break
        if not _wait_for_paid_lanes(max_wait):
            print(f"paid lanes stayed busy for {max_wait:.0f}s; stopping before {key}", flush=True)
            break
        try:
            rendered.append(render_key(reels[key]))
        except Exception as exc:  # noqa: BLE001 - keep going, record the failure
            rendered.append({"key": key, "ok": False, "errors": [f"{type(exc).__name__}: {exc}"]})
        print(json.dumps(rendered[-1]), flush=True)
        write_results(args.results, rendered, skipped=skipped)
    write_results(args.results, rendered, skipped=skipped)
    return 0 if all(r.get("ok") for r in rendered) else 1


if __name__ == "__main__":
    raise SystemExit(main())
