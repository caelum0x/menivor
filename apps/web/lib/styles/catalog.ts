/**
 * One-click reel STYLES (short-form formats). Mirrors the API catalog at
 * `GET /styles` (apps/api/app/domains/styles/catalog.py): the ids are sent as
 * `params.style` and the API folds each style into the render pipeline
 * (layout, captions, companion loop, hook formats, scene).
 *
 * Copy rule: these are "styles", never templates. The landing's sample reels
 * (real renders from Menivor's own pipeline) live in `./showcase`.
 */

export type StyleId =
  | "gameplay_split"
  | "meme_hook"
  | "anime"
  | "satisfying_split"
  | "pov_text"
  | "before_after"
  | "story_gameplay"
  | "character_story"
  | "ugc_avatar"
  | "greenscreen";

/** Opening-hook formats (the API's `hook_style` ids). */
export type StyleHookId =
  | "pov"
  | "question"
  | "nobody_tells_you"
  | "stat"
  | "story"
  | "met_me_at"
  | "nobody_me"
  | "wish_i_knew"
  | "before_after"
  | "tell_me_without"
  | "day_in_life";

export type StyleLayout = "captions_only" | "hook_intro" | "pip";

export interface ReelStyle {
  readonly id: StyleId;
  readonly label: string;
  readonly blurb: string;
  /** One line shown on the card: what the first second looks like. */
  readonly hookExample: string;
  readonly layout: StyleLayout;
  readonly backgroundId: string;
  readonly needsPresenter: boolean;
  readonly hookFamily: readonly StyleHookId[];
  /**
   * "page": link runs narrate the page's own facts under a written hook.
   * "story": the API writes a first-person story about the product.
   */
  readonly scriptMode: "page" | "story";
}

/**
 * Presenter styles (a talking AI presenter) are shown only when the presenter
 * capability is live: `NEXT_PUBLIC_PRESENTER_LIVE=1` at build time, set in the
 * same deploy that turns the provider on (claims rule 5, `PRESENTER_LIVE`).
 * While it is off the API rejects presenter layouts with `format_locked`, so
 * offering them would only lead to an error.
 */
export function presenterLive(raw: string | undefined = process.env.NEXT_PUBLIC_PRESENTER_LIVE): boolean {
  const value = (raw ?? "").trim().toLowerCase();
  return value === "1" || value === "true";
}

/** Every style, including presenter styles that may be hidden. */
export const ALL_REEL_STYLES: readonly ReelStyle[] = [
  {
    id: "gameplay_split",
    label: "Block-world gameplay",
    blurb: "Your product on top, block-world parkour gameplay below, captions on the seam.",
    hookExample: "POV: you found the tool you kept wishing existed",
    layout: "captions_only",
    backgroundId: "block-runner",
    needsPresenter: false,
    hookFamily: ["pov", "question", "nobody_tells_you"],
    scriptMode: "page",
  },
  {
    id: "meme_hook",
    label: "Meme hook",
    blurb: "A meme-caption opener, written for your product from your page.",
    hookExample: "You met me at a very ___ time in my life",
    layout: "captions_only",
    backgroundId: "block-runner",
    needsPresenter: false,
    hookFamily: ["met_me_at", "nobody_me", "tell_me_without", "wish_i_knew", "day_in_life"],
    scriptMode: "page",
  },
  {
    id: "anime",
    label: "Anime style",
    blurb: "Original AI anime-style scenes about your product, fully narrated.",
    hookExample: "Let me tell you how this started",
    layout: "captions_only",
    backgroundId: "",
    needsPresenter: false,
    hookFamily: ["story", "pov", "question"],
    scriptMode: "page",
  },
  {
    id: "satisfying_split",
    label: "Satisfying split",
    blurb: "Your product on top, a calm satisfying loop below that holds attention.",
    hookExample: "Here is what nobody tells you about launching",
    layout: "captions_only",
    backgroundId: "sand-slice",
    needsPresenter: false,
    hookFamily: ["nobody_tells_you", "question", "pov"],
    scriptMode: "page",
  },
  {
    id: "pov_text",
    label: "POV text",
    blurb: "A big POV line pinned on screen while the story plays out.",
    hookExample: "POV: your ads finally make themselves",
    layout: "captions_only",
    backgroundId: "marble-loop",
    needsPresenter: false,
    hookFamily: ["pov"],
    scriptMode: "page",
  },
  {
    id: "before_after",
    label: "Before / after",
    blurb: "Life before your product on top, after it below.",
    hookExample: "Before: three tools. After: one link",
    layout: "captions_only",
    backgroundId: "",
    needsPresenter: false,
    hookFamily: ["before_after", "wish_i_knew", "story"],
    scriptMode: "page",
  },
  {
    id: "story_gameplay",
    label: "Story time",
    blurb: "A first-person story about your product over parkour gameplay, opened by a story card.",
    hookExample: "I almost quit before I found this",
    layout: "captions_only",
    backgroundId: "block-runner",
    needsPresenter: false,
    hookFamily: ["story", "pov", "wish_i_knew"],
    scriptMode: "story",
  },
  {
    id: "character_story",
    label: "Cartoon narrator",
    blurb: "An original cartoon narrator tells your product's story over gameplay.",
    hookExample: "So this happened to me last week",
    layout: "captions_only",
    backgroundId: "block-runner",
    needsPresenter: false,
    hookFamily: ["story", "question", "pov"],
    scriptMode: "story",
  },
  {
    id: "ugc_avatar",
    label: "UGC presenter",
    blurb: "An AI presenter pitches your product to camera.",
    hookExample: "Is this actually worth it? Honest answer",
    layout: "hook_intro",
    backgroundId: "",
    needsPresenter: true,
    hookFamily: ["pov", "question", "nobody_tells_you"],
    scriptMode: "page",
  },
  {
    id: "greenscreen",
    label: "Green-screen reaction",
    blurb: "An AI presenter reacts in front of your product page.",
    hookExample: "Wait, this does what?",
    layout: "pip",
    backgroundId: "",
    needsPresenter: true,
    hookFamily: ["question", "story", "pov"],
    scriptMode: "page",
  },
];

/** The styles a visitor can pick right now (presenter styles only when live). */
export function visibleStyles(live: boolean = presenterLive()): readonly ReelStyle[] {
  return live ? ALL_REEL_STYLES : ALL_REEL_STYLES.filter((style) => !style.needsPresenter);
}

export const REEL_STYLES: readonly ReelStyle[] = visibleStyles();

const STYLE_IDS = new Set<string>(REEL_STYLES.map((style) => style.id));

export function isStyleId(value: unknown): value is StyleId {
  return typeof value === "string" && STYLE_IDS.has(value);
}

export function findStyle(id: string | null | undefined): ReelStyle | undefined {
  return REEL_STYLES.find((style) => style.id === id);
}

/** The create-box deep link that preselects a style. */
export function styleCreateHref(id: StyleId, query = ""): string {
  const params = new URLSearchParams({ preset: id });
  if (query) params.set("q", query);
  return `/create?${params.toString()}`;
}
