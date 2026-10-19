/*
 * INTERNAL dataset. Not rendered: there is no /templates route, and the
 * graph's dead-link guard drops every link to one (tested in
 * app/(marketing)/tools/seo-copy.test.ts). Before a page renders it, it must
 * pass the copy gate (several formats here describe an avatar presenter,
 * which is not available yet).
 */
/**
 * Reel-template landing-page dataset for `/templates/{slug}`.
 *
 * The 26 entries mirror the real shot-template catalogue served by the
 * templates API (`apps/api/app/domains/templates/presets/*`) — same slugs,
 * genres, layouts, caption styles, camera motion, durations, beat structure
 * (slots), and required inputs. The API is the source of truth for the specs;
 * this module adds the human, search-facing editorial layer (search intent,
 * when-to-use framing, and format-specific FAQs) so each template earns a
 * substantive landing page instead of a thin catalogue stub.
 *
 * Nothing here is invented about the product: the spec facts are copied from
 * the preset definitions, and the "use this template" CTA deep-links into the
 * real compose flow at `/create/templates?template={slug}`.
 */

/** The composition layout a template renders in. */
export type TemplateLayout = "full" | "split" | "pip" | "hook_intro";

/** One narrative beat of a template, taken from its slot plan. */
export interface TemplateBeat {
  readonly role: string;
  readonly label: string;
}

/** A single user-supplied input the template asks for. */
export interface TemplateInputSpec {
  readonly key: string;
  readonly kind: "text" | "clip" | "number" | "choice";
  readonly label: string;
  readonly required: boolean;
}

/** A format-specific Q/A pair, also emitted as FAQPage JSON-LD. */
export interface ReelTemplateFaq {
  readonly question: string;
  readonly answer: string;
}

export interface ReelTemplate {
  /** URL segment and compose deep-link slug: `/templates/{slug}`. */
  readonly slug: string;
  /** Display name, exactly as the catalogue names it. */
  readonly name: string;
  /** Catalogue genre bucket. */
  readonly genre: string;
  /** Human-readable genre/category label for prose. */
  readonly categoryLabel: string;
  /** Primary keyword phrase for metadata. */
  readonly keyword: string;
  /** One-sentence lede under the H1. */
  readonly lede: string;
  /** 2–3 paragraphs of genuine, format-specific body copy. */
  readonly intro: readonly string[];
  /** "Best for" audience line. */
  readonly bestFor: string;
  // ---- Real spec facts (copied from the preset definition) ----
  readonly layout: TemplateLayout;
  readonly captionStyle: string;
  readonly cameraMotion: string;
  readonly effects: readonly string[];
  readonly defaultDurationS: number;
  readonly minDurationS: number;
  readonly maxDurationS: number;
  readonly loopable: boolean;
  /** Ordered narrative beats (the slot plan). */
  readonly beats: readonly TemplateBeat[];
  /** Inputs the template collects from you. */
  readonly inputs: readonly TemplateInputSpec[];
  /** Catalogue tags. */
  readonly tags: readonly string[];
  // ---- Cross-link mesh (all guarded before render) ----
  /** Platform slugs (`/for/{slug}`) this format suits. */
  readonly platforms: readonly string[];
  /** Make-type slugs (`/make/{slug}`) this format belongs to. */
  readonly makeTypes: readonly string[];
  /** Use-case slugs (`/tools/{slug}`) this format serves. */
  readonly useCases: readonly string[];
  /** Format-specific FAQ. */
  readonly faqs: readonly ReelTemplateFaq[];
}

/** Human labels for the layout enum. */
export const TEMPLATE_LAYOUT_LABELS: Readonly<Record<string, string>> = {
  full: "Full-frame",
  split: "Split-screen",
  pip: "Picture-in-picture",
  hook_intro: "Hook intro → demo",
};

/** Human labels for the caption-style enum. */
export const TEMPLATE_CAPTION_LABELS: Readonly<Record<string, string>> = {
  clean_white: "Clean white",
  karaoke_yellow: "Karaoke yellow",
  karaoke_green: "Karaoke green",
  bold_violet: "Bold violet",
};

/** Human labels for the camera-motion enum. */
export const TEMPLATE_MOTION_LABELS: Readonly<Record<string, string>> = {
  none: "Locked frame",
  push_in: "Slow push-in",
  crash_zoom_in: "Crash zoom",
  zoom_punch_in: "Zoom punch",
  whip_pan: "Whip-pan cuts",
  slow_zoom_in: "Slow zoom",
  handheld_follow: "Handheld follow",
  ken_burns: "Ken Burns",
};

/** Format one duration in seconds as a compact `Ns` / `Mm Ss` string. */
export function formatTemplateDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

export const REEL_TEMPLATES: readonly ReelTemplate[] = [
  {
    slug: "product-demo-ad",
    name: "Product Demo Ad (UGC)",
    genre: "marketing",
    categoryLabel: "UGC product ad",
    keyword: "AI product demo ad generator",
    lede: "A founder-style UGC ad where an avatar sells your product over your own screen recording — hook, pain, live demo, proof, CTA.",
    intro: [
      "This is the format a startup uses to make its own marketing. You upload a screen recording of the app plus a one-line pitch; Menivor writes a pattern-interrupt hook, names the pain, then drops the avatar to a corner badge while your recording fills the frame for the live demo — the single most persuasive thing a UGC ad can show.",
      "It runs in the hook-intro layout: a punchy avatar-forward cold open, then a demo section where you narrate the click-path over real footage, followed by a proof beat and one clear call to action. Karaoke-yellow captions keep the message legible with the sound off.",
    ],
    bestFor: "SaaS founders and marketers who want ads that show the product actually working.",
    layout: "hook_intro",
    captionStyle: "karaoke_yellow",
    cameraMotion: "push_in",
    effects: [],
    defaultDurationS: 30,
    minDurationS: 15,
    maxDurationS: 60,
    loopable: false,
    beats: [
      { role: "hook", label: "Pattern-interrupt hook" },
      { role: "setup", label: "The pain" },
      { role: "rising", label: "Live demo" },
      { role: "payoff", label: "Proof / result" },
      { role: "cta", label: "Call to action" },
    ],
    inputs: [
      { key: "promise", kind: "text", label: "One-line pitch / hook", required: true },
      { key: "gameplay_clip", kind: "clip", label: "Screen recording of your app", required: false },
      { key: "cta", kind: "text", label: "Call to action", required: false },
    ],
    tags: ["marketing", "ugc", "ad", "startup", "saas", "demo", "avatar"],
    platforms: ["tiktok", "instagram-reels", "linkedin"],
    makeTypes: ["product-demo", "talking-head"],
    useCases: ["ai-ugc-ad-generator", "saas-demo-video-maker", "product-demo-to-reel"],
    faqs: [
      {
        question: "What do I upload to make a product demo ad?",
        answer:
          "A screen recording of your app or product and a one-line pitch. Menivor writes the hook, script, and CTA, narrates it, and composites a lip-synced avatar over your recording during the demo beat.",
      },
      {
        question: "Why avatar over a screen recording instead of a standalone talking head?",
        answer:
          "Because showing the product in action converts. The hook-intro layout leads with the avatar, then hands the frame to your real footage so viewers watch the thing they'd actually buy — the avatar just carries the narration.",
      },
      {
        question: "Can I test several hooks for the same demo?",
        answer:
          "Yes. Billing is success-only and credits never expire, so you can render multiple hook variations over the same recording and keep the ones that perform.",
      },
    ],
  },
  {
    slug: "testimonial-ad",
    name: "Testimonial Ad (UGC)",
    genre: "marketing",
    categoryLabel: "UGC testimonial ad",
    keyword: "AI testimonial video generator",
    lede: "An authentic customer-review UGC ad that reads like a real review, not a pitch: result-first hook, the objection, the payoff, a soft CTA.",
    intro: [
      "Testimonials convert because they answer the buyer's private doubt out loud. This format opens on the result, admits the objection the customer had before buying, then shows what changed. Use a real customer's words (with their permission), delivered by a clearly AI presenter in a picture-in-picture layout over B-roll of the product in use. Never invent reviews.",
      "Clean white captions and a locked frame keep the tone honest and understated. It is deliberately soft-sell: the close is a low-pressure ask, because a review that hard-pitches stops reading as a review.",
    ],
    bestFor: "Brands and agencies turning happy-customer stories into scalable proof ads.",
    layout: "pip",
    captionStyle: "clean_white",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 25,
    minDurationS: 12,
    maxDurationS: 45,
    loopable: false,
    beats: [
      { role: "hook", label: "Result-first hook" },
      { role: "setup", label: "The objection" },
      { role: "payoff", label: "What changed" },
      { role: "cta", label: "Soft CTA" },
    ],
    inputs: [
      { key: "promise", kind: "text", label: "The result / claim", required: true },
      { key: "broll_clip", kind: "clip", label: "B-roll of the product in use", required: false },
      { key: "cta", kind: "text", label: "Soft call to action", required: false },
    ],
    tags: ["marketing", "ugc", "ad", "testimonial", "review", "proof", "startup"],
    platforms: ["tiktok", "instagram-reels", "linkedin"],
    makeTypes: ["product-demo", "talking-head"],
    useCases: ["testimonial-video-generator", "ugc-ad-for-tiktok", "agency-ugc-video-generator"],
    faqs: [
      {
        question: "How is this different from the product demo ad?",
        answer:
          "The demo ad shows the product working; the testimonial ad tells a customer's before/after story. It leads with the result and admits an objection, so it reads as a peer review rather than a feature tour.",
      },
      {
        question: "Do I need real customer footage?",
        answer:
          "No. You supply the result and objection in one line each; the avatar delivers the review and optional B-roll of the product plays underneath. Real footage makes it stronger but is not required.",
      },
      {
        question: "Why a soft CTA?",
        answer:
          "A testimonial that ends in a hard sell loses the viewer. The soft close keeps the message credible, and the quote itself must come from a real customer.",
      },
    ],
  },
  {
    slug: "before-after",
    name: "Before / After Transformation",
    genre: "marketing",
    categoryLabel: "transformation ad",
    keyword: "before after video maker",
    lede: "A transformation reveal — after-first hook, the before and the struggle, a fast process montage, the satisfying reveal, then a CTA.",
    intro: [
      "Before/after is the highest-converting proof format on short video because the payoff is visible in the first frame. This template opens on the after, rewinds to the before and the struggle, races through the process, and lands the reveal at the emotional peak.",
      "It runs hook-intro with karaoke-yellow captions and a slow push-in for momentum. Give it a one-line transformation and optional footage of the before/after or a screen recording; Menivor scripts and voices the arc and burns the captions to the audio.",
    ],
    bestFor: "Coaches, fitness, beauty, and product brands with a visible result to show.",
    layout: "hook_intro",
    captionStyle: "karaoke_yellow",
    cameraMotion: "push_in",
    effects: [],
    defaultDurationS: 25,
    minDurationS: 12,
    maxDurationS: 45,
    loopable: false,
    beats: [
      { role: "hook", label: "After-first hook" },
      { role: "setup", label: "The before" },
      { role: "rising", label: "The process" },
      { role: "climax", label: "The reveal" },
      { role: "cta", label: "CTA" },
    ],
    inputs: [
      { key: "promise", kind: "text", label: "The transformation in one line", required: true },
      { key: "gameplay_clip", kind: "clip", label: "Your before/after footage", required: false },
      { key: "cta", kind: "text", label: "Call to action", required: false },
    ],
    tags: ["marketing", "transformation", "before-after", "proof", "ugc"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts"],
    makeTypes: ["product-demo"],
    useCases: ["ugc-ad-for-instagram", "fitness-video-generator", "beauty-product-ugc-generator"],
    faqs: [
      {
        question: "Why does the hook show the 'after' first?",
        answer:
          "Leading with the result is what stops the scroll. Viewers watch to find out how you got there, which carries them through the before, the process, and the reveal.",
      },
      {
        question: "What footage works best?",
        answer:
          "Any clip that shows the change — a physique, a room, a dashboard, a redesign, a before/after screen recording. If you have none, Menivor renders the arc over a clean backdrop with captions carrying the story.",
      },
      {
        question: "How long should a before/after reel be?",
        answer:
          "The default is 25 seconds and it flexes from 12 to 45. Keep the process montage tight — the reveal should land before attention drops.",
      },
    ],
  },
  {
    slug: "talking-head-explainer",
    name: "Talking-Head Explainer",
    genre: "talking-head",
    categoryLabel: "talking-head explainer",
    keyword: "AI talking head video generator",
    lede: "A straight-to-camera explainer — hook, frame the question, a clear explanation, the one takeaway, a follow CTA.",
    intro: [
      "The talking-head explainer builds authority: one person, one idea, delivered to camera with total clarity. This format cold-opens with a hook, frames the exact question the viewer has, explains it cleanly, and lands a single takeaway they can repeat.",
      "Upload a selfie clip or bind an AI avatar as the presenter. Karaoke-yellow captions and a slow push-in keep the energy up on a full-frame layout, and the script step keeps you to one idea so the reel stays sharp.",
    ],
    bestFor: "Founders, educators, and creators building a personal brand on expertise.",
    layout: "full",
    captionStyle: "karaoke_yellow",
    cameraMotion: "push_in",
    effects: [],
    defaultDurationS: 40,
    minDurationS: 15,
    maxDurationS: 90,
    loopable: false,
    beats: [
      { role: "hook", label: "Cold-open hook" },
      { role: "setup", label: "Frame the question" },
      { role: "body", label: "The explanation" },
      { role: "payoff", label: "The takeaway" },
      { role: "cta", label: "Follow CTA" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "What are you explaining?", required: true },
      { key: "broll_clip", kind: "clip", label: "Your selfie/talking clip", required: false },
      { key: "cta", kind: "text", label: "Call to action", required: false },
    ],
    tags: ["talking-head", "explainer", "educational", "authority", "avatar", "faceless"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts", "linkedin"],
    makeTypes: ["talking-head"],
    useCases: ["talking-head-video-generator", "ai-avatar-video-generator", "explainer-video-generator"],
    faqs: [
      {
        question: "Can I make a talking-head video without filming myself?",
        answer:
          "Yes. Bind an AI avatar as the presenter and Menivor lip-syncs it to the narration. If you prefer your own face, upload a short selfie clip instead.",
      },
      {
        question: "How long should a talking-head explainer be?",
        answer:
          "The default is 40 seconds, flexing from 15 to 90. Keep it to one idea — the format is strongest when the takeaway is a single repeatable sentence.",
      },
      {
        question: "Does it work in Turkish?",
        answer:
          "Yes. Menivor writes the script and voices the avatar in English or Turkish, with Turkish-glyph captions burned to the audio.",
      },
    ],
  },
  {
    slug: "faceless-facts",
    name: "Faceless Facts (Did You Know)",
    genre: "faceless",
    categoryLabel: "faceless facts reel",
    keyword: "faceless video generator",
    lede: "100% faceless value — a 'did you know' hook, rapid surprising facts, a mind-blown payoff, and a save CTA over a satisfying loop.",
    intro: [
      "This is the classic save-bait faceless format: no camera, no presenter, just a fast stack of surprising facts delivered by TTS narration over a satisfying background loop. It opens on a 'did you know' hook, fires through the facts with bold captions, hits a mind-blown payoff, and asks for the save.",
      "It runs a split layout with bold-violet captions so the text is the star. Give it a topic; Menivor writes the facts, narrates them, and times the captions to the voice — a whole faceless channel can run on this one template.",
    ],
    bestFor: "Faceless channel operators farming saves and follows without showing their face.",
    layout: "split",
    captionStyle: "bold_violet",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 34,
    minDurationS: 12,
    maxDurationS: 60,
    loopable: false,
    beats: [
      { role: "hook", label: "Fact hook" },
      { role: "rising", label: "The facts" },
      { role: "payoff", label: "Mind-blown payoff" },
      { role: "cta", label: "Save CTA" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "Facts topic", required: true },
      { key: "broll_clip", kind: "clip", label: "Background loop (optional)", required: false },
    ],
    tags: ["faceless", "facts", "did-you-know", "value", "save-bait", "tts"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts"],
    makeTypes: ["faceless-video", "listicle"],
    useCases: ["faceless-video-generator", "faceless-tiktok-video-maker", "faceless-youtube-shorts-maker"],
    faqs: [
      {
        question: "Is this really 100% faceless?",
        answer:
          "Yes. There is no presenter and no avatar — TTS narration runs over a satisfying background loop while bold captions carry the facts. Nothing about you appears on screen.",
      },
      {
        question: "Where do the facts come from?",
        answer:
          "You give the topic; Menivor writes the fact list and narrates it. Review and edit the script before rendering so every claim is one you stand behind.",
      },
      {
        question: "Why does it end on a save CTA?",
        answer:
          "Fact reels are saved and re-watched more than they're liked. Asking for the save compounds reach, which is why the format closes on it rather than a follow.",
      },
    ],
  },
  {
    slug: "minecraft-reddit-split",
    name: "Minecraft × Reddit Split",
    genre: "brainrot-split",
    categoryLabel: "gameplay-split story",
    keyword: "reddit story video maker",
    lede: "A narrated Reddit story with karaoke captions up top over looping parkour gameplay below — cold-open the spiciest line first.",
    intro: [
      "The split-screen story format is engineered for completion rate: uninterrupted, hypnotic gameplay at the bottom keeps eyes on screen while the narrated story plays out up top. This template cold-opens the spiciest line, then runs setup, rising action, a climax or twist, and a loop-back CTA.",
      "Paste a Reddit story or script, pick a looping gameplay clip and a narration voice; Menivor narrates it and burns karaoke-yellow captions timed to the audio while the parkour loops underneath.",
    ],
    bestFor: "Faceless story-channel operators chasing watch-time and re-watches.",
    layout: "split",
    captionStyle: "karaoke_yellow",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 45,
    minDurationS: 20,
    maxDurationS: 60,
    loopable: true,
    beats: [
      { role: "hook", label: "Cold-open hook" },
      { role: "setup", label: "Setup" },
      { role: "rising", label: "Rising action" },
      { role: "climax", label: "Climax / twist" },
      { role: "cta", label: "Loop-back / CTA" },
    ],
    inputs: [
      { key: "story", kind: "text", label: "Reddit story / script", required: true },
      { key: "gameplay_clip", kind: "clip", label: "Looping gameplay clip", required: false },
      { key: "subject", kind: "text", label: "Subject / title", required: false },
      { key: "voice_id", kind: "choice", label: "Narration voice", required: false },
    ],
    tags: ["reddit", "gameplay", "faceless", "story"],
    platforms: ["tiktok", "youtube-shorts", "instagram-reels"],
    makeTypes: ["faceless-video"],
    useCases: ["faceless-video-generator", "faceless-tiktok-video-maker", "short-form-video-generator"],
    faqs: [
      {
        question: "Why gameplay under the story?",
        answer:
          "The continuous, low-stakes gameplay gives the eye somewhere to rest so viewers stay for the whole story. It is the mechanic that makes the split format hold attention to the end.",
      },
      {
        question: "Can I bring my own story?",
        answer:
          "Yes. Paste any Reddit story or your own script; Menivor narrates it in the voice you pick and captions it word-by-word. The gameplay loop is a background clip you choose.",
      },
      {
        question: "Should the hook be the first line of the story?",
        answer:
          "No — lead with the spiciest moment. The template cold-opens on the most dramatic line, then loops back so the payoff lands twice.",
      },
    ],
  },
  {
    slug: "split-screen-gameplay-story",
    name: "Gameplay × Story Split",
    genre: "brainrot-split",
    categoryLabel: "gameplay-split narration",
    keyword: "gameplay story video maker",
    lede: "Narration up top over continuous gameplay below — a payoff-first hook, the story body, and a CTA or loop.",
    intro: [
      "A leaner cousin of the Reddit split: three clean beats — payoff-first hook, story body, and a CTA or loop — with your narration mixed above continuous gameplay. It suits any first-person story or explainer you want to ride on hypnotic background motion.",
      "Karaoke-green captions sit over a looping parkour clip. Drop in your story and a gameplay clip; Menivor voices it and keeps the gameplay uninterrupted so watch-time holds.",
    ],
    bestFor: "Creators who want the split-screen retention trick without the Reddit framing.",
    layout: "split",
    captionStyle: "karaoke_green",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 45,
    minDurationS: 20,
    maxDurationS: 60,
    loopable: true,
    beats: [
      { role: "hook", label: "Payoff-first hook" },
      { role: "body", label: "Story body" },
      { role: "cta", label: "CTA / loop" },
    ],
    inputs: [
      { key: "story", kind: "text", label: "Story / narration", required: true },
      { key: "gameplay_clip", kind: "clip", label: "Gameplay clip", required: false },
    ],
    tags: ["gameplay", "story", "faceless", "split"],
    platforms: ["tiktok", "youtube-shorts", "instagram-reels"],
    makeTypes: ["faceless-video"],
    useCases: ["faceless-video-generator", "faceless-youtube-shorts-maker", "short-form-video-generator"],
    faqs: [
      {
        question: "How is this different from the Minecraft × Reddit split?",
        answer:
          "Same retention mechanic, fewer beats and no Reddit framing. Use this one for any narration — a story, a lesson, a rant — that you want to run over background gameplay.",
      },
      {
        question: "What counts as a good gameplay clip?",
        answer:
          "Continuous, loopable motion with no hard cuts — parkour, driving, satisfying runs. The point is a calm visual floor under the narration, so avoid anything that itself demands attention.",
      },
      {
        question: "Is it faceless?",
        answer:
          "Completely. It's narration plus gameplay plus captions — you never appear on camera.",
      },
    ],
  },
  {
    slug: "story-time",
    name: "Story Time (narrated)",
    genre: "story",
    categoryLabel: "narrated story reel",
    keyword: "AI story video generator",
    lede: "A first-person narrated story over a background loop — hook, setup, escalating drama, twist, resolution, and a 'part 2?' CTA.",
    intro: [
      "Story Time is the six-beat drama engine: hook, setup, escalation, the twist, resolution, and a comment-bait close. It's built for completion rate and comments — the twist rewards watching to the end and the CTA invites a 'part 2?' thread.",
      "It runs a split layout with karaoke-yellow captions over a satisfying background loop. Give it your story or a prompt to dramatize; Menivor writes and voices the arc and times captions to the narration.",
    ],
    bestFor: "Storytellers and faceless drama channels optimizing for watch-time and replies.",
    layout: "split",
    captionStyle: "karaoke_yellow",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 45,
    minDurationS: 20,
    maxDurationS: 90,
    loopable: false,
    beats: [
      { role: "hook", label: "Story hook" },
      { role: "setup", label: "Setup" },
      { role: "rising", label: "Escalation" },
      { role: "climax", label: "The twist" },
      { role: "payoff", label: "Resolution" },
      { role: "cta", label: "Comment CTA" },
    ],
    inputs: [
      { key: "story", kind: "text", label: "Your story or a prompt to dramatize", required: true },
      { key: "broll_clip", kind: "clip", label: "Background loop (optional)", required: false },
    ],
    tags: ["story", "storytime", "narration", "faceless", "reddit", "drama"],
    platforms: ["tiktok", "youtube-shorts", "instagram-reels"],
    makeTypes: ["faceless-video"],
    useCases: ["faceless-video-generator", "short-form-video-generator", "faceless-tiktok-video-maker"],
    faqs: [
      {
        question: "What makes the six-beat structure work?",
        answer:
          "Each beat has a job: the hook stops the scroll, escalation builds tension, the twist rewards the watch, and the comment CTA turns viewers into a thread. It's a complete narrative loop, not a list of clips.",
      },
      {
        question: "Can Menivor write the story for me?",
        answer:
          "Yes. Give it a premise or prompt and it dramatizes a full arc; or paste your own story and it narrates and captions it exactly.",
      },
      {
        question: "Why does it end on a comment CTA?",
        answer:
          "Stories that promise more ('part 2?') drive replies and follows. Comments are a strong ranking signal, so the format closes by inviting them.",
      },
    ],
  },
  {
    slug: "listicle",
    name: "Listicle (N things)",
    genre: "edutainment",
    categoryLabel: "listicle reel",
    keyword: "listicle video generator",
    lede: "A rapid-fire numbered list — a '5 things you need' hook, punchy items with bold captions, the best pick, and a save/follow CTA.",
    intro: [
      "The listicle is built for saves and shares: a numbered promise up front ('5 free tools for founders'), fast punchy items, a highlighted best pick, and a save CTA. The number in the hook sets an expectation that pulls viewers to the end.",
      "It runs a split layout with bold-violet captions so each item reads instantly. Give it a topic and Menivor writes the list, narrates it, and paces the items to the captions — ideal for value-content channels.",
    ],
    bestFor: "Value and edutainment creators, marketers, and newsletter-style channels.",
    layout: "split",
    captionStyle: "bold_violet",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 28,
    minDurationS: 12,
    maxDurationS: 50,
    loopable: false,
    beats: [
      { role: "hook", label: "Numbered hook" },
      { role: "rising", label: "The items" },
      { role: "payoff", label: "Best pick" },
      { role: "cta", label: "Save CTA" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "List topic", required: true },
      { key: "broll_clip", kind: "clip", label: "Background footage (optional)", required: false },
    ],
    tags: ["edutainment", "listicle", "tips", "value", "marketing", "faceless"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts", "linkedin"],
    makeTypes: ["listicle", "faceless-video"],
    useCases: ["listicle-video-generator", "faceless-video-generator", "short-form-video-generator"],
    faqs: [
      {
        question: "How many items should a listicle have?",
        answer:
          "Enough to keep pace but few enough to finish inside 30–50 seconds — typically 3 to 7. The number in the hook is a promise, so deliver exactly that many.",
      },
      {
        question: "Is a listicle faceless?",
        answer:
          "It can be. It runs on narration plus captions over background footage, so you never need to appear — though you can add a talking clip if you want a face on it.",
      },
      {
        question: "Why optimize for saves?",
        answer:
          "List content is reference content — people save it to act on later. Saves and shares extend reach beyond the first view, so the CTA asks for the save.",
      },
    ],
  },
  {
    slug: "tutorial-howto",
    name: "Tutorial / How-To",
    genre: "tutorial",
    categoryLabel: "how-to tutorial",
    keyword: "how to video maker",
    lede: "A step-by-step how-to — outcome hook, 'what you need', numbered steps over your screen recording, the finished result, a save CTA.",
    intro: [
      "The tutorial format teaches a repeatable outcome. It opens on the finished result to sell the payoff, lists what's needed, walks the numbered steps over your screen recording, shows the result, and asks for the save. The avatar drops to a corner during the steps so your recording carries the demo.",
      "It runs hook-intro with karaoke-green captions. Give it what you're teaching and a screen recording of the steps; Menivor scripts and narrates the walkthrough and times captions to your voice.",
    ],
    bestFor: "Educators, SaaS teams, and creators teaching a concrete skill or workflow.",
    layout: "hook_intro",
    captionStyle: "karaoke_green",
    cameraMotion: "push_in",
    effects: [],
    defaultDurationS: 50,
    minDurationS: 20,
    maxDurationS: 90,
    loopable: false,
    beats: [
      { role: "hook", label: "Outcome hook" },
      { role: "setup", label: "What you need" },
      { role: "rising", label: "The steps" },
      { role: "payoff", label: "The result" },
      { role: "cta", label: "Save CTA" },
    ],
    inputs: [
      { key: "title", kind: "text", label: "What are you teaching?", required: true },
      { key: "gameplay_clip", kind: "clip", label: "Screen recording of the steps", required: false },
      { key: "cta", kind: "text", label: "Call to action", required: false },
    ],
    tags: ["tutorial", "how-to", "steps", "educational", "screen-recording", "save-bait"],
    platforms: ["youtube-shorts", "tiktok", "instagram-reels", "linkedin"],
    makeTypes: ["product-demo", "talking-head"],
    useCases: ["tutorial-video-generator", "how-to-video-maker", "app-demo-video-maker"],
    faqs: [
      {
        question: "Do I need to record my screen for a tutorial?",
        answer:
          "It's strongly recommended — the steps beat plays over your screen recording so viewers see exactly what to do. Without one, Menivor narrates the steps over captions, but the demo is weaker.",
      },
      {
        question: "Why open on the finished result?",
        answer:
          "Showing the outcome first tells viewers the tutorial is worth their time. It sets the promise, then the steps deliver on it.",
      },
      {
        question: "How long can a tutorial be?",
        answer:
          "Up to 90 seconds, defaulting to 50. Keep each step to one action so the pacing stays tight even on longer workflows.",
      },
    ],
  },
  {
    slug: "greenscreen-react",
    name: "Greenscreen React / Hot Take",
    genre: "commentary",
    categoryLabel: "reaction / hot take",
    keyword: "greenscreen reaction video maker",
    lede: "An avatar reacts over a headline or screenshot — read-the-headline hook, breakdown, a hot take, and a divisive comment-bait CTA.",
    intro: [
      "The greenscreen react is the commentary engine of short video: a presenter stands over a headline, chart, or screenshot and reacts. This template reads the headline as its hook, breaks it down, delivers a genuine hot take, and closes with a divisive prompt built to spark comments.",
      "It runs a picture-in-picture layout with clean white captions so the source material stays readable behind the avatar. Give it your take and the screenshot to react over; Menivor scripts and voices the reaction.",
    ],
    bestFor: "Commentators, news reactors, and creators building an opinionated brand.",
    layout: "pip",
    captionStyle: "clean_white",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 30,
    minDurationS: 12,
    maxDurationS: 55,
    loopable: false,
    beats: [
      { role: "hook", label: "Read-the-headline hook" },
      { role: "body", label: "Breakdown" },
      { role: "payoff", label: "Hot take" },
      { role: "cta", label: "Divisive CTA" },
    ],
    inputs: [
      { key: "angle", kind: "text", label: "The take / what you're reacting to", required: true },
      { key: "broll_clip", kind: "clip", label: "Screenshot / headline / chart", required: false },
      { key: "cta", kind: "text", label: "Comment-bait CTA", required: false },
    ],
    tags: ["commentary", "react", "greenscreen", "hot-take", "news", "faceless"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts", "linkedin"],
    makeTypes: ["talking-head"],
    useCases: ["explainer-video-generator", "ai-avatar-video-generator", "finance-video-generator"],
    faqs: [
      {
        question: "What do I react over?",
        answer:
          "A screenshot, headline, tweet, or chart — anything topical. It plays behind the avatar in the picture-in-picture layout while the reaction narration runs.",
      },
      {
        question: "Do I have to be on camera?",
        answer:
          "No. An AI avatar delivers the reaction, so you can run a commentary channel without ever filming yourself.",
      },
      {
        question: "Why a divisive CTA?",
        answer:
          "Reaction content lives on debate. A prompt that invites disagreement drives the comment volume that pushes the reel in the feed.",
      },
    ],
  },
  {
    slug: "street-interview",
    name: "Street Interview (Q&A)",
    genre: "interview",
    categoryLabel: "street interview",
    keyword: "street interview video maker",
    lede: "A man-on-the-street Q&A — a provocative question hook, rapid-fire answers, the standout answer, and a comment CTA.",
    intro: [
      "The street interview turns one provocative question into a montage of answers. It opens on the question, cuts rapid-fire through responses with whip-pans, spotlights the standout answer, and closes by asking viewers for theirs. The variety of takes is what keeps people watching.",
      "It runs full-frame with karaoke-green captions and whip-pan cuts between answers. Give it the question you're asking and your footage; Menivor structures the montage and captions each answer.",
    ],
    bestFor: "Interview and vox-pop creators, and brands running question-led campaigns.",
    layout: "full",
    captionStyle: "karaoke_green",
    cameraMotion: "whip_pan",
    effects: [],
    defaultDurationS: 38,
    minDurationS: 15,
    maxDurationS: 75,
    loopable: false,
    beats: [
      { role: "hook", label: "Question hook" },
      { role: "rising", label: "The answers" },
      { role: "climax", label: "Standout answer" },
      { role: "cta", label: "Comment CTA" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "The question you're asking", required: true },
      { key: "broll_clip", kind: "clip", label: "Your interview footage", required: false },
    ],
    tags: ["interview", "street", "q-and-a", "vox-pop", "comments", "trend"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts"],
    makeTypes: ["faceless-video"],
    useCases: ["short-form-video-generator", "vertical-video-generator", "explainer-video-generator"],
    faqs: [
      {
        question: "Do I need real interview footage?",
        answer:
          "It's the strongest input — real answers give the format its authenticity. Menivor structures the montage, times the whip-pan cuts, and captions each answer.",
      },
      {
        question: "What makes a good question hook?",
        answer:
          "One that's easy to have an opinion on and slightly provocative. The tension in the question is what makes viewers stay to hear the answers and add their own.",
      },
      {
        question: "How long should it run?",
        answer:
          "Around 38 seconds, up to 75. Keep answers short and varied — the montage pace is the point.",
      },
    ],
  },
  {
    slug: "quote-motivation",
    name: "Motivational Quote",
    genre: "motivation",
    categoryLabel: "motivational reel",
    keyword: "motivational video maker",
    lede: "A cinematic motivation reel — tension hook, a slow narrated build over B-roll, the punch-line quote at the peak, a follow CTA.",
    intro: [
      "Motivational reels work on rhythm: a tension hook, a slow narrated build, and a single punch-line quote that lands at the emotional peak. This template paces that arc with a slow zoom and a light-leak accent so the quote hits when the music and visuals crest.",
      "It runs full-frame with clean white captions. Give it a theme (or the exact quote to land) and optional cinematic B-roll; Menivor writes the build, narrates it, and times the quote to the climax.",
    ],
    bestFor: "Mindset, stoicism, fitness, and discipline pages posting daily motivation.",
    layout: "full",
    captionStyle: "clean_white",
    cameraMotion: "slow_zoom_in",
    effects: ["light_leak"],
    defaultDurationS: 22,
    minDurationS: 8,
    maxDurationS: 40,
    loopable: false,
    beats: [
      { role: "hook", label: "Tension hook" },
      { role: "rising", label: "The build" },
      { role: "climax", label: "The quote" },
      { role: "cta", label: "Follow CTA" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "Theme", required: true },
      { key: "quote", kind: "text", label: "The quote to land (optional)", required: false },
      { key: "broll_clip", kind: "clip", label: "Cinematic B-roll (optional)", required: false },
    ],
    tags: ["motivation", "quote", "mindset", "stoicism", "cinematic", "inspirational"],
    platforms: ["instagram-reels", "tiktok", "youtube-shorts"],
    makeTypes: ["quote-video", "faceless-video"],
    useCases: ["faceless-video-generator", "short-form-video-generator", "vertical-video-generator"],
    faqs: [
      {
        question: "Can I supply my own quote?",
        answer:
          "Yes. Give the exact line to land and Menivor builds the narrated ramp up to it. Leave it blank and it writes a quote to fit your theme.",
      },
      {
        question: "Is it faceless?",
        answer:
          "Yes — it's narration and captions over cinematic B-roll. No presenter appears, which is why it suits high-frequency daily posting.",
      },
      {
        question: "Why keep it short?",
        answer:
          "Motivation lands on impact, not length. The default 22 seconds gives just enough build for the quote to hit before attention fades.",
      },
    ],
  },
  {
    slug: "countdown-ranking",
    name: "Countdown / Ranking",
    genre: "ranking",
    categoryLabel: "countdown / tier-list",
    keyword: "top 10 countdown video maker",
    lede: "A top-N countdown — hook, count DOWN through the ranked picks with bold captions, the #1 reveal with a confetti pop, a 'do you agree?' CTA.",
    intro: [
      "Rankings are debate-bait. This template hooks with the premise ('top 5 productivity apps'), counts down through the picks with bold captions, reveals #1 with a confetti pop, and closes by asking whether viewers agree — which reliably fills the comments.",
      "It runs a split layout with karaoke-yellow captions over a satisfying background loop. Give it the ranking topic; Menivor writes the countdown, narrates it, and paces each pick to the captions.",
    ],
    bestFor: "Edutainment and niche-authority channels farming comments with opinions.",
    layout: "split",
    captionStyle: "karaoke_yellow",
    cameraMotion: "zoom_punch_in",
    effects: ["confetti"],
    defaultDurationS: 33,
    minDurationS: 12,
    maxDurationS: 60,
    loopable: false,
    beats: [
      { role: "hook", label: "Countdown hook" },
      { role: "rising", label: "The countdown" },
      { role: "climax", label: "The #1 reveal" },
      { role: "cta", label: "Debate CTA" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "Ranking topic", required: true },
      { key: "broll_clip", kind: "clip", label: "Background loop (optional)", required: false },
    ],
    tags: ["ranking", "countdown", "tier-list", "top-10", "debate", "comments"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts"],
    makeTypes: ["listicle", "faceless-video"],
    useCases: ["listicle-video-generator", "faceless-video-generator", "short-form-video-generator"],
    faqs: [
      {
        question: "Why count down instead of up?",
        answer:
          "Counting down builds suspense toward the #1 reveal, which is the moment viewers wait for. Counting up gives the payoff away early.",
      },
      {
        question: "How does it drive comments?",
        answer:
          "Any ranking is arguable. The 'do you agree?' close invites viewers to defend their own #1, which is why the format is a reliable comment engine.",
      },
      {
        question: "Is it faceless?",
        answer:
          "Yes. Narration and bold captions run over a background loop — no camera or presenter needed.",
      },
    ],
  },
  {
    slug: "quiz-engagement",
    name: "Quiz / Would-You-Rather",
    genre: "engagement",
    categoryLabel: "quiz / engagement",
    keyword: "quiz video maker",
    lede: "A comment-bait quiz — rapid 'pick one / guess the answer' rounds over a satisfying background, a pause beat, and a loop-back CTA.",
    intro: [
      "This format farms comments and re-watches. It fires quick 'pick one' or 'guess the answer' rounds over a satisfying background, holds a pause beat so viewers commit to an answer, then asks them to comment — and loops so the reel replays seamlessly.",
      "It runs a split layout with karaoke-green captions and is loopable by design. Give it a quiz prompt or would-you-rather theme; Menivor writes the rounds and paces the pause beat.",
    ],
    bestFor: "Engagement-first pages optimizing for comments, saves, and rewatch loops.",
    layout: "split",
    captionStyle: "karaoke_green",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 22,
    minDurationS: 10,
    maxDurationS: 40,
    loopable: true,
    beats: [
      { role: "hook", label: "Challenge hook" },
      { role: "rising", label: "Rounds" },
      { role: "climax", label: "Pause / reveal" },
      { role: "cta", label: "Comment CTA" },
      { role: "loop", label: "Loop seam" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "Quiz topic / prompt", required: true },
      { key: "background_id", kind: "text", label: "Background (optional)", required: false },
    ],
    tags: ["engagement", "quiz", "comment-bait", "faceless", "loop", "would-you-rather"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts"],
    makeTypes: ["faceless-video"],
    useCases: ["faceless-video-generator", "short-form-video-generator", "vertical-video-generator"],
    faqs: [
      {
        question: "How does the pause beat work?",
        answer:
          "The reel holds for a moment before each reveal so viewers commit to an answer in their head — or in the comments. That commitment is what drives replies.",
      },
      {
        question: "Why is it loopable?",
        answer:
          "A seamless loop means the reel replays without a visible cut, so watch-time compounds across rewatches. The loop seam is a dedicated beat.",
      },
      {
        question: "Is it faceless?",
        answer:
          "Yes — the whole quiz runs on captions and narration over a satisfying background. No presenter required.",
      },
    ],
  },
  {
    slug: "news-brief",
    name: "News Brief",
    genre: "news",
    categoryLabel: "news brief",
    keyword: "AI news video generator",
    lede: "A fast, neutral update — headline hook, essential context, what happened, why it matters, and a follow-for-updates CTA.",
    intro: [
      "The news brief delivers a credible, wire-service-style update in under a minute: headline hook, the context you need, what happened, why it matters, and a follow CTA for the next one. The neutral tone and clean captions signal reliability.",
      "It runs full-frame with clean white captions and a locked frame. Give it the story — a headline, link, or summary — and optional B-roll; Menivor writes the brief and narrates it.",
    ],
    bestFor: "News, niche-update, and industry-digest channels posting on a fast cadence.",
    layout: "full",
    captionStyle: "clean_white",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 35,
    minDurationS: 15,
    maxDurationS: 70,
    loopable: false,
    beats: [
      { role: "hook", label: "Headline hook" },
      { role: "setup", label: "Context" },
      { role: "body", label: "What happened" },
      { role: "payoff", label: "Why it matters" },
      { role: "cta", label: "Follow CTA" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "The story (headline or summary)", required: true },
      { key: "broll_clip", kind: "clip", label: "B-roll footage (optional)", required: false },
    ],
    tags: ["news", "update", "brief", "headline", "faceless", "explainer"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts", "linkedin"],
    makeTypes: ["faceless-video", "talking-head"],
    useCases: ["explainer-video-generator", "faceless-video-generator", "short-form-video-generator"],
    faqs: [
      {
        question: "Where does the reporting come from?",
        answer:
          "You supply the story — a headline, link, or summary. Menivor structures and narrates the brief; always review the script so every claim is accurate before rendering.",
      },
      {
        question: "Why the neutral tone?",
        answer:
          "News content earns follows through trust. The clean captions, locked frame, and even delivery read as credible rather than sensational.",
      },
      {
        question: "Can I run a news channel faceless?",
        answer:
          "Yes. The brief runs on narration and captions over B-roll; no anchor on camera is required.",
      },
    ],
  },
  {
    slug: "meme-explainer",
    name: "Meme Explainer",
    genre: "explainer",
    categoryLabel: "meme explainer",
    keyword: "meme explainer video maker",
    lede: "A fast, funny 'let me explain' — crash-zoom hook, quick context, a punchy explanation with a glitch cut, comedic payoff, follow CTA.",
    intro: [
      "The meme explainer breaks down a trend, drama, or concept with comedy timing. It crash-zooms into the hook, gives quick context, delivers the explanation with a glitch cut for punch, lands a comedic payoff, and asks for the follow. High energy is the whole point.",
      "It runs full-frame with bold-violet captions, a crash zoom, and a glitch effect. Give it what you're explaining and an optional reaction clip; Menivor scripts the bit with meme pacing.",
    ],
    bestFor: "Commentary and comedy creators explaining the internet at speed.",
    layout: "full",
    captionStyle: "bold_violet",
    cameraMotion: "crash_zoom_in",
    effects: ["glitch"],
    defaultDurationS: 26,
    minDurationS: 10,
    maxDurationS: 45,
    loopable: false,
    beats: [
      { role: "hook", label: "Crash-zoom hook" },
      { role: "setup", label: "Quick context" },
      { role: "body", label: "The explanation" },
      { role: "payoff", label: "Comedic payoff" },
      { role: "cta", label: "Follow CTA" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "What are you explaining?", required: true },
      { key: "broll_clip", kind: "clip", label: "Reaction/greenscreen clip (optional)", required: false },
    ],
    tags: ["explainer", "meme", "comedy", "commentary", "trend", "fast"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts"],
    makeTypes: ["talking-head", "faceless-video"],
    useCases: ["explainer-video-generator", "short-form-video-generator", "faceless-video-generator"],
    faqs: [
      {
        question: "How is this different from a talking-head explainer?",
        answer:
          "Same job, different energy. The meme explainer uses crash zooms, a glitch cut, and comedic timing for fast trend commentary, where the talking-head explainer is calmer and authority-first.",
      },
      {
        question: "Do I need a reaction clip?",
        answer:
          "No, but a greenscreen or reaction clip adds punch. Without one, the bold captions and glitch cut carry the comedy over narration.",
      },
      {
        question: "How fast should the pacing be?",
        answer:
          "Fast. The format defaults to 26 seconds and lives on momentum — cut anything that slows the joke down.",
      },
    ],
  },
  {
    slug: "platform-hook-open",
    name: "Platform Hook Opener",
    genre: "opener",
    categoryLabel: "hook opener (0–5s)",
    keyword: "video hook generator",
    lede: "A composable 0–5s cold-open — pattern-interrupt, a multimodal hook, the promise, and a loop-back you can prefix onto any reel.",
    intro: [
      "The hook opener is a retention primitive: a 3–6 second cold-open you prepend to any reel to survive the first three seconds. It fires a pattern interrupt, stacks a multimodal hook, states the promise, and sets up a loop-back — the part of a video that decides whether the rest gets watched.",
      "It runs full-frame with karaoke-yellow captions, a whip-pan, and a glitch effect, and is loopable. Give it the promise and an optional SEO keyword phrase; Menivor writes and voices the opener.",
    ],
    bestFor: "Any creator who wants a proven cold-open to raise first-three-second retention.",
    layout: "full",
    captionStyle: "karaoke_yellow",
    cameraMotion: "whip_pan",
    effects: ["glitch"],
    defaultDurationS: 5,
    minDurationS: 3,
    maxDurationS: 6,
    loopable: true,
    beats: [
      { role: "hook", label: "Pattern interrupt" },
      { role: "setup", label: "Multimodal hook" },
      { role: "payoff", label: "Promise / payoff-preview" },
    ],
    inputs: [
      { key: "promise", kind: "text", label: "The promise / payoff", required: true },
      { key: "keyword", kind: "text", label: "SEO keyword phrase", required: false },
    ],
    tags: ["hook", "opener", "prefix", "retention"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts"],
    makeTypes: ["faceless-video", "talking-head"],
    useCases: ["tiktok-hook-script-generator", "short-form-video-generator", "vertical-video-generator"],
    faqs: [
      {
        question: "Is a 5-second opener a full reel?",
        answer:
          "No — it's a cold-open you prefix onto a longer reel. Its whole job is to win the first three seconds so viewers stay for the main content.",
      },
      {
        question: "What's a 'multimodal hook'?",
        answer:
          "A hook that hits on more than one channel at once — a spoken line, an on-screen caption, and a visual pattern interrupt — so it registers even at scroll speed.",
      },
      {
        question: "Can I reuse one opener across videos?",
        answer:
          "Yes. It's built to be composable, and it's loopable, so you can standardize a cold-open across a series.",
      },
    ],
  },
  {
    slug: "day-in-the-life",
    name: "Day in the Life (Vlog)",
    genre: "vlog",
    categoryLabel: "vlog / lifestyle",
    keyword: "day in the life video maker",
    lede: "An aesthetic vlog montage — a hook that sets the day, a quick setup, a montage of moments over narration, and a follow CTA.",
    intro: [
      "The day-in-the-life vlog builds a parasocial connection through aesthetic pacing. It sets the day with a hook, gives a quick setup, then rolls a montage of moments over narration with a handheld feel, and closes on a follow. It's less about events than vibe.",
      "It runs full-frame with clean white captions and a handheld follow motion. Give it whose day and the theme ('day in my life as a founder') plus your footage montage; Menivor writes the narration and paces the cut.",
    ],
    bestFor: "Lifestyle creators, founders building in public, and personal brands.",
    layout: "full",
    captionStyle: "clean_white",
    cameraMotion: "handheld_follow",
    effects: [],
    defaultDurationS: 45,
    minDurationS: 20,
    maxDurationS: 90,
    loopable: false,
    beats: [
      { role: "hook", label: "Day hook" },
      { role: "setup", label: "Setup" },
      { role: "body", label: "The montage" },
      { role: "cta", label: "Follow CTA" },
    ],
    inputs: [
      { key: "title", kind: "text", label: "Whose day + the theme", required: true },
      { key: "broll_clip", kind: "clip", label: "Your footage montage (optional)", required: false },
    ],
    tags: ["vlog", "day-in-the-life", "lifestyle", "montage", "aesthetic", "routine"],
    platforms: ["instagram-reels", "tiktok", "youtube-shorts"],
    makeTypes: ["talking-head"],
    useCases: ["short-form-video-generator", "vertical-video-generator", "coach-content-video-maker"],
    faqs: [
      {
        question: "Do I need to film a whole day?",
        answer:
          "No — a handful of clips is enough. Menivor sequences them into a montage over narration; the vibe matters more than covering every hour.",
      },
      {
        question: "What makes a vlog hook work?",
        answer:
          "A specific, relatable framing of the day ('day in my life as a solo founder') sets an expectation viewers want to see fulfilled.",
      },
      {
        question: "Why the low-key edit?",
        answer:
          "Aesthetic, handheld pacing is what makes the format feel personal. Over-editing breaks the parasocial, in-the-moment feel that earns follows.",
      },
    ],
  },
  {
    slug: "get-ready-with-me",
    name: "Get Ready With Me (GRWM)",
    genre: "lifestyle",
    categoryLabel: "GRWM / lifestyle",
    keyword: "GRWM video maker",
    lede: "A casual GRWM chat — a hook that promises the story, a setup, a chatty body over your routine, and a soft CTA.",
    intro: [
      "GRWM pairs a routine with a story, and the story is the draw. This template hooks by promising the story, sets it up, then runs a chatty body over your getting-ready footage, closing on a soft CTA. The parasocial, talking-to-a-friend tone is what makes it land.",
      "It runs full-frame with karaoke-yellow captions and a handheld follow. Give it the occasion and the story ('GRWM for a first date') plus your routine clip; Menivor writes the chat and times the captions.",
    ],
    bestFor: "Beauty, lifestyle, and personal-brand creators building parasocial reach.",
    layout: "full",
    captionStyle: "karaoke_yellow",
    cameraMotion: "handheld_follow",
    effects: [],
    defaultDurationS: 40,
    minDurationS: 15,
    maxDurationS: 75,
    loopable: false,
    beats: [
      { role: "hook", label: "GRWM hook" },
      { role: "setup", label: "Setup" },
      { role: "body", label: "The chat / routine" },
      { role: "cta", label: "Soft CTA" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "The occasion + story", required: true },
      { key: "broll_clip", kind: "clip", label: "Your routine clip (optional)", required: false },
    ],
    tags: ["lifestyle", "grwm", "vlog", "beauty", "routine", "parasocial"],
    platforms: ["instagram-reels", "tiktok", "youtube-shorts"],
    makeTypes: ["talking-head"],
    useCases: ["beauty-product-ugc-generator", "coach-content-video-maker", "short-form-video-generator"],
    faqs: [
      {
        question: "Is the routine or the story the point?",
        answer:
          "The story. The routine is the backdrop; viewers stay for the chatty narrative you promise in the hook. Pick an occasion with a story worth telling.",
      },
      {
        question: "Can I run GRWM without showing my face?",
        answer:
          "You can bind an avatar, though GRWM is strongest with your own routine footage — the format trades on feeling personal.",
      },
      {
        question: "Why a soft CTA?",
        answer:
          "A hard sell breaks the friend-to-friend tone. A gentle close keeps the parasocial connection that drives repeat views.",
      },
    ],
  },
  {
    slug: "recipe-quick",
    name: "Quick Recipe",
    genre: "food",
    categoryLabel: "recipe / food",
    keyword: "recipe video maker",
    lede: "A fast overhead recipe — finished-dish hook, ingredients, rapid step-by-step over cooking footage, the plated payoff, a save CTA.",
    intro: [
      "Recipe reels are pure save-bait. This template opens on the finished dish, lists ingredients, races through the steps over your cooking footage with bold step captions, reveals the plated result, and asks for the save. Bold captions make each step scannable on mute.",
      "It runs full-frame with bold-violet captions and a Ken Burns motion. Give it the dish ('15-minute garlic butter pasta') and your overhead cooking footage; Menivor structures the steps and captions them.",
    ],
    bestFor: "Food creators, meal-prep pages, and restaurants driving saves and shares.",
    layout: "full",
    captionStyle: "bold_violet",
    cameraMotion: "ken_burns",
    effects: [],
    defaultDurationS: 30,
    minDurationS: 12,
    maxDurationS: 60,
    loopable: false,
    beats: [
      { role: "hook", label: "Finished-dish hook" },
      { role: "setup", label: "Ingredients" },
      { role: "rising", label: "The steps" },
      { role: "payoff", label: "The plate" },
      { role: "cta", label: "Save CTA" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "The dish", required: true },
      { key: "broll_clip", kind: "clip", label: "Your cooking footage (optional)", required: false },
    ],
    tags: ["food", "recipe", "cooking", "save-bait", "how-to", "overhead"],
    platforms: ["instagram-reels", "tiktok", "youtube-shorts"],
    makeTypes: ["listicle", "product-demo"],
    useCases: ["how-to-video-maker", "restaurant-video-maker", "short-form-video-generator"],
    faqs: [
      {
        question: "Do I need overhead cooking footage?",
        answer:
          "It's the ideal input — recipe reels are watched for the process. Menivor times the step captions to your footage; without it, the steps play over captions but the reel is less appetizing.",
      },
      {
        question: "Why open on the finished dish?",
        answer:
          "Showing the plate first sells the payoff and sets the expectation, so viewers stay through the steps to learn how to make it.",
      },
      {
        question: "Why optimize for saves?",
        answer:
          "People save recipes to cook later. Saves and shares are what carry a recipe reel far beyond its first audience, so the CTA asks for the save.",
      },
    ],
  },
  {
    slug: "anime-beat-edit",
    name: "Anime Beat Edit",
    genre: "edit",
    categoryLabel: "beat-synced edit",
    keyword: "beat edit video maker",
    lede: "A beat-synced montage — hardest frame first, story-beat trims, and native trending audio, cut to the music.",
    intro: [
      "The beat edit is a montage cut to music. This template leads with the hardest frame, trims clips to story beats, and syncs cuts to a trending track, with glow and light-leak accents for polish. It's the AMV/edit format built for aesthetic, high-energy loops.",
      "It runs full-frame with clean white captions and a crash zoom. Drop in your source clips and name a trending track; Menivor sequences the montage against the beat.",
    ],
    bestFor: "Edit creators, fandom pages, and brands wanting a stylish beat-synced montage.",
    layout: "full",
    captionStyle: "clean_white",
    cameraMotion: "crash_zoom_in",
    effects: ["glow", "light_leak"],
    defaultDurationS: 20,
    minDurationS: 8,
    maxDurationS: 40,
    loopable: false,
    beats: [
      { role: "hook", label: "Hardest frame" },
      { role: "body", label: "Beat body" },
      { role: "payoff", label: "Final hit" },
    ],
    inputs: [
      { key: "clips", kind: "clip", label: "Source clips", required: true },
      { key: "track", kind: "text", label: "Trending track name", required: false },
    ],
    tags: ["anime", "edit", "beat", "amv"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts"],
    makeTypes: ["faceless-video"],
    useCases: ["short-form-video-generator", "vertical-video-generator", "faceless-video-generator"],
    faqs: [
      {
        question: "What clips work for a beat edit?",
        answer:
          "Short, visually striking shots — anime scenes, product beauty shots, action clips. The edit trims them to the beat, so variety and impact matter more than length.",
      },
      {
        question: "Why lead with the 'hardest frame'?",
        answer:
          "The strongest visual up front stops the scroll and sets the tone. Edits live or die on the first hit.",
      },
      {
        question: "Do I have to pick a track?",
        answer:
          "Naming a trending track helps the pacing and the algorithm favors native audio. If you skip it, Menivor still cuts to a beat structure.",
      },
    ],
  },
  {
    slug: "asmr-satisfying-loop",
    name: "ASMR Satisfying Loop",
    genre: "asmr",
    categoryLabel: "ASMR / satisfying loop",
    keyword: "satisfying loop video maker",
    lede: "One precise repetitive trigger as a frame-perfect ~5s seamless loop, with trigger audio only.",
    intro: [
      "The satisfying loop is the shortest, most hypnotic format: a single precise trigger — a cut, a pour, a peel — as a seamless ~5-second loop that replays without a visible seam. Trigger audio only, no narration; the sound and the loop do all the work, compounding watch-time on every replay.",
      "It runs full-frame with a locked frame and is loopable by design. Drop in your trigger clip and an optional top-center label; Menivor finds the seam and builds the loop.",
    ],
    bestFor: "ASMR and satisfying-content pages maximizing rewatch and watch-time.",
    layout: "full",
    captionStyle: "clean_white",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 5,
    minDurationS: 3,
    maxDurationS: 6,
    loopable: true,
    beats: [
      { role: "hook", label: "Trigger-in hook" },
      { role: "body", label: "Satisfying action" },
      { role: "seam", label: "Loop seam" },
    ],
    inputs: [
      { key: "trigger_clip", kind: "clip", label: "Trigger clip", required: true },
      { key: "label", kind: "text", label: "Optional top-center label", required: false },
    ],
    tags: ["asmr", "satisfying", "loop", "faceless"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts"],
    makeTypes: ["faceless-video"],
    useCases: ["faceless-video-generator", "vertical-video-generator", "short-form-video-generator"],
    faqs: [
      {
        question: "Why keep it to ~5 seconds?",
        answer:
          "A tight, seamless loop replays many times before a viewer scrolls, so a 5-second clip can rack up far more watch-time than its length. The loop seam is a dedicated beat to make the join invisible.",
      },
      {
        question: "Does it use narration?",
        answer:
          "No. ASMR relies on trigger audio only — the satisfying sound is the content. An optional on-screen label is the only text.",
      },
      {
        question: "What makes a good trigger clip?",
        answer:
          "One clean, repetitive action with a crisp sound — kinetic sand cutting, soap carving, a smooth pour. Precision reads as more satisfying than variety.",
      },
    ],
  },
  {
    slug: "brainrot-ai-meme",
    name: "Brainrot AI Meme",
    genre: "meme",
    categoryLabel: "serialized meme",
    keyword: "AI meme video generator",
    lede: "A recurring AI character with a catchphrase pattern-interrupt, escalating nonsense to a signature sound — built to serialize.",
    intro: [
      "Brainrot memes win on serialization: a recurring character, a signature catchphrase, and escalating absurdity that pays off on a known sound. This template opens with an absurd hook, escalates, then pays off or loops back — and it's numbered by episode so viewers follow for the next one.",
      "It runs full-frame with bold-violet captions, a crash zoom, and a glitch effect, and it's loopable. Give it the character name, the bit/catchphrase, and an episode number; Menivor scripts the escalation.",
    ],
    bestFor: "Meme creators building a serialized character with a recurring format.",
    layout: "full",
    captionStyle: "bold_violet",
    cameraMotion: "crash_zoom_in",
    effects: ["glitch"],
    defaultDurationS: 12,
    minDurationS: 8,
    maxDurationS: 15,
    loopable: true,
    beats: [
      { role: "hook", label: "Absurd hook" },
      { role: "escalation", label: "Escalation" },
      { role: "payoff", label: "Payoff / loop-back" },
    ],
    inputs: [
      { key: "character", kind: "text", label: "Recurring character name", required: true },
      { key: "bit", kind: "text", label: "The bit / catchphrase", required: true },
      { key: "episode", kind: "number", label: "Episode number", required: false },
    ],
    tags: ["brainrot", "meme", "serialized", "character"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts"],
    makeTypes: ["faceless-video"],
    useCases: ["faceless-video-generator", "short-form-video-generator", "vertical-video-generator"],
    faqs: [
      {
        question: "Why serialize with an episode number?",
        answer:
          "A recurring character and episode count turns one-off memes into a series people follow for. The number signals there's more, which drives the follow.",
      },
      {
        question: "How long should a brainrot meme be?",
        answer:
          "Very short — 8 to 15 seconds. The escalation has to hit fast, and the loop makes a short clip replay.",
      },
      {
        question: "Is it faceless?",
        answer:
          "Yes. It runs on an AI character, captions, and a signature sound, so nothing about you appears on screen.",
      },
    ],
  },
  {
    slug: "movie-recap",
    name: "Movie Recap (Angle-First)",
    genre: "recap",
    categoryLabel: "film recap",
    keyword: "movie recap video maker",
    lede: "An angle-first narrated recap over clip B-roll — hook in the first 20–30s, the premise and angle, the beats, a verdict, a follow CTA.",
    intro: [
      "The movie recap is a watch-time format: a narrated summary with a specific angle, played over clip B-roll. This template hooks in the first 20–30 seconds, states the premise and your angle, walks the beats, delivers a verdict, and closes on a follow. The angle is what separates a recap from a plot dump.",
      "It runs full-frame with karaoke-yellow (Hormozi-style) captions. Give it the film or show title, a specific angle, and clip B-roll; Menivor writes and narrates the recap.",
    ],
    bestFor: "Film and TV recap channels chasing long watch-time and binge follows.",
    layout: "full",
    captionStyle: "karaoke_yellow",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 60,
    minDurationS: 30,
    maxDurationS: 90,
    loopable: false,
    beats: [
      { role: "hook", label: "Intrigue hook" },
      { role: "setup", label: "Premise + angle" },
      { role: "body", label: "Beats" },
      { role: "payoff", label: "Payoff / verdict" },
      { role: "cta", label: "CTA / follow" },
    ],
    inputs: [
      { key: "title", kind: "text", label: "Film / show title", required: true },
      { key: "angle", kind: "text", label: "Specific angle", required: false },
      { key: "broll_clip", kind: "clip", label: "Clip B-roll", required: false },
    ],
    tags: ["recap", "film", "narration", "faceless"],
    platforms: ["youtube-shorts", "tiktok", "instagram-reels"],
    makeTypes: ["faceless-video"],
    useCases: ["faceless-video-generator", "short-form-video-generator", "faceless-youtube-shorts-maker"],
    faqs: [
      {
        question: "What does 'angle-first' mean?",
        answer:
          "Instead of retelling the plot, you frame the recap around a specific take or question. The angle is the hook that makes your recap different from every other one.",
      },
      {
        question: "Do I supply the clips?",
        answer:
          "You provide the B-roll you have the rights to use; Menivor narrates the recap over it and burns Hormozi-style captions. Always respect the source material's copyright.",
      },
      {
        question: "How long should a recap be?",
        answer:
          "Up to 90 seconds, defaulting to 60 — long enough to cover the beats but tight enough to hold watch-time. Land the hook inside the first 30 seconds.",
      },
    ],
  },
  {
    slug: "fake-ai-podcast",
    name: "Fake AI Podcast",
    genre: "podcast",
    categoryLabel: "AI podcast clip",
    keyword: "AI podcast video generator",
    lede: "A two-host synthetic dialogue — a mid-conversation hook, speaker-cut turns, and bold captions.",
    intro: [
      "The fake-podcast clip mimics the viral 'podcast moment': two hosts mid-conversation, cutting between speakers, with bold captions. This template drops you into the middle of the exchange (the strongest hook), runs the back-and-forth, and lands a button line. It's a fast way to make debate-style content without a studio.",
      "It runs a split layout with bold-violet captions. Give it the topic or a script, pick a render mode, and optionally add B-roll; Menivor voices both hosts and cuts between them.",
    ],
    bestFor: "Faceless commentary and 'podcast clip' channels riding the format's reach.",
    layout: "split",
    captionStyle: "bold_violet",
    cameraMotion: "none",
    effects: [],
    defaultDurationS: 50,
    minDurationS: 30,
    maxDurationS: 60,
    loopable: false,
    beats: [
      { role: "hook", label: "Mid-convo hook" },
      { role: "exchange", label: "Exchange" },
      { role: "button", label: "Button" },
    ],
    inputs: [
      { key: "topic", kind: "text", label: "Podcast topic / script", required: true },
      { key: "mode", kind: "choice", label: "Render mode", required: false },
      { key: "broll_clip", kind: "clip", label: "B-roll (split mode)", required: false },
    ],
    tags: ["podcast", "dialogue", "faceless"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts"],
    makeTypes: ["faceless-video", "talking-head"],
    useCases: ["faceless-video-generator", "short-form-video-generator", "explainer-video-generator"],
    faqs: [
      {
        question: "Why open mid-conversation?",
        answer:
          "The strongest podcast hooks feel like you walked in on a spicy moment. Starting mid-exchange skips the intro and drops viewers straight into the tension.",
      },
      {
        question: "Are both voices AI?",
        answer:
          "Yes. Menivor voices both hosts and cuts between speakers, so you can produce a two-person debate clip without recording anyone.",
      },
      {
        question: "Is it a real podcast?",
        answer:
          "It's a synthetic dialogue in the podcast format. Keep the content honest and clearly styled so it informs or entertains rather than misleads.",
      },
    ],
  },
];

export function getReelTemplate(slug: string): ReelTemplate | undefined {
  return REEL_TEMPLATES.find((template) => template.slug === slug);
}

export const REEL_TEMPLATE_SLUGS: readonly string[] = REEL_TEMPLATES.map(
  (template) => template.slug,
);

/** Peer templates in the same genre first, then fill to `limit` from the rest. */
export function relatedReelTemplates(
  slug: string,
  limit = 4,
): readonly ReelTemplate[] {
  const current = getReelTemplate(slug);
  const others = REEL_TEMPLATES.filter((t) => t.slug !== slug);
  if (!current) return others.slice(0, limit);
  const sameGenre = others.filter((t) => t.genre === current.genre);
  const rest = others.filter((t) => t.genre !== current.genre);
  return [...sameGenre, ...rest].slice(0, limit);
}
