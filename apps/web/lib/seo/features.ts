/**
 * Feature dataset for the `/features/{slug}` programmatic pages and the
 * knowledge-graph projection in `graph.ts`.
 *
 * Every feature here is described as it stands today (claims rules): avatar
 * video and direct publishing are marked "not available/open yet" rather than
 * promised, and no denylisted vendor or competitor name appears in the copy. Each entry
 * carries enough structured data to (a) render a differentiated hub page and
 * (b) let `graph.ts` compute typed edges deterministically:
 *   - `useCases`             → SOLVES edges (feature → use case)
 *   - `comparableCompetitors`→ HAS_FEATURE edges (competitor → feature), only
 *                              where the research doc genuinely supports a
 *                              comparable capability; left empty (neutral) when
 *                              the doc does not.
 *   - `providers`            → the marketplace providers that power the feature
 *   - `theme`                → RELATED edges (feature ↔ feature by theme)
 */

/** Thematic bucket used to compute RELATED feature ↔ feature edges. */
export type FeatureTheme =
  | "avatar"
  | "captions"
  | "screen-recording"
  | "scripting"
  | "publishing"
  | "growth"
  | "billing";

export interface FeatureFaq {
  readonly question: string;
  readonly answer: string;
}

export interface Feature {
  /** URL segment: `/features/{slug}`. */
  readonly slug: string;
  /** H1 / display name. */
  readonly name: string;
  /** Primary keyword phrase for metadata. */
  readonly keyword: string;
  /** One-sentence lede under the H1. */
  readonly lede: string;
  /** 2–3 paragraphs of genuine, differentiated body copy. */
  readonly body: readonly string[];
  /** Concrete capability bullets. */
  readonly highlights: readonly string[];
  /** "Best for" audience line. */
  readonly bestFor: string;
  /** Thematic bucket (drives RELATED feature ↔ feature edges). */
  readonly theme: FeatureTheme;
  /** Use-case slugs this feature centrally solves (→ SOLVES edges). */
  readonly useCases: readonly string[];
  /**
   * Competitor slugs that truthfully offer a comparable capability, per
   * `docs/menivor.md`. Empty where the doc does not support a claim — we stay
   * neutral rather than asserting a competitor has or lacks a feature.
   */
  readonly comparableCompetitors: readonly string[];
  /** Provider slugs (routing marketplace / core adapters) that power it. */
  readonly providers: readonly string[];
  /** Page-specific FAQ (also emitted as FAQPage JSON-LD). */
  readonly faqs: readonly FeatureFaq[];
}

export const FEATURES: readonly Feature[] = [
  {
    slug: "lip-synced-avatar-presenter",
    name: "Avatar Video (Not Available Yet)",
    keyword: "avatar video maker",
    lede: "Avatar video, a generated person speaking your script on camera, is not available in Menivor yet. Here is what you can make today instead.",
    body: [
      "Avatar video puts a generated person on screen who speaks your script in time with the voiceover. Menivor does not offer it today, and no reel it renders now has a person on camera.",
      "What ships today covers most of the same jobs without anyone on screen: a hook-first script, a natural AI voiceover, word-by-word captions and a style, laid over your screen recording, a recording of your page or a moving scene such as block-world gameplay or a cartoon narrator.",
      "When avatar video opens, this page will say so. Until then, pick a faceless style and your real footage stays the hero of the reel.",
    ],
    highlights: [
      "Not available today, and no reel promises it",
      "A natural AI voiceover instead of a face on camera",
      "Your real footage or page recording as the picture",
      "Faceless styles that run without anyone filming",
    ],
    bestFor: "Creators who want to post without filming, with the options that work today.",
    theme: "avatar",
    useCases: ["ai-avatar-video-generator", "talking-head-video-generator", "faceless-video-generator", "ai-ugc-ad-generator"],
    comparableCompetitors: ["captions", "submagic", "veed"],
    providers: ["heygen", "sadtalker"],
    faqs: [
      {
        question: "Can Menivor make avatar videos today?",
        answer:
          "No. Avatar video is not available yet. Menivor renders voiced, captioned reels over your footage or a style scene.",
      },
      {
        question: "Do I need to film myself?",
        answer:
          "No. Every reel is narrated by a natural AI voice over your footage or a moving style scene, so nobody has to be on camera.",
      },
    ],
  },
  {
    slug: "karaoke-captions",
    name: "Word-by-Word Karaoke Captions",
    keyword: "word-by-word karaoke captions",
    lede: "Captions where each word highlights as it is spoken, burned into the MP4 and timed to the audio, not a drifting auto-subtitle track.",
    body: [
      "Menivor renders karaoke captions and burns them into the video, so the captions are part of the file and display everywhere without a separate subtitle track. Each word highlights as it is spoken, which is one of the strongest retention devices in short-form video.",
      "Timing comes from word-level timestamps of the voiceover itself, used as the single timing source for the render. That is why the captions stay tight to the narration instead of drifting the way auto-generated subtitles often do.",
      "Bundled fonts cover extended Latin glyphs, so Turkish characters like ş, ğ, and ı render correctly out of the box.",
    ],
    highlights: [
      "Word-by-word karaoke highlighting",
      "Burned into the MP4, no separate file",
      "Timed to the voiceover's word-level timestamps",
      "Correct Turkish-glyph rendering",
    ],
    bestFor: "Creators who want captions that actually improve retention.",
    theme: "captions",
    useCases: ["karaoke-caption-generator", "turkish-ai-video-generator"],
    comparableCompetitors: ["submagic"],
    providers: ["elevenlabs"],
    faqs: [
      {
        question: "Are captions burned in or a separate file?",
        answer:
          "They are burned into the video, so they display everywhere without needing a separate subtitle track.",
      },
      {
        question: "Why do the captions stay in sync?",
        answer:
          "They are timed to word-level timestamps from the voiceover itself, so each word lands as it is spoken.",
      },
    ],
  },
  {
    slug: "screen-recording-to-reel",
    name: "Screen Recording to Reel",
    keyword: "screen recording to reel",
    lede: "Drop in a raw screen capture and a prompt; get back a tight, hook-led, narrated 1080×1920 reel: new content, not a trimmed clip.",
    body: [
      "A raw screen recording is rarely postable on its own: it is too long, has no hook, and no narration. Menivor is built to fix that. It scripts the recording, narrates it with a natural AI voice, burns in karaoke captions, and composes everything into a native vertical MP4.",
      "This is what Menivor does that pure clippers do not: it is not cutting an existing long video into moments, it is turning a screen recording plus a prompt into a new reel built around the part that matters.",
      "Because the reel is generated from your actual recording, it shows your product doing the thing, the most convincing possible proof, while the voiceover and captions carry the message.",
    ],
    highlights: [
      "Purpose-built for screen recordings, not long-video clipping",
      "Split-screen and full-frame styles",
      "Voiceover and karaoke captions applied automatically",
      "A 1080×1920 MP4, ready to post",
    ],
    bestFor: "Anyone turning product demos or walkthroughs into reels.",
    theme: "screen-recording",
    useCases: ["screen-recording-to-video", "saas-demo-video-maker", "product-demo-to-reel"],
    comparableCompetitors: [],
    providers: [],
    faqs: [
      {
        question: "How is this different from a clipping tool?",
        answer:
          "Clippers cut an existing long video into short moments. Menivor writes and narrates a new reel from your screen recording and a prompt.",
      },
      {
        question: "What do I need to start?",
        answer:
          "A screen recording of your product or workflow and a short prompt describing the message. Menivor handles the script, voice and captions.",
      },
    ],
  },
  {
    slug: "hook-first-script",
    name: "Hook-First Script (TR / EN)",
    keyword: "hook-first AI script generator",
    lede: "Structured, hook-led scripts written for the first three seconds, in English or Turkish, that flow straight into voice and captions.",
    body: [
      "Menivor's script stage is hook-first by design. A large language model writes structured, hook-led scripts rather than generic paragraphs, in English or Turkish. On a vertical feed the opening line decides everything, so the script is built around it. If AI writing is unavailable, a deterministic writer still turns your page into a real script.",
      "Unlike a standalone script tool, the script does not stop at text: the same hook flows straight into the voiceover and the karaoke captions in a single render. A strong opening line becomes a finished, postable reel in the same pass.",
      "Each run renders three variants with different opening hooks, so you can post the one that fits and learn which openings land.",
    ],
    highlights: [
      "Structured, hook-first scripts in English or Turkish",
      "Flows into voiceover and captions automatically",
      "Three variants with different opening hooks",
      "A real script even when AI writing is unavailable",
    ],
    bestFor: "Creators who live or die by the first three seconds.",
    theme: "scripting",
    useCases: ["tiktok-hook-script-generator", "ai-ugc-ad-generator", "turkish-ai-video-generator"],
    comparableCompetitors: [],
    providers: ["openrouter"],
    faqs: [
      {
        question: "Does it only write scripts?",
        answer:
          "No. The script is the first stage of the pipeline: it flows into the voiceover and karaoke captions to produce a finished reel.",
      },
      {
        question: "Can I generate hooks in Turkish?",
        answer:
          "Yes. Menivor writes hook-first scripts in English or Turkish.",
      },
    ],
  },
  {
    slug: "template-marketplace",
    name: "Template Marketplace",
    keyword: "reel template marketplace",
    lede: "Publish, clone, rate and remix reel templates, so a structure that worked once becomes a starting point for the next reel.",
    body: [
      "Menivor includes a template marketplace where creators publish, clone, rate and remix reel templates. Templates can be ordered by outcomes that creators report on reels that used them, alongside ratings.",
      "Cloning a template gives you a known starting structure for a new reel instead of a blank page.",
      "Because every template is a Menivor pipeline configuration, remixing one still produces a fully generated reel: script, voice and karaoke captions included.",
    ],
    highlights: [
      "Publish, clone, rate and remix templates",
      "Ordered by ratings and reported outcomes",
      "A starting structure instead of a blank page",
      "Every remix renders a complete reel",
    ],
    bestFor: "Creators who want a proven starting point instead of a blank page.",
    theme: "growth",
    useCases: ["ai-ugc-ad-generator"],
    comparableCompetitors: ["submagic", "capcut"],
    providers: [],
    faqs: [
      {
        question: "How are templates ranked?",
        answer:
          "By ratings and by outcomes that creators report on reels that used each template.",
      },
    ],
  },
  {
    slug: "direct-publish",
    name: "Direct Publishing to TikTok, Reels and Shorts (Not Open Yet)",
    keyword: "publish to TikTok Instagram YouTube",
    lede: "Posting a finished reel straight to TikTok, Instagram Reels and YouTube Shorts from Menivor is not open yet. Today you download the MP4 and post it.",
    body: [
      "Direct publishing, where Menivor posts a finished reel to your connected TikTok, Instagram or YouTube account, is built but not open to customers yet. Until it opens, every reel downloads as a 1080×1920 MP4 you post or schedule yourself.",
      "When it opens, you will connect an account once, and you will be able to post immediately or schedule for later without leaving Menivor. Account tokens are stored encrypted and refreshed in the background.",
      "The launch status on the landing page and in the FAQ always lists what is open, so you can check before you plan around it.",
    ],
    highlights: [
      "Not open yet: download the MP4 and post it today",
      "Connect an account once when it opens",
      "Immediate or scheduled posting when it opens",
      "Encrypted account tokens",
    ],
    bestFor: "Creators who want to skip the export-and-upload step once it opens.",
    theme: "publishing",
    useCases: [],
    comparableCompetitors: ["opusclip", "submagic", "quso", "vizard"],
    providers: [],
    faqs: [
      {
        question: "Can I publish to TikTok from Menivor today?",
        answer:
          "Not yet. Download the MP4 and post it yourself. The FAQ's availability answer lists what is open right now.",
      },
    ],
  },
  {
    slug: "spark-idea-engine",
    name: "SPARK Idea Engine",
    keyword: "AI content idea engine",
    lede: "Pull fresh, hook-led reel ideas instead of starting from a blank page.",
    body: [
      "SPARK is Menivor's idea engine. Instead of staring at a blank prompt, you pull hook-led angles for your next reel, then send the one you like straight into the script stage.",
      "Creators can report how their reels did, and those reported outcomes help order the ideas and templates that SPARK surfaces.",
      "It closes the loop between idea and output: an idea in SPARK becomes a finished, voiced and captioned reel through the same pipeline without any tool-switching.",
    ],
    highlights: [
      "Hook-led idea suggestions on tap",
      "Ordered with help from reported outcomes",
      "Sends an idea straight into the script stage",
      "Ideas become finished reels in the same flow",
    ],
    bestFor: "Creators who post often and run out of angles.",
    theme: "scripting",
    useCases: ["tiktok-hook-script-generator"],
    comparableCompetitors: [],
    providers: ["openrouter"],
    faqs: [
      {
        question: "What feeds SPARK's suggestions?",
        answer:
          "Your topic or page, and outcomes that creators report on their reels, which help order the ideas surfaced first.",
      },
    ],
  },
  {
    slug: "success-only-billing",
    name: "Success-Only, Pay-Per-Reel Credits",
    keyword: "pay-per-reel success-only billing",
    lede: "One credit renders one finished reel. Credits are reserved when a render starts, captured only on success, released on failure — and they never expire.",
    body: [
      "Menivor prices every reel, on a monthly plan or a one-time credit pack. When a render starts, its credit cost is reserved on your wallet; when the reel succeeds, the actual cost is captured; if it fails, the hold is released back to you. You are never charged for a render that did not finish.",
      "Pack credits never expire, which makes packs practical for bursty work — testing several hooks for one product, or rendering a batch before a launch. A monthly plan suits steady posting; its included reels reset each period.",
      "The whole flow runs on an integer-microdollar wallet with a cost guard that refunds a cost-capped job once on terminal failure, so the billing stays honest even when a provider misbehaves.",
    ],
    highlights: [
      "One credit = one finished reel",
      "Reserve on start, capture on success, release on failure",
      "Credits never expire",
      "Cost guard refunds cost-capped failures",
    ],
    bestFor: "Anyone testing creative at volume without a subscription to burn down.",
    theme: "billing",
    useCases: [],
    comparableCompetitors: [],
    providers: [],
    faqs: [
      {
        question: "Do I pay for failed renders?",
        answer:
          "No. Credits are reserved when a render starts and only captured when it succeeds; a failed render releases the hold back to you.",
      },
      {
        question: "Do credits expire?",
        answer: "No. Menivor credits never expire.",
      },
    ],
  },
];

const FEATURE_BY_SLUG: ReadonlyMap<string, Feature> = new Map(
  FEATURES.map((feature) => [feature.slug, feature]),
);

/** Resolve a feature by slug, or `undefined` when the slug is unknown. */
export function getFeature(slug: string): Feature | undefined {
  return FEATURE_BY_SLUG.get(slug);
}

/** Every feature slug — used by generateStaticParams and the sitemap. */
export const FEATURE_SLUGS: readonly string[] = FEATURES.map(
  (feature) => feature.slug,
);
