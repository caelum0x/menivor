"""Render REAL sample reels, one per style, for the marketing site (ops tool).

Runs Menivor's own pipeline stages in-process (script -> tts -> avatar ->
captions -> compose) on reels that advertise OUR OWN products, so every sample
on the landing page is an honest render. No credits are debited (no Job row, no
ledger); the default voice is a free neural voice, and any paid provider call
(an ElevenLabs ``--voice``, Replicate art, HeyGen for presenter styles) is real
and its spend is logged. Cost-free first: pass a paid voice only on purpose.

A reel is published only when it passes the showcase media checks (moving,
with sound, 20-40 s; ``showcase/checks.py``). It goes to the PUBLIC media
bucket (``menivor-public`` behind ``media.menivor.com``, never ``r2.dev``) under
``marketing/styles/``. Renders run in the lowest (bulk) lane at the lowest CPU
priority and, like ``showcase/runner.py``, only in the off-peak window unless
``--now`` is passed.

Sample keys (``SAMPLE_PLAN``) are ``<style>`` or ``<style>-<n>``:

* ``<key>.mp4``          540x960 H.264, muted (the autoplay wall/cards)
       540x960 VP9, muted
* ``<key>-poster.jpg`` first-second poster
* ``<key>-full.mp4``     the full 1080x1920 render with sound

Usage (inside the worker container, env loaded):

    python apps/api/tools/ops/render_style_samples.py gameplay_split-2 meme_hook-3
    python apps/api/tools/ops/render_style_samples.py --all
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from loguru import logger  # noqa: E402

PRODUCTS: dict[str, tuple[str, str]] = {
    "menivor": ("Menivor", "https://menivor.com"),
    "rally": ("Rally", "https://vcpeer.com"),
    "scribase": ("Scribase", "https://scribase.com"),
    "recoder": ("Recoder", "https://recoder.xyz"),
}

# sample key -> (style, product, opening-hook format). Keys are the R2 object
# names under ``marketing/styles/``; every style gets several products/hooks.
SAMPLE_PLAN: dict[str, tuple[str, str, str]] = {
    # Second generation (moving page recordings, mixed loops): <style>-m<n>.
    "gameplay_split-m1": ("gameplay_split", "scribase", "pov"),
    "gameplay_split-m2": ("gameplay_split", "recoder", "nobody_tells_you"),
    "gameplay_split-m3": ("gameplay_split", "rally", "tell_me_without"),
    "meme_hook-m1": ("meme_hook", "menivor", "met_me_at"),
    "meme_hook-m2": ("meme_hook", "scribase", "nobody_me"),
    "meme_hook-m3": ("meme_hook", "recoder", "day_in_life"),
    "anime-m1": ("anime", "rally", "story"),
    "anime-m2": ("anime", "menivor", "story"),
    "anime-m3": ("anime", "recoder", "question"),
    "satisfying_split-m1": ("satisfying_split", "menivor", "wish_i_knew"),
    "satisfying_split-m2": ("satisfying_split", "rally", "nobody_tells_you"),
    "satisfying_split-m3": ("satisfying_split", "scribase", "question"),
    "pov_text-m1": ("pov_text", "menivor", "pov"),
    "pov_text-m2": ("pov_text", "recoder", "pov"),
    "pov_text-m3": ("pov_text", "rally", "pov"),
    "before_after-m1": ("before_after", "scribase", "before_after"),
    "before_after-m2": ("before_after", "menivor", "before_after"),
    "before_after-m3": ("before_after", "rally", "before_after"),
    "story_gameplay-m1": ("story_gameplay", "menivor", "story"),
    "story_gameplay-m2": ("story_gameplay", "recoder", "story"),
    "story_gameplay-m3": ("story_gameplay", "rally", "wish_i_knew"),
    "character_story-m1": ("character_story", "scribase", "question"),
    "character_story-m2": ("character_story", "menivor", "story"),
    "character_story-m3": ("character_story", "rally", "story"),
}

#: Free neural voice by default (cost-free first); a paid ``--voice`` is opt-in.
DEFAULT_VOICE = "en-US-AvaMultilingualNeural"
PREFIX = "marketing/styles"
CACHE_CONTROL = "public, max-age=31536000, immutable"
# Rough public list prices used only for the spend log.
TTS_USD_PER_1K_CHARS = 0.30
HEYGEN_USD_PER_MINUTE = 1.0


def _body(content: dict) -> list[str]:
    beats: list[str] = []
    description = str(content.get("description") or "").strip()
    if description:
        beats.append(description[:180].rstrip(" ,;") + ("" if description[-1:] in ".!?" else "."))
    for feature in list(content.get("features") or [])[:1]:
        text = str(feature).strip()
        if len(text) > 3:
            beats.append(text[:140].rstrip(" ,;") + ("" if text[-1:] in ".!?" else "."))
    beats.append("Check the link to try it.")
    return beats


def _script(style, content: dict, hook_format: str = "") -> tuple[str, dict]:
    from app.domains.styles.hooks import write_hooks

    hooks = write_hooks(
        title=str(content.get("title") or ""),
        description=str(content.get("description") or ""),
        features=list(content.get("features") or []),
        formats=[hook_format or style.hook_family[0]],
        language="en",
    )
    hook = hooks[0] if hooks else {"hook": content.get("title") or "", "hook_style": "", "source": "none"}
    return "\n\n".join([hook["hook"], *_body(content)]), hook


def _run(argv: list[str]) -> None:
    subprocess.run(argv, check=True, timeout=900)


def _qa(final_path: str) -> None:
    """Refuse to publish a reel that is static, silent or outside 20-40 s."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "showcase"))
    from checks import media_verdict

    verdict = media_verdict(final_path)
    if not verdict["ok"]:
        raise RuntimeError(f"showcase checks failed: {'; '.join(verdict['errors'])}")


def _publish(style_id: str, final_path: str, work: str) -> dict[str, str]:
    from app.platform.storage.r2 import get_public_media_client
    from app.utils import utils

    _qa(final_path)

    ffmpeg = utils.get_ffmpeg_binary() or "ffmpeg"
    small = os.path.join(work, f"{style_id}.mp4")
    poster = os.path.join(work, f"{style_id}-poster.jpg")
    scale = "scale=540:960:flags=lanczos"
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", final_path, "-vf", scale,
          "-c:v", "libx264", "-preset", "slow", "-crf", "28", "-profile:v", "high",
          "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", small])
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", "1.2", "-i", final_path,
          "-vf", scale, "-frames:v", "1", "-q:v", "4", poster])

    client = get_public_media_client()
    uploads = {
        f"{PREFIX}/{style_id}.mp4": (small, "video/mp4"),
        f"{PREFIX}/{style_id}-poster.jpg": (poster, "image/jpeg"),
        f"{PREFIX}/{style_id}-full.mp4": (final_path, "video/mp4"),
    }
    urls: dict[str, str] = {}
    for key, (path, content_type) in uploads.items():
        with open(path, "rb") as handle:
            client._s3.put_object(
                Bucket=client._bucket,
                Key=key,
                Body=handle,
                ContentType=content_type,
                CacheControl=CACHE_CONTROL,
            )
        urls[key] = client.public_url(key)
        logger.info(f"uploaded {key} ({os.path.getsize(path) // 1024} KB)")
    return urls


def _replicate_spend(style, ctx: dict) -> float:
    from app.services.styles.visuals import ANIME_COST_PER_IMAGE_USD, anime_image_count

    logged = float(ctx.get("style_provider_spend_usd") or 0.0)
    if logged or style.visual not in ("anime", "character"):
        return logged
    images = anime_image_count() if style.visual == "anime" else 1
    return round(images * ANIME_COST_PER_IMAGE_USD, 4)  # upper bound


def render_one(sample_key: str, *, voice: str, avatar: str, duration: int) -> dict:
    from app.domains.ingest.service import IngestService
    from app.domains.styles.catalog import get_style, style_overrides
    from app.services import reelforge

    if sample_key not in SAMPLE_PLAN:
        raise SystemExit(f"unknown sample {sample_key!r}")
    style_id, product_key, hook_format = SAMPLE_PLAN[sample_key]
    style = get_style(style_id)
    if style is None:
        raise SystemExit(f"unknown style {style_id!r}")
    if style.needs_presenter and not avatar:
        raise SystemExit(f"{style_id} needs --avatar (a HeyGen avatar id)")
    name, url = PRODUCTS[product_key]
    page = IngestService().url_to_reel(url)
    content = dict(page.get("content") or {})
    content["title"] = content.get("title") or name
    if style.script_mode == "story":
        # The pipeline writes a first-person story about the product itself.
        description = str(content.get("description") or "").strip()
        subject = f"{name}: {description}"[:200] if description else name
        script, hook = "", {"hook": "", "hook_style": hook_format, "source": "pipeline"}
    else:
        subject = name
        script, hook = _script(style, content, hook_format)

    params = reelforge.ReelForgeParams(
        video_subject=subject,
        video_script=script,
        voice_name=voice,
        avatar_id=avatar if style.needs_presenter else "",
        aspect="9:16",
        language="en",
        target_duration_s=duration,
        source_url=url,
        **style_overrides(style, hook_style=hook.get("hook_style", "")),
    )
    job_id = f"sample-{sample_key.replace('_', '-')}-{uuid.uuid4().hex[:8]}"
    logger.info(f"[{job_id}] {style_id} for {name}: hook={hook['hook']!r} ({hook['source']})")

    started = time.time()
    # Operator-funded: this tool pays ElevenLabs/HeyGen itself (no Job row, no
    # credits), so the premium guards must not downgrade or refuse the sample.
    from app.domains.reels.premium import OPERATOR_FUNDED_CTX_KEY

    ctx: dict = {OPERATOR_FUNDED_CTX_KEY: True}
    for stage in (
        reelforge.stage_script,
        reelforge.stage_tts,
        reelforge.stage_avatar,
        reelforge.stage_captions,
        reelforge.stage_compose,
    ):
        ctx = {**ctx, **(stage(job_id, params, ctx) or {})}
    final = str(ctx.get("final_video") or "")
    if not final or not os.path.isfile(final):
        raise RuntimeError(f"[{job_id}] compose produced no final video")

    narration_s = float(ctx.get("audio_duration") or 0.0)
    spend = {
        "tts_usd_est": round(len(str(ctx.get("script") or script)) / 1000 * TTS_USD_PER_1K_CHARS, 4),
        "replicate_usd": _replicate_spend(style, ctx),
        "heygen_usd_est": round(narration_s / 60 * HEYGEN_USD_PER_MINUTE, 4) if style.needs_presenter else 0.0,
    }
    urls = _publish(sample_key, final, os.path.dirname(final))
    # The reel is in R2 now: drop this sample's local intermediates (only the
    # sample's own task dir, never user jobs) so the box disk stays free.
    shutil.rmtree(os.path.dirname(final), ignore_errors=True)
    return {
        "sample": sample_key,
        "style": style_id,
        "product": name,
        "url": url,
        "job_id": job_id,
        "hook": hook,
        "seconds": round(time.time() - started, 1),
        "narration_s": round(narration_s, 1),
        "spend": spend,
        "urls": urls,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("styles", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--avatar", default="")
    parser.add_argument("--duration", type=int, default=28)
    parser.add_argument("--budget-usd", type=float, default=15.0)
    parser.add_argument("--min-free-gb", type=float, default=10.0)
    parser.add_argument("--now", action="store_true", help="skip the off-peak window (dev machine only)")
    args = parser.parse_args()
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "showcase"))
    import datetime as _dt

    from runner import in_offpeak, offpeak_hours

    if not args.now and not in_offpeak(_dt.datetime.now(), offpeak_hours()):
        raise SystemExit("outside the off-peak window (SHOWCASE_OFFPEAK_HOURS); pass --now on a dev machine")
    try:
        os.nice(19)
    except (OSError, AttributeError):
        pass
    styles = list(SAMPLE_PLAN) if args.all else args.styles
    total = 0.0
    results = []
    for sample_key in styles:
        free_gb = shutil.disk_usage("/").free / 1e9
        if free_gb < args.min_free_gb:
            logger.warning(f"only {free_gb:.1f} GB free (< {args.min_free_gb}); stopping before {sample_key}")
            break
        if total >= args.budget_usd:
            logger.warning(f"budget {args.budget_usd} reached; skipping {sample_key}")
            continue
        try:
            result = render_one(sample_key, voice=args.voice, avatar=args.avatar, duration=args.duration)
        except Exception as exc:  # noqa: BLE001 - keep rendering the other samples
            logger.error(f"{sample_key} failed: {type(exc).__name__}: {exc}")
            results.append({"sample": sample_key, "error": f"{type(exc).__name__}: {exc}"})
            continue
        total += sum(result["spend"].values())
        results.append(result)
    print(json.dumps({"results": results, "spend_usd_est": round(total, 4)}, indent=2))


if __name__ == "__main__":
    main()
