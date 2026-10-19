/**
 * Provider dataset for the `/providers/{slug}` programmatic pages and the
 * knowledge-graph projection in `graph.ts`.
 *
 * Each entry is a capability page. Slugs are unchanged (pages are rewritten,
 * never removed). Copy rules (gtm/policy/CLAIMS-RULES.md): no competitor or
 * denylisted vendor names, and availability is stated honestly: avatar video
 * is not available yet; premium voices, AI video clips, generated music and
 * LoRA training run only while switched on and are paid from premium credits.
 *
 * Structured fields drive the graph:
 *   - `category`        → RELATED provider ↔ provider edges (same category)
 *   - `relatedFeatures` → provider ↔ feature edges (only where truthful)
 */

/** Grouping used to compute RELATED provider ↔ provider edges. */
export type ProviderCategory =
  | "video-generation"
  | "avatar"
  | "voice"
  | "music"
  | "language-model"
  | "training";

/** Human-readable label per category, for prose and grouping headings. */
export const PROVIDER_CATEGORY_LABELS: Readonly<
  Record<ProviderCategory, string>
> = {
  "video-generation": "Video generation",
  avatar: "Avatar video",
  voice: "Voice & speech",
  music: "Music",
  "language-model": "Language model",
  training: "Model training",
};

export interface ProviderFaq {
  readonly question: string;
  readonly answer: string;
}

export interface Provider {
  /** URL segment: `/providers/{slug}`. */
  readonly slug: string;
  /** Display name. */
  readonly name: string;
  /** Primary keyword phrase for metadata. */
  readonly keyword: string;
  readonly category: ProviderCategory;
  /** Neutral, factual description of the provider's own capability. */
  readonly whatItDoes: string;
  /** Honest statement of how Menivor routes to it. */
  readonly howMenivorUses: string;
  /** Feature slugs this provider genuinely powers (→ provider↔feature edges). */
  readonly relatedFeatures: readonly string[];
  /** Page FAQ (also emitted as FAQPage JSON-LD). */
  readonly faqs: readonly ProviderFaq[];
}

export const PROVIDERS: readonly Provider[] = [
  {
    slug: "heygen",
    name: "Avatar video (not available yet)",
    keyword: "avatar video",
    category: "avatar",
    whatItDoes:
      "Avatar video is a generated person speaking your script on camera, timed to the voiceover.",
    howMenivorUses:
      "Avatar video is not available in Menivor yet. Menivor's reels today are voiced and captioned over your footage, a page recording or a moving style scene, with nobody on camera. This page will say so the day avatar video opens.",
    relatedFeatures: [],
    faqs: [
      {
        question: 'Can Menivor make avatar videos today?',
        answer:
          'Not yet. Avatar video is not available. What renders today is a voiced, captioned reel over your own footage or a style scene.',
      },
    ],
  },
  {
    slug: "elevenlabs",
    name: "Premium voices",
    keyword: "premium AI voices",
    category: "voice",
    whatItDoes:
      "Premium voices are studio-quality neural voices, including cloned brand voices, with word-level timing for each line.",
    howMenivorUses:
      "Every reel is narrated by a natural AI voice at no extra cost. Premium voices are an upgrade for a specific sound or your own cloned brand voice. It is a premium capability: it runs only while it is switched on for your account, and it is paid from premium credits, never from standard reel credits.",
    relatedFeatures: ["karaoke-captions"],
    faqs: [
      {
        question: 'Do I need premium voices?',
        answer:
          'No. Every reel includes a natural AI voice and word-by-word captions. Premium voices are optional.',
      },
      {
        question: 'How are premium voices paid for?',
        answer:
          'From premium credits, a separate pack. Standard reel credits never pay for a premium voice.',
      },
    ],
  },
  {
    slug: "kling",
    name: "Kling",
    keyword: "Kling AI video generation",
    category: "video-generation",
    whatItDoes:
      "Kling is a text-to-video and image-to-video model known for coherent motion and cinematic short clips.",
    howMenivorUses:
      "Menivor's AI video clips can be generated with Kling as one of several models. It is a premium capability: it runs only while it is switched on for your account, and it is paid from premium credits, never from standard reel credits. Reels without AI clips use your footage, a page recording or a style scene.",
    relatedFeatures: [],
    faqs: [
      {
        question: 'Can I generate Kling clips in Menivor?',
        answer:
          'Only while AI video clips are switched on for your account, paid from premium credits. Kling is one of the models Menivor can use for them.',
      },
    ],
  },
  {
    slug: "luma",
    name: "Luma Dream Machine",
    keyword: "Luma Dream Machine video",
    category: "video-generation",
    whatItDoes:
      "Luma's Dream Machine generates video from text or an image, with smooth camera motion and realistic scenes.",
    howMenivorUses:
      "Menivor's AI video clips can be generated with Luma Dream Machine as one of several models. It is a premium capability: it runs only while it is switched on for your account, and it is paid from premium credits, never from standard reel credits. Reels without AI clips use your footage, a page recording or a style scene.",
    relatedFeatures: [],
    faqs: [
      {
        question: 'Can I generate Luma Dream Machine clips in Menivor?',
        answer:
          'Only while AI video clips are switched on for your account, paid from premium credits. Luma Dream Machine is one of the models Menivor can use for them.',
      },
    ],
  },
  {
    slug: "minimax",
    name: "MiniMax (Hailuo)",
    keyword: "MiniMax Hailuo video generation",
    category: "video-generation",
    whatItDoes:
      "MiniMax's Hailuo model generates short video from text or an image with strong subject consistency.",
    howMenivorUses:
      "Menivor's AI video clips can be generated with MiniMax (Hailuo) as one of several models. It is a premium capability: it runs only while it is switched on for your account, and it is paid from premium credits, never from standard reel credits. Reels without AI clips use your footage, a page recording or a style scene.",
    relatedFeatures: [],
    faqs: [
      {
        question: 'Can I generate MiniMax (Hailuo) clips in Menivor?',
        answer:
          'Only while AI video clips are switched on for your account, paid from premium credits. MiniMax (Hailuo) is one of the models Menivor can use for them.',
      },
    ],
  },
  {
    slug: "runway",
    name: "Runway",
    keyword: "Runway Gen video generation",
    category: "video-generation",
    whatItDoes:
      "Runway's Gen family generates and edits video from text, images, or existing footage, and is widely used for creative motion work.",
    howMenivorUses:
      "Menivor's AI video clips can be generated with Runway as one of several models. It is a premium capability: it runs only while it is switched on for your account, and it is paid from premium credits, never from standard reel credits. Reels without AI clips use your footage, a page recording or a style scene.",
    relatedFeatures: [],
    faqs: [
      {
        question: 'Can I generate Runway clips in Menivor?',
        answer:
          'Only while AI video clips are switched on for your account, paid from premium credits. Runway is one of the models Menivor can use for them.',
      },
    ],
  },
  {
    slug: "veo",
    name: "Google Veo",
    keyword: "Google Veo video generation",
    category: "video-generation",
    whatItDoes:
      "Veo is Google's text-to-video model, producing high-fidelity clips with coherent motion and prompt adherence.",
    howMenivorUses:
      "Menivor's AI video clips can be generated with Google Veo as one of several models. It is a premium capability: it runs only while it is switched on for your account, and it is paid from premium credits, never from standard reel credits. Reels without AI clips use your footage, a page recording or a style scene.",
    relatedFeatures: [],
    faqs: [
      {
        question: 'Can I generate Google Veo clips in Menivor?',
        answer:
          'Only while AI video clips are switched on for your account, paid from premium credits. Google Veo is one of the models Menivor can use for them.',
      },
    ],
  },
  {
    slug: "wan",
    name: "Wan",
    keyword: "Wan open video model",
    category: "video-generation",
    whatItDoes:
      "Wan is an open video-generation model family that can be run on hosted infrastructure or self-hosted for text-to-video and image-to-video.",
    howMenivorUses:
      "Menivor's AI video clips can be generated with Wan as one of several models. It is a premium capability: it runs only while it is switched on for your account, and it is paid from premium credits, never from standard reel credits. Reels without AI clips use your footage, a page recording or a style scene.",
    relatedFeatures: [],
    faqs: [
      {
        question: 'Can I generate Wan clips in Menivor?',
        answer:
          'Only while AI video clips are switched on for your account, paid from premium credits. Wan is one of the models Menivor can use for them.',
      },
    ],
  },
  {
    slug: "suno",
    name: "Suno",
    keyword: "Suno AI music generation",
    category: "music",
    whatItDoes:
      "Suno generates original music and songs from a text prompt, including vocals and full arrangements.",
    howMenivorUses:
      "Reels can use the built-in background music at no extra cost. Generated music with Suno is an optional premium extra. It is a premium capability: it runs only while it is switched on for your account, and it is paid from premium credits, never from standard reel credits.",
    relatedFeatures: [],
    faqs: [
      {
        question: 'Can Menivor generate music with Suno?',
        answer:
          'Only while generated music is switched on for your account, paid from premium credits. The built-in background music is always available at no extra cost.',
      },
    ],
  },
  {
    slug: "sadtalker",
    name: "Open portrait animation (not available yet)",
    keyword: "open portrait animation model",
    category: "avatar",
    whatItDoes:
      "Open portrait-animation models animate a single still image to follow a supplied audio track.",
    howMenivorUses:
      "Portrait animation is not available in Menivor yet. It belongs to avatar video, which has not opened. Menivor's reels today are voiced and captioned with nobody on camera.",
    relatedFeatures: [],
    faqs: [
      {
        question: 'Can I animate a portrait in Menivor?',
        answer:
          'Not yet. Portrait animation is part of avatar video, which is not available today.',
      },
    ],
  },
  {
    slug: "openrouter",
    name: "Language model routing",
    keyword: "AI script writing",
    category: "language-model",
    whatItDoes:
      "Language model routing sends each writing task to one of several large language models behind a single interface.",
    howMenivorUses:
      "Menivor's hook-first scripts and idea suggestions are written by large language models. If AI writing is unavailable, Menivor still produces a real script from your page with a deterministic writer, and you can always type your own script.",
    relatedFeatures: ["hook-first-script", "spark-idea-engine"],
    faqs: [
      {
        question: "What writes Menivor's scripts?",
        answer:
          'Large language models write the hook-first scripts and idea suggestions, with a deterministic fallback that still turns your page into a real script.',
      },
    ],
  },
  {
    slug: "lora-training",
    name: "LoRA Training",
    keyword: "LoRA fine-tuning for video",
    category: "training",
    whatItDoes:
      "LoRA (Low-Rank Adaptation) fine-tuning trains a lightweight adapter on your own images so a generation model can reproduce a specific subject or style.",
    howMenivorUses:
      "Menivor can train a LoRA adapter for a consistent character or brand style in AI-generated clips. It is a premium capability: it runs only while it is switched on for your account, and it is paid from premium credits, never from standard reel credits.",
    relatedFeatures: [],
    faqs: [
      {
        question: 'Can I train a custom model in Menivor?',
        answer:
          'Only while LoRA training is switched on for your account, paid from premium credits. It is used for a consistent character or style in AI-generated clips.',
      },
    ],
  },
];

const PROVIDER_BY_SLUG: ReadonlyMap<string, Provider> = new Map(
  PROVIDERS.map((provider) => [provider.slug, provider]),
);

/** Resolve a provider by slug, or `undefined` when the slug is unknown. */
export function getProvider(slug: string): Provider | undefined {
  return PROVIDER_BY_SLUG.get(slug);
}

/** Every provider slug — used by generateStaticParams and the sitemap. */
export const PROVIDER_SLUGS: readonly string[] = PROVIDERS.map(
  (provider) => provider.slug,
);
