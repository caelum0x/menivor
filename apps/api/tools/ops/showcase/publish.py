"""Publish showcase reels to the public media bucket and check they load.

Media lives in the public bucket (``menivor-public`` by default) behind the
custom domain ``media.menivor.com``, never on ``r2.dev``. Object keys:

    showcase/<key>.mp4          540x960 muted loop (the wall)
    showcase/<key>-poster.jpg   poster frame
    showcase/<key>-full.mp4     720x1280 full reel with sound

Modes (dry run unless ``--apply``):

    # new renders: only reels whose checks.py verdict passed are uploaded, so a
    # live reel is replaced only by a replacement that passed
    python checks.py --media --json /tmp/showcase-qa.json
    python publish.py --qa /tmp/showcase-qa.json [--apply]

    # first move: copy today's live files (web loops from apps/web/public, full
    # reels from the private bucket's marketing/showcase/) into the public bucket
    python publish.py --seed-existing [--apply]

    # clean-network check: every URL the landing uses returns 200
    python publish.py --verify

Nothing is ever deleted from either bucket.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
REPO = os.path.abspath(os.path.join(API, "..", ".."))
STAGING = os.environ.get("SHOWCASE_OUT", os.path.join(REPO, "public-samples-staging"))
WEB_PUBLIC = os.path.join(REPO, "apps", "web", "public", "samples", "showcase")
PREFIX = "showcase"
LEGACY_FULL_PREFIX = "marketing/showcase"
CACHE_CONTROL = "public, max-age=86400"


@dataclass(frozen=True)
class Upload:
    local: str
    key: str
    content_type: str


def object_keys(reel_key: str) -> dict[str, str]:
    return {
        "loop": f"{PREFIX}/{reel_key}.mp4",
        "poster": f"{PREFIX}/{reel_key}-poster.jpg",
        "full": f"{PREFIX}/{reel_key}-full.mp4",
    }


def passing_keys(qa: Mapping, keys: Iterable[str]) -> list[str]:
    """Reels whose media verdict passed; a plan failure blocks every upload."""
    if not qa.get("plan_ok"):
        return []
    media = qa.get("media") or {}
    return [key for key in keys if (media.get(key) or {}).get("ok")]


def staged_uploads(reel_key: str, staging: str = STAGING) -> list[Upload]:
    keys = object_keys(reel_key)
    return [
        Upload(os.path.join(staging, "web", f"{reel_key}.mp4"), keys["loop"], "video/mp4"),
        Upload(os.path.join(staging, "web", f"{reel_key}-poster.jpg"), keys["poster"], "image/jpeg"),
        Upload(os.path.join(staging, "full", f"{reel_key}-full.mp4"), keys["full"], "video/mp4"),
    ]


def public_urls(base: str, keys: Sequence[str]) -> list[str]:
    base = base.rstrip("/")
    return [f"{base}/{obj}" for key in keys for obj in object_keys(key).values()]


def _put(client, upload: Upload) -> None:
    with open(upload.local, "rb") as handle:
        client._s3.put_object(  # noqa: SLF001 - ops tool, sets Cache-Control
            Bucket=client._bucket, Key=upload.key, Body=handle,  # noqa: SLF001
            ContentType=upload.content_type, CacheControl=CACHE_CONTROL,
        )


def publish(uploads: Sequence[Upload], *, apply: bool, client_factory: Callable | None = None) -> list[str]:
    missing = [u.local for u in uploads if not os.path.isfile(u.local)]
    if missing:
        raise SystemExit("missing files:\n" + "\n".join(missing))
    lines = [f"{'PUT' if apply else 'dry-run'} {u.key} <- {u.local}" for u in uploads]
    if apply:
        client = (client_factory or _public_client)()
        for upload in uploads:
            _put(client, upload)
    return lines


def _public_client():
    sys.path.insert(0, API)
    from app.platform.storage.r2 import get_public_media_client

    return get_public_media_client()


def seed_existing(keys: Sequence[str], *, apply: bool) -> list[str]:
    """Copy today's live loops, posters and full reels into the public bucket."""
    uploads = []
    for key in keys:
        obj = object_keys(key)
        uploads.append(Upload(os.path.join(WEB_PUBLIC, f"{key}.mp4"), obj["loop"], "video/mp4"))
        uploads.append(Upload(os.path.join(WEB_PUBLIC, f"{key}-poster.jpg"), obj["poster"], "image/jpeg"))
    lines = publish(uploads, apply=apply)
    if not apply:
        return lines + [f"dry-run {object_keys(k)['full']} <- private {LEGACY_FULL_PREFIX}/{k}-full.mp4" for k in keys]
    sys.path.insert(0, API)
    from app.platform.storage.r2 import get_r2_client

    private = get_r2_client()
    with tempfile.TemporaryDirectory() as tmp:
        for key in keys:
            local = os.path.join(tmp, f"{key}-full.mp4")
            private.download_file(f"{LEGACY_FULL_PREFIX}/{key}-full.mp4", local)
            lines += publish([Upload(local, object_keys(key)["full"], "video/mp4")], apply=True)
    return lines


def verify(urls: Sequence[str], opener: Callable | None = None) -> list[str]:
    """HEAD every URL; returns the failures (r2.dev hosts always fail)."""
    failures: list[str] = []
    for url in urls:
        if ".r2.dev" in url:
            failures.append(f"{url}: r2.dev is not a production origin")
            continue
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "menivor-showcase-verify"})
            with (opener or urllib.request.urlopen)(req, timeout=30) as resp:  # noqa: S310 - fixed https base
                if resp.status != 200:
                    failures.append(f"{url}: HTTP {resp.status}")
        except (urllib.error.URLError, OSError) as exc:
            failures.append(f"{url}: {exc}")
    return failures


def main() -> int:
    sys.path.insert(0, HERE)
    import plan

    parser = argparse.ArgumentParser(description="Publish showcase reels to the public media bucket")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--qa", default="", help="checks.py --json output (new renders)")
    parser.add_argument("--seed-existing", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--base", default=os.environ.get("R2_PUBLIC_MEDIA_BASE_URL", "https://media.menivor.com"))
    parser.add_argument("keys", nargs="*")
    args = parser.parse_args()
    keys = args.keys or [r["key"] for r in plan.REELS]

    if args.verify:
        failures = verify(public_urls(args.base, keys))
        for line in failures:
            print("FAIL", line)
        print(f"{len(failures)} failure(s) across {len(keys) * 3} URLs")
        return 1 if failures else 0
    if args.seed_existing:
        lines = seed_existing(keys, apply=args.apply)
    elif args.qa:
        with open(args.qa, encoding="utf-8") as handle:
            ready = passing_keys(json.load(handle), keys)
        skipped = sorted(set(keys) - set(ready))
        lines = publish([u for key in ready for u in staged_uploads(key)], apply=args.apply)
        lines += [f"kept live (no passing replacement): {key}" for key in skipped]
    else:
        parser.error("pick --qa, --seed-existing or --verify")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
