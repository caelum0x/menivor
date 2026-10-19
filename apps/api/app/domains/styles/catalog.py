"""One-click reel STYLES: short-form formats that drive the existing pipeline.

A style is not a template. It is a small preset that the job API folds into
``ReelForgeParams`` (layout, caption style, background loop, hook family) plus a
scene recipe the compose stage uses to build the reel's visual track from the
creator's own link:

* ``stack``        - product visuals on top, a looping companion clip below
                     (gameplay parkour or a satisfying loop), captions on the seam.
* ``meme``         - a white meme-caption band with the hook over the visuals.
* ``full``         - full-screen visuals (page image or AI art) with slow motion.
* ``pov``          - full-screen visuals with the POV line pinned on screen.
* ``before_after`` - a dimmed "before" half over a vivid "after" half.
* ``""``           - no scene: the classic presenter/background compose.

``visual`` says where the product visuals come from: ``page`` (the pasted page's
own preview image, else a branded title card), ``anime`` (original AI-generated
anime-style illustrations, see ``app.services.styles.visuals``) or ``none``.

Pure data (no I/O). Public ids are stable: they are persisted in ``Job.params``
and sent by the web create box.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

CAPTIONS_ONLY = "captions_only"


@dataclass(frozen=True)
class StyleSpec:
    id: str
    label: str
    blurb: str
    layout: str
    caption_style: str
    hook_family: tuple[str, ...]
    scene: str = ""
    visual: str = "page"
    background_id: str = ""
    needs_presenter: bool = False
    # Honest per-render provider cost on top of narration (USD), for the UI.
    extra_cost_usd: float = 0.0
    # "page": a link run's body is the page's own facts. "story": the API
    # writes a first-person story about the product (no typed body).
    script_mode: str = "page"

    def to_public(self) -> dict:
        data = asdict(self)
        data["hook_family"] = list(self.hook_family)
        return data


_STYLES: tuple[StyleSpec, ...] = (
    StyleSpec(
        id="gameplay_split",
        label="Block-world gameplay",
        blurb="Your product on top, block-world parkour gameplay below, captions on the seam.",
        layout=CAPTIONS_ONLY,
        caption_style="split_center",
        hook_family=("pov", "question", "nobody_tells_you"),
        scene="stack",
        visual="page",
        background_id="block-runner",
    ),
    StyleSpec(
        id="meme_hook",
        label="Meme hook",
        blurb="A meme-caption hook like “you met me at a very ___ time in my life”, written for your product.",
        layout=CAPTIONS_ONLY,
        caption_style="meme_clean",
        hook_family=("met_me_at", "nobody_me", "tell_me_without", "wish_i_knew", "day_in_life"),
        scene="meme",
        visual="page",
        background_id="block-runner",
    ),
    StyleSpec(
        id="anime",
        label="Anime style",
        blurb="Original AI anime-style scenes about your product, narrated with word-by-word captions.",
        layout=CAPTIONS_ONLY,
        caption_style="anime_pop",
        hook_family=("story", "pov", "question"),
        scene="full",
        visual="anime",
        extra_cost_usd=0.012,
    ),
    StyleSpec(
        id="satisfying_split",
        label="Satisfying split",
        blurb="Your product on top, a calm satisfying loop below that keeps eyes on screen.",
        layout=CAPTIONS_ONLY,
        caption_style="split_center",
        hook_family=("nobody_tells_you", "question", "pov"),
        scene="stack",
        visual="page",
        background_id="sand-slice",
    ),
    StyleSpec(
        id="pov_text",
        label="POV text",
        blurb="A big “POV:” line pinned on screen while the story plays out.",
        layout=CAPTIONS_ONLY,
        # Bottom captions: the POV line owns the top of the frame.
        caption_style="meme_clean",
        hook_family=("pov",),
        scene="pov",
        visual="page",
        background_id="marble-loop",
    ),
    StyleSpec(
        id="before_after",
        label="Before / after",
        blurb="Life before your product on top, after it below. The contrast sells it.",
        layout=CAPTIONS_ONLY,
        caption_style="split_center",
        hook_family=("before_after", "wish_i_knew", "story"),
        scene="before_after",
        visual="page",
    ),
    StyleSpec(
        id="story_gameplay",
        label="Story time",
        blurb="A first-person story about your product over parkour gameplay, opened by a story card.",
        layout=CAPTIONS_ONLY,
        caption_style="split_center",
        hook_family=("story", "pov", "wish_i_knew"),
        scene="story",
        visual="none",
        background_id="block-runner",
        script_mode="story",
    ),
    StyleSpec(
        id="character_story",
        label="Cartoon narrator",
        blurb="An original cartoon narrator tells your product's story over gameplay.",
        layout=CAPTIONS_ONLY,
        caption_style="split_center",
        hook_family=("story", "question", "pov"),
        scene="character",
        visual="character",
        background_id="block-runner",
        extra_cost_usd=0.003,
        script_mode="story",
    ),
    StyleSpec(
        id="ugc_avatar",
        label="UGC presenter",
        blurb="An AI presenter pitches your product to camera, then drops into a corner bubble.",
        layout="hook_intro",
        caption_style="karaoke_yellow",
        hook_family=("pov", "question", "nobody_tells_you"),
        scene="full",
        visual="page",
        needs_presenter=True,
    ),
    StyleSpec(
        id="greenscreen",
        label="Green-screen reaction",
        blurb="An AI presenter reacts in front of your product page, green-screen style.",
        layout="pip",
        caption_style="karaoke_green",
        hook_family=("question", "story", "pov"),
        scene="full",
        visual="page",
        needs_presenter=True,
    ),
)

_BY_ID = {style.id: style for style in _STYLES}
STYLE_IDS: tuple[str, ...] = tuple(style.id for style in _STYLES)


class UnknownStyleError(ValueError):
    """An unknown style id was requested."""


def list_styles() -> list[StyleSpec]:
    return list(_STYLES)


def get_style(style_id: str) -> StyleSpec | None:
    return _BY_ID.get(normalize_style_id(style_id))


def normalize_style_id(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def require_style(value: object) -> StyleSpec | None:
    """The style for ``value``; ``None`` for blank; raise on an unknown id."""
    key = normalize_style_id(value)
    if not key:
        return None
    style = _BY_ID.get(key)
    if style is None:
        raise UnknownStyleError(f"unknown style {value!r} (allowed: {', '.join(STYLE_IDS)})")
    return style


def style_overrides(style: StyleSpec, *, hook_style: str = "") -> dict:
    """``ReelForgeParams`` fields a style sets (the one-click choice wins).

    The hook angle is only filled when the caller did not pick one, so a link
    run that already wrote a meme hook keeps its own label.
    """
    overrides: dict = {
        "style": style.id,
        "layout": style.layout,
        "caption_style": style.caption_style,
    }
    if style.background_id:
        overrides["background_id"] = style.background_id
    if not str(hook_style or "").strip() and style.hook_family:
        overrides["hook_style"] = style.hook_family[0]
    return overrides


__all__ = [
    "CAPTIONS_ONLY",
    "STYLE_IDS",
    "StyleSpec",
    "UnknownStyleError",
    "get_style",
    "list_styles",
    "normalize_style_id",
    "require_style",
    "style_overrides",
]
