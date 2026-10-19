"""Curated background-footage library for split-screen / loop formats.

The missing piece that lets the **story-over-gameplay split, brainrot, ASMR-loop
and recap** formats render *without the user sourcing footage*: a reviewed
registry of loop-able "second-stimulation" backgrounds (gameplay parkour,
satisfying ASMR, driving …), each resolvable to real footage.

Two source kinds, honestly labelled:

* ``stock``   — resolvable **today** via the existing stock fetcher
  (``services/material.download_videos``, Pexels/Pixabay) using a curated query.
* ``bundled`` — a first-party loop hosted in R2 (best quality / rights-clean);
  ``needs_asset=True`` marks the ones whose loop still has to be uploaded, so the
  gap is explicit rather than a silent failure.

The templates compiler auto-fills a template's ``default_background`` when the
caller supplies no ``gameplay_clip``; the compose stage materializes the chosen
background to a local clip via :func:`materialize`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Categories group backgrounds for the picker.
GAMEPLAY = "gameplay"
SATISFYING = "asmr-satisfying"
DRIVING = "driving"
NATURE = "nature"


@dataclass(frozen=True)
class BackgroundClip:
    id: str
    category: str
    label: str
    source: str  # "stock" | "bundled"
    query: str = ""  # stock search term (source == "stock")
    r2_key: str = ""  # optional bundled loop object key
    asset_path: str = ""  # packaged filename under assets/backgrounds
    provider: str = "pexels"
    loopable: bool = True
    license_note: str = ""
    needs_asset: bool = False  # bundled loop not yet packaged/uploaded


_ASSET_ROOT = (Path(__file__).resolve().parent / "assets" / "backgrounds").resolve()


# --- The curated catalog ---------------------------------------------------- #
_CLIPS: tuple[BackgroundClip, ...] = (
    # Original abstract stimulation loops with no game capture or branded art.
    # Their legacy ids (named after games) still resolve through
    # LEGACY_BACKGROUND_ALIASES so stored jobs and templates keep working.
    BackgroundClip(
        "voxel-parkour",
        GAMEPLAY,
        "Voxel motion loop",
        "bundled",
        asset_path="voxel-parkour.mp4",
        license_note="Original in-house loop generated with FFmpeg lavfi.",
    ),
    BackgroundClip(
        "neon-runner",
        GAMEPLAY,
        "Neon runner loop",
        "bundled",
        asset_path="neon-runner.mp4",
        license_note="Original in-house loop generated with FFmpeg lavfi.",
    ),
    # Procedurally rendered in-house loops (scripts/background-loops): original
    # code-drawn scenes, no game capture, no third-party art or trademarks.
    BackgroundClip(
        "block-runner",
        GAMEPLAY,
        "Block parkour run",
        "bundled",
        asset_path="block-runner.mp4",
        license_note="Original in-house loop rendered from our own three.js scene.",
    ),
    *(
        BackgroundClip(
            f"block-runner-{n}",
            GAMEPLAY,
            f"Block parkour run {n}",
            "bundled",
            asset_path=f"block-runner-{n}.mp4",
            license_note="Original in-house loop rendered from our own three.js scene.",
        )
        for n in range(2, 7)
    ),
    BackgroundClip(
        "sand-slice",
        SATISFYING,
        "Sand slicing (satisfying)",
        "bundled",
        asset_path="sand-slice.mp4",
        license_note="Original in-house loop rendered from our own canvas scene.",
    ),
    *(
        BackgroundClip(
            f"sand-slice-{n}",
            SATISFYING,
            f"Sand slicing {n}",
            "bundled",
            asset_path=f"sand-slice-{n}.mp4",
            license_note="Original in-house loop rendered from our own canvas scene.",
        )
        for n in range(2, 4)
    ),
    BackgroundClip(
        "marble-loop",
        SATISFYING,
        "Marble run loop",
        "bundled",
        asset_path="marble-run.mp4",
        license_note="Original in-house loop rendered from our own three.js scene.",
    ),
    *(
        BackgroundClip(
            f"marble-loop-{n}",
            SATISFYING,
            f"Marble run loop {n}",
            "bundled",
            asset_path=f"marble-run-{n}.mp4",
            license_note="Original in-house loop rendered from our own three.js scene.",
        )
        for n in range(2, 4)
    ),
    BackgroundClip("generic-parkour", GAMEPLAY, "Generic parkour (stock)", "stock",
                   query="parkour freerunning rooftop", provider="pexels",
                   license_note="Pexels license — commercial OK."),
    BackgroundClip(
        "synthwave-road",
        DRIVING,
        "Synthwave road loop",
        "bundled",
        asset_path="synthwave-road.mp4",
        license_note="Original in-house loop generated with FFmpeg lavfi.",
    ),
    BackgroundClip("city-driving", DRIVING, "City driving POV (stock)", "stock",
                   query="pov city driving night", provider="pexels"),
    # Satisfying / ASMR — resolvable on stock today.
    BackgroundClip("kinetic-sand-cutting", SATISFYING, "Kinetic sand cutting", "stock",
                   query="kinetic sand cutting satisfying", provider="pixabay"),
    BackgroundClip("soap-cutting", SATISFYING, "Soap cutting ASMR", "stock",
                   query="soap cutting asmr satisfying", provider="pixabay"),
    BackgroundClip("slime-poking", SATISFYING, "Slime poking", "stock",
                   query="slime satisfying asmr", provider="pixabay"),
    BackgroundClip("hydraulic-press", SATISFYING, "Hydraulic press crush", "stock",
                   query="hydraulic press crushing", provider="pexels"),
    BackgroundClip("pressure-washing", SATISFYING, "Pressure washing", "stock",
                   query="pressure washing satisfying clean", provider="pexels"),
    BackgroundClip("marble-run", SATISFYING, "Marble run", "stock",
                   query="marble run satisfying", provider="pixabay"),
    # Calm nature loops (recap / talking-head backdrops).
    BackgroundClip("aerial-nature", NATURE, "Aerial nature", "stock",
                   query="aerial drone nature landscape", provider="pexels"),
)

_BY_ID = {c.id: c for c in _CLIPS}

#: Legacy background ids (named after third-party games) -> the neutral id the
#: API now shows. Old ids in stored jobs, templates, channels and older app
#: builds keep resolving; no API response ever returns a legacy id.
LEGACY_BACKGROUND_ALIASES: dict[str, str] = {
    "minecraft-parkour": "voxel-parkour",
    "subway-surfers": "neon-runner",
    "gta-driving": "synthwave-road",
}


def canonical_id(background_id: str) -> str:
    """The current id for ``background_id`` (legacy ids map to neutral ones)."""
    value = str(background_id or "").strip()
    return LEGACY_BACKGROUND_ALIASES.get(value, value)


# Genre → sensible default background id (used when the caller supplies no clip).
_GENRE_DEFAULT = {
    "brainrot-split": "voxel-parkour",
    "brainrot": "neon-runner",
    "asmr": "kinetic-sand-cutting",
    "asmr-loop": "kinetic-sand-cutting",
    "recap": "aerial-nature",
    "podcast": "generic-parkour",
    "gameplay": "generic-parkour",
}


def get(background_id: str) -> BackgroundClip | None:
    return _BY_ID.get(canonical_id(background_id))


def list_backgrounds(category: str | None = None) -> list[BackgroundClip]:
    clips = list(_CLIPS)
    if category:
        clips = [c for c in clips if c.category == category]
    return sorted(clips, key=lambda c: (c.category, c.id))


def variants_of(background_id: str) -> list[BackgroundClip]:
    """The clip and its numbered variants (``<id>``, ``<id>-2``, ``<id>-3`` ...).

    Split styles mix several variants per reel so no two reels reuse the same
    loop end to end.
    """
    base = canonical_id(background_id)
    out: list[BackgroundClip] = []
    for clip in _CLIPS:
        suffix = clip.id[len(base) + 1:] if clip.id.startswith(base + "-") else ""
        if clip.id == base or suffix.isdigit():
            out.append(clip)
    return out


def default_for_genre(genre: str) -> str:
    """Best default background id for a template genre (may be ``""``)."""
    return _GENRE_DEFAULT.get(str(genre or "").strip(), "")


def resolve(background_id: str, *, genre: str = "", prefer_available: bool = True) -> BackgroundClip | None:
    """Resolve an explicit id, else the genre default.

    When ``prefer_available`` and the chosen clip is a bundled loop that hasn't
    been uploaded yet (``needs_asset``), fall back to an **available** (stock)
    background in the same category so the format still renders today — upgrading
    to the first-party loop automatically once its asset exists.
    """
    clip = get(background_id)
    if clip is None and genre:
        clip = get(default_for_genre(genre))
    if clip is None:
        return None
    if prefer_available and clip.needs_asset:
        for alt in list_backgrounds(clip.category):
            if not alt.needs_asset:
                return alt
    return clip


class BackgroundUnavailable(Exception):
    """The chosen background can't be materialized (bundled loop not uploaded)."""


def materialize(
    clip: BackgroundClip,
    *,
    task_id: str,
    duration_s: float,
    downloader=None,
    storage=None,
) -> list[str]:
    """Resolve a background clip to local video file path(s).

    ``stock`` → fetch via the real stock downloader (Pexels/Pixabay). ``bundled``
    → pull the first-party loop from R2. Raises :class:`BackgroundUnavailable`
    when a bundled loop hasn't been uploaded yet (explicit, not silent).

    ``downloader``/``storage`` are injectable for tests; production uses the real
    ``services.material.download_videos`` + R2 storage.
    """
    if clip.source == "stock":
        if downloader is None:
            from app.services import material

            downloader = material.download_videos
        return list(downloader(
            task_id, [clip.query], source=clip.provider,
            audio_duration=float(duration_s), max_clip_duration=6,
        ) or [])
    # Packaged loops are part of the worker image and need no network/credential.
    if clip.asset_path:
        candidate = (_ASSET_ROOT / clip.asset_path).resolve()
        if candidate.parent != _ASSET_ROOT or candidate.suffix.lower() != ".mp4":
            raise BackgroundUnavailable(
                f"background {clip.id!r} has an invalid packaged asset path"
            )
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            raise BackgroundUnavailable(
                f"background {clip.id!r} packaged asset is missing"
            )
        return [str(candidate)]
    # Remote bundled objects remain supported for future operator-owned media.
    if clip.needs_asset:
        raise BackgroundUnavailable(
            f"background {clip.id!r} needs a first-party loop uploaded to "
            f"{clip.r2_key!r} — pick a 'stock' background or upload the asset."
        )
    if storage is None:
        storage = _r2_download_to_temp
    return [storage(clip.r2_key)]


def _r2_download_to_temp(key: str) -> str:
    """Presign + download a bundled loop from R2 to a temp file (production default)."""
    import tempfile

    import requests

    from app.platform.storage.r2 import get_r2_client

    url = get_r2_client().presign_get(key, expires=900)
    fd, dest = tempfile.mkstemp(suffix=".mp4", prefix="bg_")
    import os

    os.close(fd)
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            if chunk:
                fh.write(chunk)
    return dest


def to_dict(clip: BackgroundClip) -> dict:
    return {
        "id": clip.id, "category": clip.category, "label": clip.label,
        "source": clip.source, "provider": clip.provider, "loopable": clip.loopable,
        "license_note": clip.license_note,
        "available": not clip.needs_asset,
    }
