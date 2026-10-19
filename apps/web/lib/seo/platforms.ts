/**
 * Platform landing-page dataset for `/for/{platform}`.
 *
 * Each entry targets a genuine "AI video for {platform}" search intent and is
 * differentiated by that platform's real format constraints (aspect ratio,
 * length window, safe zones, native-audio behaviour) and how Menivor's pipeline
 * maps onto them. Copy is grounded in what renders today: 1080×1920 export,
 * hook-first script, a natural AI voiceover, word-by-word captions and one-click
 * styles. Direct posting to social accounts is not open yet, so every page says
 * "download the MP4 and post it" (claims rule: describe what ships).
 */

export interface PlatformFaq {
  readonly question: string;
  readonly answer: string;
}

/** A single hard spec fact rendered in the platform's spec table. */
export interface PlatformSpec {
  readonly label: string;
  readonly value: string;
}

export interface Platform {
  /** URL segment: `/for/{slug}`. */
  readonly slug: string;
  /** Platform display name. */
  readonly name: string;
  /** Primary keyword phrase for metadata. */
  readonly keyword: string;
  /** One-sentence lede under the H1. */
  readonly lede: string;
  /** Whether Menivor can publish to this platform directly today (false until publishing opens). */
  readonly directPublish: boolean;
  /** 3 paragraphs of platform-specific body copy. */
  readonly body: readonly string[];
  /** Hard format facts shown as a spec table. */
  readonly specs: readonly PlatformSpec[];
  /** What works on this platform — differentiated bullets. */
  readonly highlights: readonly string[];
  /** "Best for" audience line. */
  readonly bestFor: string;
  /** Template slugs (`/templates/{slug}`) that suit this platform. */
  readonly templates: readonly string[];
  /** Make-type slugs (`/make/{slug}`) relevant here. */
  readonly makeTypes: readonly string[];
  /** Use-case slugs (`/tools/{slug}`) for this platform. */
  readonly useCases: readonly string[];
  readonly faqs: readonly PlatformFaq[];
}

export const PLATFORMS: readonly Platform[] = [
  {
    slug: "tiktok",
    name: "TikTok",
    keyword: "AI video generator for TikTok",
    lede: "Turn a link, a screen recording or a topic into a hook-first, captioned 9:16 TikTok, ready to download and post.",
    directPublish: false,
    body: [
      "TikTok rewards the first three seconds above everything else. Menivor's script step is hook-first by design, so every reel opens on a pattern interrupt rather than a slow intro — and styles like the meme hook and POV text exist purely to win that opening beat.",
      "The whole reel is built native-vertical: a 1080×1920 export, word-by-word karaoke captions burned to the audio so it reads on mute, and a style that looks native to the feed, from a gameplay split to POV text, instead of a repurposed clip.",
      "Because billing is success-only and credits never expire, you can render several hook variations of the same idea and post the ones that land — the exact iteration loop TikTok's algorithm rewards. Download the MP4 and post it from your TikTok app.",
    ],
    specs: [
      { label: "Aspect ratio", value: "9:16 vertical (1080×1920)" },
      { label: "Sweet-spot length", value: "15–34 seconds" },
      { label: "Captions", value: "Burned-in karaoke, timed to the audio" },
      { label: "Posting", value: "Download the MP4 and post it in TikTok" },
    ],
    highlights: [
      "Hook-first scripts built to survive the first three seconds",
      "Native 1080×1920 export, no cropping or letterboxing",
      "Word-by-word karaoke captions for silent autoplay",
      "A finished MP4 you can post the moment it renders",
    ],
    bestFor: "Creators and brands posting daily, iterating on hooks at volume.",
    templates: ["platform-hook-open", "minecraft-reddit-split", "product-demo-ad", "story-time", "countdown-ranking"],
    makeTypes: ["faceless-video", "product-demo", "talking-head", "listicle"],
    useCases: ["faceless-tiktok-video-maker", "tiktok-hook-script-generator", "ugc-ad-for-tiktok", "tiktok-ad-maker"],
    faqs: [
      {
        question: "What size are Menivor's TikTok videos?",
        answer:
          "Every reel renders native 9:16 at 1080×1920, the full-screen vertical format TikTok favors — no cropping, bars, or repurposing from a landscape source.",
      },
      {
        question: "Can I post to TikTok directly from Menivor?",
        answer:
          "Not yet. Direct posting to social accounts is not open; download the finished MP4 and post or schedule it in TikTok yourself.",
      },
      {
        question: "Why are hooks so important on TikTok?",
        answer:
          "TikTok's feed decides in the first seconds whether to keep showing your video. Menivor writes hook-first scripts and puts the hook on screen in the opening seconds, so the first beat carries the video.",
      },
      {
        question: "Do the captions work with the sound off?",
        answer:
          "Yes. Karaoke captions are burned in and timed to the narration word-by-word, so the reel is fully legible on silent autoplay.",
      },
    ],
  },
  {
    slug: "instagram-reels",
    name: "Instagram Reels",
    keyword: "AI video generator for Instagram Reels",
    lede: "Make polished, on-brand vertical Reels from a link or a screen recording, with a voiceover, karaoke captions and a style that fits the feed.",
    directPublish: false,
    body: [
      "Instagram Reels skews more aesthetic than TikTok — clean edits and a consistent look matter. Menivor gives you caption styles and one-click formats (from POV text to before/after) that keep a reel feeling designed rather than auto-generated.",
      "The output is native 9:16 at 1080×1920 with karaoke captions burned in, kept clear of the platform's UI safe zones so the caption text never sits under the like or share buttons. Your own footage or page recording stays the hero of the reel.",
      "Reels rewards saves and shares as much as watch-time, so save-bait formats like before/after transformations fit the surface well. Download the MP4 and post it from Instagram when the reel is ready.",
    ],
    specs: [
      { label: "Aspect ratio", value: "9:16 vertical (1080×1920)" },
      { label: "Sweet-spot length", value: "20–40 seconds" },
      { label: "Safe zones", value: "Captions kept clear of Reels UI overlays" },
      { label: "Posting", value: "Download the MP4 and post it in Instagram" },
    ],
    highlights: [
      "Polished caption styles that keep a consistent brand look",
      "Your real footage up front, with a voice and captions",
      "Save-bait formats (before/after, listicle) built in",
      "A finished MP4 ready to upload to Reels",
    ],
    bestFor: "Brands and creators who want a consistent, designed look on Reels.",
    templates: ["before-after", "get-ready-with-me", "listicle", "testimonial-ad", "quote-motivation"],
    makeTypes: ["product-demo", "listicle", "talking-head", "quote-video"],
    useCases: ["faceless-instagram-reels-maker", "ai-avatar-instagram-reels", "ugc-ad-for-instagram", "instagram-reels-maker"],
    faqs: [
      {
        question: "Are Menivor reels sized correctly for Instagram Reels?",
        answer:
          "Yes — 1080×1920 9:16, the native full-screen Reels format, with captions positioned clear of Instagram's UI overlays.",
      },
      {
        question: "Can I publish to Instagram Reels from Menivor?",
        answer:
          "Not yet. Direct posting is not open; download the MP4 and upload it through Instagram yourself.",
      },
      {
        question: "What formats perform best on Reels?",
        answer:
          "Save-bait and aesthetic formats such as before/after transformations, POV text and satisfying splits. Each is a one-click style in Menivor.",
      },
      {
        question: "Will the captions collide with the Reels buttons?",
        answer:
          "No. Caption placement respects the Reels safe zones so the karaoke text stays readable and never sits under the like, comment, or share controls.",
      },
    ],
  },
  {
    slug: "youtube-shorts",
    name: "YouTube Shorts",
    keyword: "AI video generator for YouTube Shorts",
    lede: "Produce watch-time-optimized 9:16 Shorts from a screen recording and a prompt — narrated, captioned, and ready to publish.",
    directPublish: false,
    body: [
      "YouTube Shorts is a watch-time and completion game, and it can carry slightly longer narratives than TikTok. Menivor's story styles fit Shorts well, with split-screen formats that hold attention to the end.",
      "Every Short exports native 9:16 at 1080×1920 with a natural AI voiceover and karaoke captions timed to the voice. Faceless styles such as story time over gameplay, a cartoon narrator or a satisfying split let you run a Shorts channel without ever appearing on camera.",
      "Shorts often feed subscribers to a long-form channel, so a clear follow line at the end of the script matters. Download the MP4 and upload it to YouTube when you are done.",
    ],
    specs: [
      { label: "Aspect ratio", value: "9:16 vertical (1080×1920)" },
      { label: "Length", value: "Short reels; story styles run longer" },
      { label: "Optimized for", value: "Completion rate and watch-time" },
      { label: "Posting", value: "Download the MP4 and upload it to YouTube" },
    ],
    highlights: [
      "Story styles that hold attention for watch-time",
      "Faceless channel styles: story time, cartoon narrator, splits",
      "Natural AI narration with word-timed karaoke captions",
      "A finished 1080×1920 MP4 ready to upload",
    ],
    bestFor: "Faceless channel operators and creators funneling Shorts to long-form.",
    templates: ["minecraft-reddit-split", "movie-recap", "faceless-facts", "tutorial-howto", "news-brief"],
    makeTypes: ["faceless-video", "talking-head", "listicle"],
    useCases: ["faceless-youtube-shorts-maker", "ai-avatar-youtube-shorts", "youtube-shorts-maker", "faceless-youtube-channel-videos"],
    faqs: [
      {
        question: "How long can a Menivor Short be?",
        answer:
          "Menivor makes short reels sized for the Shorts feed; the length follows the script, and story styles run longer than a quick hook reel.",
      },
      {
        question: "Can I run a faceless YouTube Shorts channel?",
        answer:
          "Yes. Styles like story time over gameplay, the cartoon narrator and the satisfying split run entirely on narration, moving footage and captions, with no camera required.",
      },
      {
        question: "Can I publish to YouTube Shorts from Menivor?",
        answer:
          "Not yet. Direct posting is not open; export the 1080×1920 MP4 and upload it yourself.",
      },
      {
        question: "Why optimize for completion rate?",
        answer:
          "Shorts ranks heavily on how many viewers finish a video. Menivor's split-screen and story styles are structured to hold attention through the end.",
      },
    ],
  },
  {
    slug: "linkedin",
    name: "LinkedIn",
    keyword: "AI video generator for LinkedIn",
    lede: "Turn a product demo or an idea into a credible, captioned vertical video for LinkedIn — authority-first, no cringe.",
    directPublish: false,
    body: [
      "LinkedIn video is a different register: professional, substance-first, and skeptical of hype. Menivor's voiceover reel and before/after styles fit that tone: clear structure, clean captions, and a single takeaway rather than meme energy.",
      "Vertical video performs in the LinkedIn feed, and captions are essential because most of the feed autoplays muted in a work setting. Every reel exports 1080×1920 with karaoke captions burned in, and a natural AI voiceover lets founders and B2B teams publish consistently without filming.",
      "For LinkedIn, Menivor exports the finished 1080×1920 MP4 ready to upload natively from the LinkedIn app or website, where the feed favors native uploads over links. Product demos and thought-leadership explainers are the strongest fits.",
    ],
    specs: [
      { label: "Aspect ratio", value: "9:16 vertical (1080×1920)" },
      { label: "Sweet-spot length", value: "30–60 seconds" },
      { label: "Tone", value: "Authority-first, substance over hype" },
      { label: "Posting", value: "Export MP4 and upload natively to LinkedIn" },
    ],
    highlights: [
      "Authority-first styles: voiceover reel, before/after, POV text",
      "Captions for a muted, professional autoplay feed",
      "A natural AI voiceover for consistent B2B posting without filming",
      "Native-ready 1080×1920 MP4 export",
    ],
    bestFor: "Founders, B2B marketers, and operators building thought-leadership reach.",
    templates: ["talking-head-explainer", "product-demo-ad", "news-brief", "listicle", "tutorial-howto"],
    makeTypes: ["talking-head", "product-demo"],
    useCases: ["saas-marketing-video-maker", "explainer-video-generator", "talking-head-video-generator", "product-demo-to-reel"],
    faqs: [
      {
        question: "Can Menivor post to LinkedIn directly?",
        answer:
          "Not directly. LinkedIn uses an export workflow: Menivor renders the finished 1080×1920 MP4, and you upload it natively in LinkedIn, which the feed favors over external links. Direct posting is not open for any platform yet.",
      },
      {
        question: "What kind of video works on LinkedIn?",
        answer:
          "Authority-first content: product demos, explainers and before/after stories. The tone is substance over hype, which is how Menivor writes those scripts.",
      },
      {
        question: "Do I need captions for LinkedIn?",
        answer:
          "Yes. The professional feed largely autoplays muted, so burned-in karaoke captions are essential for the message to land — and Menivor adds them by default.",
      },
      {
        question: "Can I make LinkedIn videos without filming myself?",
        answer:
          "Yes. Menivor narrates your screen recording or page with a natural AI voice, so B2B teams and founders can publish consistent video without a camera or a studio.",
      },
    ],
  },
];

export function getPlatform(slug: string): Platform | undefined {
  return PLATFORMS.find((platform) => platform.slug === slug);
}

export const PLATFORM_SLUGS: readonly string[] = PLATFORMS.map(
  (platform) => platform.slug,
);

/** Other platforms, for the cross-link mesh. */
export function otherPlatforms(slug: string): readonly Platform[] {
  return PLATFORMS.filter((platform) => platform.slug !== slug);
}
