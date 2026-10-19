"""Midjourney -> our pipeline WITHOUT automation (Midjourney has no official API; proxies and
Discord bots break its Terms of Service, so we never call it).

1. ``prompts(plan, preset)`` writes a ready-to-paste MJ prompt per still of a clone plan, with
   consistent character-reference (V7 ``--oref``/``--ow``, V6.1 ``--cref``/``--cw``) and style
   reference (``--sref``/``--sw``) notes and the file name to save the result as.
2. The owner renders in Midjourney and drops images into the watched inbox (or uploads them in
   the UI). ``import_inbox`` tags each image to a character (hero / oxhan / side) or to a still id
   (``s1.png``) and copies it into the project's ``mj/`` library with a manifest.
3. ``first_frames`` picks, per shot, the imported image used as the Kling first frame.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

TAGS = {"hero": "H", "oxhan": "O", "side": "N"}
IMAGE_EXT = {".png": b"\x89PNG", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".webp": b"RIFF"}
MAX_BYTES = 25 * 1024 * 1024
MANIFEST = "mj/manifest.json"
_STILL = re.compile(r"^(s\d{1,2})(?:[_\-.].*)?$", re.I)
_TAG = re.compile(r"^(hero|oxhan|side)(?:[_\-.].*)?$", re.I)
_PLACEHOLDER = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")


class ImportError_(ValueError):  # noqa: N801 - avoid shadowing the builtin
    status_code = 400


def tag_for(path: Path, inbox: Path) -> str | None:
    """Tag from the sub-folder (hero/, oxhan/, side/, s3/) or the file-name prefix."""
    rel = path.relative_to(inbox)
    candidates = [rel.parts[0]] if len(rel.parts) > 1 else []
    candidates.append(path.stem)
    for c in candidates:
        if m := _TAG.match(c):
            return m.group(1).lower()
        if m := _STILL.match(c):
            return m.group(1).lower()
    return None


def _is_image(path: Path) -> bool:
    magic = IMAGE_EXT.get(path.suffix.lower())
    if not magic or path.stat().st_size > MAX_BYTES:
        return False
    with open(path, "rb") as fh:
        head = fh.read(12)
    return head.startswith(magic) and (path.suffix.lower() != ".webp" or head[8:12] == b"WEBP")


def load_manifest(root: str) -> list[dict]:
    p = Path(root) / MANIFEST
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []


def import_inbox(inbox: str, root: str) -> dict[str, Any]:
    """Copy new tagged images from ``inbox`` into ``<root>/mj/<tag>/<sha>.<ext>``; returns imported + skipped."""
    src = Path(inbox)
    if not src.is_dir():
        raise ImportError_(f"inbox folder not found: {inbox}")
    manifest = load_manifest(root)
    known = {e["sha256"] for e in manifest}
    imported, skipped = [], []
    for path in sorted(p for p in src.rglob("*") if p.is_file() and not p.name.startswith(".")):
        tag = tag_for(path, src)
        if tag is None or not _is_image(path):
            skipped.append({"file": str(path.relative_to(src)), "why": "untagged" if tag is None else "not an image"})
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha in known:
            continue
        rel = f"mj/{tag}/{sha[:16]}{path.suffix.lower()}"
        dest = Path(root) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        imported.append({"tag": tag, "path": rel, "sha256": sha, "from": str(path.relative_to(src))})
        known.add(sha)
    new_manifest = [*manifest, *imported]
    if imported:
        save_manifest(root, new_manifest)
    return {"imported": imported, "skipped": skipped, "total": len(new_manifest)}


def save_manifest(root: str, manifest: list[dict]) -> Path:
    out = Path(root) / MANIFEST
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, out)
    return out


def tag_upload(manifest: list[dict], *, key: str, tag: str) -> list[dict]:
    """New manifest with a UI upload (``uploads/...`` storage key) tagged to a character or still."""
    tag = tag.lower().strip()
    if tag not in TAGS and not _STILL.match(tag):
        raise ImportError_("tag is hero, oxhan, side or a still id like s1")
    if not key.startswith("uploads/") or ".." in key or len(key) > 300:
        raise ImportError_("use a file you uploaded")
    return [*manifest, {"tag": tag, "key": key, "sha256": hashlib.sha256(key.encode()).hexdigest()}]


def first_frames(plan: Mapping[str, Any], manifest: list[dict]) -> dict[str, str | None]:
    """shot id -> imported image (still-tagged first, then the speaker's character image)."""
    latest: dict[str, str] = {}
    for e in manifest:
        latest[e["tag"]] = e.get("path") or e.get("key")
    by_char = {v: latest.get(k) for k, v in TAGS.items()}
    lines = {ln["id"]: ln for ln in plan.get("lines") or []}
    out = {}
    for s in plan.get("shots") or []:
        still = next((r for r in s.get("refs") or [] if not str(r).startswith("@") and "/" not in str(r)), None)
        speaker = lines.get((s.get("lines") or [None])[0], {}).get("speaker")
        out[s["id"]] = latest.get(str(still)) or by_char.get(speaker)
    return out


def _expand(text: str, preset: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    chars = preset["characters"]
    ctx = {"SET": plan.get("set", ""), "SWEAT": preset.get("sweat_short", ""), "LOOK": "", "NOTEXT": "",
           "NOSUB": "", "PRINTKEEP": "", **{f"DESC_{k}": c.get("desc", c.get("persona", "")) for k, c in chars.items()}}
    out = _PLACEHOLDER.sub(lambda m: str(ctx.get(m.group(1), "")), text)
    out = re.sub(r"\b(Vertical|Horizontal) (9:16|16:9)\b ?", "", out)
    out = re.sub(r"\(exactly the man in the first reference image\)", "", out)
    out = re.sub(r"The (reference image|third reference) is ONLY [^.]*\.", "", out)
    return re.sub(r"\s+", " ", out).strip()


def prompts(plan: Mapping[str, Any], preset: Mapping[str, Any]) -> list[dict]:
    """Ready-to-paste Midjourney prompts per still (V7 and V6.1 parameter variants)."""
    mj = preset.get("midjourney") or {}
    ar = plan.get("aspect", "9:16")
    sref = mj.get("sref_url") or "<STYLE_REF_URL>"
    crefs = mj.get("cref_urls") or {}
    names = {"H": "HERO_SHEET_URL", "O": "OXHAN_SHEET_URL", "N": "SIDE_SHEET_URL"}
    out = []
    for s in plan.get("stills") or []:
        who = next((r[1:] for r in s.get("refs") or [] if r in ("@H", "@O", "@N")), None)
        body = _expand(str(s.get("prompt") or ""), preset, plan)
        if s["id"] == "s0":
            who = None  # the set still has no people; @H there is only a style hint
        base = f"{body}, {mj.get('style', '')}, no text, no logos, no watermark --ar {ar} --stylize {mj.get('stylize', 150)}"
        cref = (crefs.get(who) or f"<{names.get(who, 'SHEET_URL')}>") if who else ""
        v7 = f"{base} --v 7 --sref {sref} --sw 200" + (f" --oref {cref} --ow {mj.get('cw', 100)}" if cref else "")
        v6 = f"{base} --v 6.1 --style raw --sref {sref} --sw 200" + (f" --cref {cref} --cw {mj.get('cw', 100)}" if cref else "")
        out.append({"still": s["id"], "character": who, "save_as": f"{s['id']}.png", "prompt_v7": v7, "prompt_v6": v6,
                    "notes": "Keep the same --sref on every still; character refs lock face/hair only, the sweatshirt "
                             "print is checked by eye. Never reference the source ad's character or frames."})
    return out
