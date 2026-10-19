/**
 * INTERNAL research dataset. Not rendered: there are no /vs, /alternatives or
 * /templates routes, and the graph's dead-link guard drops every link to them
 * (tested in app/(marketing)/tools/seo-copy.test.ts). Competitor names stay
 * here as research only (claims rule 2: no competitor names in public copy);
 * a page that renders this data must pass the copy gate first. Menivor-side
 * lines describe what renders today (no avatar video).
 *
 * Competitor dataset for the /vs and /alternatives programmatic pages.
 *
 * Every fact here is grounded in `docs/menivor.md`. Where the research doc only
 * lists a competitor as an SEO target without detailed claims (CapCut,
 * Descript), the fields are kept neutral and category-level rather than
 * inventing specifics. `menivorEdge` and `whenToPickThem` are honest,
 * capability-based framing — not competitor put-downs.
 */

/** A short/long category bucket used for honest "when to pick which" framing. */
export type CompetitorCategory =
  | "clipper"
  | "avatar-generator"
  | "caption-editor"
  | "faceless-generator"
  | "general-editor"
  | "managed-service"
  | "text-to-video"
  | "ugc-ad-generator";

export interface Competitor {
  /** URL segment: `/vs/{slug}` and `/alternatives/{slug}`. */
  readonly slug: string;
  /** Display name as written by the vendor. */
  readonly name: string;
  /** What the product is, in the vendor's own framing. */
  readonly positioning: string;
  readonly category: CompetitorCategory;
  /** Human-readable category label for prose. */
  readonly categoryLabel: string;
  /** Pricing note (directional — always verify on the vendor's site). */
  readonly pricingNote: string;
  /** Genuine strengths — reasons a creator would legitimately choose them. */
  readonly strengths: readonly string[];
  /** Honest, capability-based reasons a creator might prefer Menivor. */
  readonly menivorEdge: readonly string[];
  /** Honest guidance on when the competitor is the better pick. */
  readonly whenToPickThem: string;
  /** When Menivor is the better pick. */
  readonly whenToPickMenivor: string;
  /** Per-dimension comparison values, keyed to COMPARISON_DIMENSIONS. */
  readonly comparison: Readonly<Record<string, string>>;
}

export const COMPETITORS: readonly Competitor[] = [
  {
    slug: "opusclip",
    name: "OpusClip",
    positioning:
      "an AI clipping tool that turns long videos into short, vertical clips",
    category: "clipper",
    categoryLabel: "long-video clipper",
    pricingNote:
      "Free tier with a watermark and a 3-day export link; Starter around $15/mo and Pro around $29/mo.",
    strengths: [
      "Best-in-class at cutting existing long videos into short clips (ClipAnything, ReframeAnything)",
      "AI virality scoring to prioritise the strongest moments",
      "Large, proven user base and a public API for teams",
      "One-click multi-platform publishing and scheduling",
    ],
    menivorEdge: [
      "Menivor generates net-new UGC from a screen recording and a prompt rather than cutting footage you already have",
      "A natural AI voiceover and captions over your recording, not just captioned clips",
      "Success-only, pay-per-reel credits that never expire instead of a monthly subscription",
    ],
    whenToPickThem:
      "You already have long-form videos, podcasts, or streams and mainly need to auto-cut them into ranked short clips.",
    whenToPickMenivor:
      "You are starting from a screen recording or an idea and want a finished avatar-led UGC reel.",
    comparison: {
      primaryJob: "Clip existing long videos into short vertical clips",
      avatar: "Not an avatar generator; works from existing footage",
      captions: "Auto-captions on extracted clips",
      billing: "Monthly subscription tiers",
      freeTier: "Free tier with watermark and 3-day link",
    },
  },
  {
    slug: "submagic",
    name: "Submagic",
    positioning:
      "a short-form editor focused on fast AI captions, Magic Clips, and avatars",
    category: "caption-editor",
    categoryLabel: "caption + short-form editor",
    pricingNote:
      "Free tier (a few watermarked videos); Starter around $19/mo, Pro around $39/mo, Business+API around $69/mo. Magic Clips is a paid add-on on lower tiers.",
    strengths: [
      "Very fast, polished AI captions across many languages",
      "Magic Clips for turning long videos into shorts",
      "Large template library and a big affiliate-driven creator community",
      "Mature editing extras: auto-zoom, B-roll, translation",
    ],
    menivorEdge: [
      "Karaoke captions and a natural AI voiceover are included on every reel",
      "Screen-recording-to-avatar UGC pipeline rather than a caption/editing layer over existing clips",
      "Pay-per-reel credits with success-only billing instead of tiered subscriptions",
    ],
    whenToPickThem:
      "You want a mature captioning and short-form editing tool with a huge template ecosystem and an established affiliate program.",
    whenToPickMenivor:
      "You want a narrated UGC format and karaoke captions built into a single pay-per-reel pipeline.",
    comparison: {
      primaryJob: "Add captions and edit existing short-form clips fast",
      avatar: "Avatars available; captions/editing are the core",
      captions: "Fast multi-language captions (a core strength)",
      billing: "Subscription tiers; Magic Clips add-on on lower plans",
      freeTier: "Free tier with a few watermarked videos",
    },
  },
  {
    slug: "captions",
    name: "Captions (Mirage)",
    positioning:
      "a generative talking-head and AI-avatar app with digital twins",
    category: "avatar-generator",
    categoryLabel: "AI avatar / talking-head generator",
    pricingNote:
      "Credit-based: a free tier with limited lifetime credits (no generative AI), Basic around $9.99/mo, Max around $24.99/mo, and Scale tiers up to roughly $279.99/mo.",
    strengths: [
      "Leading AI avatars and digital twins (a twin from a single selfie)",
      "AI dubbing across many languages and eye-contact correction",
      "A top-rated, heavily used iOS app",
      "Well-funded research team shipping generative video features quickly",
    ],
    menivorEdge: [
      "Menivor pairs the avatar with your screen recording as product UGC, not just a standalone talking head",
      "Word-by-word karaoke captions burned in and timed to the audio",
      "Pay-per-reel credits that never expire, versus recurring credit subscriptions",
    ],
    whenToPickThem:
      "You want the most polished digital-twin / AI-actor experience and a best-in-class iOS app for talking-head videos.",
    whenToPickMenivor:
      "You want the avatar layered over an actual screen recording as a UGC ad, with karaoke captions.",
    comparison: {
      primaryJob: "Generate talking-head / avatar videos and digital twins",
      avatar: "Core strength: digital twins and AI actors",
      captions: "Auto-captions in many languages",
      billing: "Credit-based monthly subscriptions",
      freeTier: "Limited lifetime credits, no generative AI on free",
    },
  },
  {
    slug: "vizard",
    name: "Vizard",
    positioning:
      "a long-video-to-clips tool that produces many vertical clips in one click",
    category: "clipper",
    categoryLabel: "long-video clipper",
    pricingNote:
      "Free tier (limited credits, watermark, 720p); Creator around $14.50/mo annual and Business around $19.50/mo annual.",
    strengths: [
      "Produces 30+ clips from one long video in a single click",
      "Auto-reframe, captions, and emoji styling",
      "Translation across 100+ languages",
      "Positioned as far cheaper than a human editor",
    ],
    menivorEdge: [
      "Generative, narrated reels rather than reframed clips of existing footage",
      "Karaoke captions and screen-recording layouts built in",
      "Success-only pay-per-reel credits",
    ],
    whenToPickThem:
      "You need high-volume, budget clipping of existing long videos across many languages.",
    whenToPickMenivor:
      "You want to create original avatar-led UGC from a screen recording, not repurpose long videos.",
    comparison: {
      primaryJob: "Turn one long video into many short clips",
      avatar: "Not an avatar generator",
      captions: "Auto-captions with emoji styling",
      billing: "Monthly / annual subscription tiers",
      freeTier: "Free tier with watermark at 720p",
    },
  },
  {
    slug: "veed",
    name: "VEED",
    positioning:
      "a broad, browser-based AI video editor and creation suite",
    category: "general-editor",
    categoryLabel: "general-purpose online editor",
    pricingNote:
      "Free tier (720p, watermark); Creator around $10/mo, Pro around $21/mo, Studio around $35/mo, plus enterprise.",
    strengths: [
      "A full general-purpose editor: text/image-to-video, subtitles, dubbing",
      "Avatars and lip sync, voice clone, and a brand kit",
      "Enterprise APIs and very large scale",
      "One tool for a huge range of video tasks",
    ],
    menivorEdge: [
      "An opinionated, single-purpose pipeline (screen recording → UGC reel) instead of a broad timeline editor",
      "Voiceover and karaoke captions applied by default, not assembled manually",
      "Pay-per-reel credits instead of seat-based subscriptions",
    ],
    whenToPickThem:
      "You want a versatile all-purpose online editor that can do many different video jobs.",
    whenToPickMenivor:
      "You specifically want screen-recording-based UGC reels produced automatically, with an avatar and captions.",
    comparison: {
      primaryJob: "General-purpose online video editing and creation",
      avatar: "Avatars + lip sync available within a broad suite",
      captions: "Subtitles and dubbing tools",
      billing: "Seat-based subscription tiers",
      freeTier: "Free tier with watermark at 720p",
    },
  },
  {
    slug: "quso",
    name: "quso.ai",
    positioning:
      "an all-in-one clip, schedule, and publish suite (formerly vidyo.ai)",
    category: "clipper",
    categoryLabel: "clip + scheduling suite",
    pricingNote:
      "Free tier (limited credits); Lite around $19/mo annual, Essential around $26/mo annual, Growth around $33/mo annual.",
    strengths: [
      "Clipping plus scheduling across six platforms in one place",
      "Subtitles in 50+ languages and social caption/hashtag generation",
      "Brand kit and analytics aimed at replacing several tools",
      "Broad all-in-one workflow",
    ],
    menivorEdge: [
      "Generates original avatar UGC from a screen recording rather than repurposing long videos",
      "Karaoke captions and avatar layouts built in",
      "Success-only, pay-per-reel credits",
    ],
    whenToPickThem:
      "You want a single suite that clips long videos and schedules them across many platforms.",
    whenToPickMenivor:
      "You want to create avatar-led UGC reels from screen recordings, with pay-per-reel pricing.",
    comparison: {
      primaryJob: "Clip long videos and schedule across platforms",
      avatar: "Not an avatar generator",
      captions: "Subtitles in 50+ languages",
      billing: "Monthly / annual subscription tiers",
      freeTier: "Free tier with limited credits",
    },
  },
  {
    slug: "klap",
    name: "Klap",
    positioning:
      "a long-video-to-shorts clipper",
    category: "clipper",
    categoryLabel: "long-video clipper",
    pricingNote:
      "Paid plans from around $14/mo; no free tier.",
    strengths: [
      "Focused, reliable long-video-to-short clipping",
      "Auto-captions and reframing",
      "Simple, lean product",
    ],
    menivorEdge: [
      "Menivor creates original avatar UGC rather than clipping existing videos",
      "A free tier of 3 reels versus no free tier",
      "Karaoke captions and screen-recording layouts",
      "Pay-per-reel credits",
    ],
    whenToPickThem:
      "You want a straightforward, no-frills long-video clipping tool.",
    whenToPickMenivor:
      "You want to generate avatar-led UGC from a screen recording — and to try it free first.",
    comparison: {
      primaryJob: "Clip long videos into short clips",
      avatar: "Not an avatar generator",
      captions: "Auto-captions on clips",
      billing: "Monthly subscription",
      freeTier: "No free tier",
    },
  },
  {
    slug: "crayo",
    name: "Crayo",
    positioning:
      "a tool for faceless, high-volume viral shorts (Reddit-story, fake-iMessage, split-screen gameplay)",
    category: "faceless-generator",
    categoryLabel: "faceless short-video generator",
    pricingNote:
      "Paid plans from around $13/mo, with free utility tools as a lead magnet.",
    strengths: [
      "Purpose-built for faceless / 'brainrot' formats",
      "Reddit-story, fake-text, and split-screen gameplay templates",
      "Free-tool funnels for fast top-of-funnel volume",
    ],
    menivorEdge: [
      "Menivor narrates your own screen recording or page, not a generic stock montage",
      "Karaoke captions timed to a real voiceover",
      "Success-only, pay-per-reel credits",
    ],
    whenToPickThem:
      "You specifically want faceless, high-volume 'brainrot'-style content for entertainment feeds.",
    whenToPickMenivor:
      "You want branded, avatar-led product UGC from a screen recording rather than faceless montages.",
    comparison: {
      primaryJob: "Generate faceless viral shorts",
      avatar: "Faceless formats rather than a presenter avatar",
      captions: "Auto-captions on faceless clips",
      billing: "Monthly subscription",
      freeTier: "Free utility tools only",
    },
  },
  {
    slug: "zebracat",
    name: "Zebracat",
    positioning:
      "an AI video growth agent for faceless marketing video",
    category: "faceless-generator",
    categoryLabel: "faceless marketing-video generator",
    pricingNote:
      "Free tier (watermark); paid from around $19/mo annual up to around $39/mo.",
    strengths: [
      "Faceless marketing video from text or a prompt",
      "Bilingual English/German focus",
      "Marketing-oriented templates and pacing",
    ],
    menivorEdge: [
      "Narrated reels over an actual screen recording, not faceless stock montages",
      "Karaoke captions and multiple screen-recording layouts",
      "Pay-per-reel credits that never expire",
    ],
    whenToPickThem:
      "You want faceless English or German marketing videos generated from text.",
    whenToPickMenivor:
      "You want avatar-led UGC built from a screen recording.",
    comparison: {
      primaryJob: "Generate faceless marketing videos from text",
      avatar: "Faceless format rather than a presenter avatar",
      captions: "Auto-captions",
      billing: "Subscription tiers",
      freeTier: "Free tier with watermark",
    },
  },
  {
    slug: "munch",
    name: "Munch",
    positioning:
      "a done-for-you social marketing service (pivoted from clipping)",
    category: "managed-service",
    categoryLabel: "done-for-you social service",
    pricingNote:
      "Managed service pricing from roughly $48/mo; trial available.",
    strengths: [
      "Hands-off, done-for-you social marketing",
      "Suited to small businesses that don't want to self-serve",
      "Managed content operations",
    ],
    menivorEdge: [
      "A self-serve tool you control, not a done-for-you service",
      "Avatar-led UGC from your own screen recording, rendered in minutes",
      "Pay-per-reel pricing",
      "A free tier to try before you commit",
    ],
    whenToPickThem:
      "You want an agency-style, done-for-you social presence and prefer to outsource production.",
    whenToPickMenivor:
      "You want to self-serve avatar UGC reels quickly and cheaply.",
    comparison: {
      primaryJob: "Done-for-you social marketing service",
      avatar: "Service-led rather than a self-serve avatar tool",
      captions: "Handled as part of the service",
      billing: "Managed service subscription",
      freeTier: "Trial rather than a free tier",
    },
  },
  {
    slug: "capcut",
    name: "CapCut",
    positioning:
      "a popular, free, all-purpose manual video editor",
    category: "general-editor",
    categoryLabel: "manual video editor",
    pricingNote:
      "Free to use with an optional Pro tier.",
    strengths: [
      "Powerful, hands-on manual editing timeline",
      "Free to start with a very large user base",
      "Huge library of effects, transitions, and templates",
    ],
    menivorEdge: [
      "An automated pipeline (script → voice → avatar → captions) instead of manual timeline editing",
      "A natural AI voiceover generated for you (avatar video is not available yet)",
      "Success-only, pay-per-reel credits for finished renders",
    ],
    whenToPickThem:
      "You enjoy hands-on manual editing and want granular control over every cut.",
    whenToPickMenivor:
      "You want a finished avatar-led UGC reel produced automatically instead of editing it yourself.",
    comparison: {
      primaryJob: "Manual, hands-on video editing",
      avatar: "No generative avatar presenter",
      captions: "Manual / auto-caption tools",
      billing: "Free with optional Pro subscription",
      freeTier: "Free to use",
    },
  },
  {
    slug: "descript",
    name: "Descript",
    positioning:
      "a text-based video and podcast editor",
    category: "general-editor",
    categoryLabel: "text-based editor",
    pricingNote:
      "Free tier available with paid plans for more features.",
    strengths: [
      "Edit video and audio by editing the transcript",
      "Strong transcription and podcast workflows",
      "Voice/overdub and screen-recording capture",
    ],
    menivorEdge: [
      "Generates original avatar-led UGC rather than editing existing recordings",
      "Karaoke captions and screen-recording layouts applied automatically",
      "Pay-per-reel credits that never expire",
    ],
    whenToPickThem:
      "You want text-based editing of podcasts and long-form video with strong transcription.",
    whenToPickMenivor:
      "You want to generate short avatar-led UGC reels from a screen recording.",
    comparison: {
      primaryJob: "Text-based editing of video and podcasts",
      avatar: "No generative presenter avatar",
      captions: "Transcript-driven captions",
      billing: "Free tier with paid plans",
      freeTier: "Free tier available",
    },
  },
  {
    slug: "heygen",
    name: "HeyGen",
    positioning:
      "a leading AI avatar and video platform for talking-head videos and digital twins",
    category: "avatar-generator",
    categoryLabel: "AI avatar / talking-head platform",
    pricingNote:
      "Free tier with limited credits and a watermark; Creator around $29/mo and Team/Business tiers higher. Always verify current pricing on heygen.com.",
    strengths: [
      "Best-in-class studio avatars and custom digital twins",
      "Large library of stock avatars and 175+ languages of AI voices",
      "Interactive avatars, translation, and an API for teams",
      "Very polished output favoured by enterprise training and marketing teams",
    ],
    menivorEdge: [
      "Menivor composites a HeyGen-style avatar over your own screen recording as product UGC, not a standalone talking head on a studio background",
      "Word-by-word karaoke captions are burned in and timed to the voiceover on every reel",
      "Success-only, pay-per-reel credits that never expire instead of a monthly avatar subscription",
    ],
    whenToPickThem:
      "You want the most powerful standalone avatar studio, custom digital twins, or enterprise avatar/translation features at scale.",
    whenToPickMenivor:
      "You want an avatar layered over an actual screen recording as a finished UGC reel — hook script and karaoke captions included.",
    comparison: {
      primaryJob: "Generate talking-head avatar videos and digital twins",
      avatar: "Core strength: studio avatars and custom digital twins",
      captions: "Captions/subtitles available; not word-by-word karaoke by default",
      billing: "Monthly / credit subscription tiers",
      freeTier: "Free tier with limited credits and watermark",
    },
  },
  {
    slug: "synthesia",
    name: "Synthesia",
    positioning:
      "an enterprise AI video platform for avatar-led training and corporate videos",
    category: "avatar-generator",
    categoryLabel: "enterprise avatar video platform",
    pricingNote:
      "Free plan with a few minutes of video; Starter around $18/mo (annual) and Creator/Enterprise tiers higher. Verify on synthesia.io.",
    strengths: [
      "230+ studio avatars and 140+ languages for corporate video",
      "Template-driven workflow suited to L&D, HR, and internal comms",
      "Strong governance, brand kits, and enterprise security",
      "Consistent, professional output at scale",
    ],
    menivorEdge: [
      "Menivor targets short-form UGC reels for social, not slide-style corporate training videos",
      "The avatar sits over your real screen recording, so a reel reads as creator content rather than a narrated deck",
      "Hook-first scripts, karaoke captions, and native 9:16 export built for TikTok, Reels, and Shorts",
      "Pay-per-reel credits instead of seat-based enterprise plans",
    ],
    whenToPickThem:
      "You produce corporate training, onboarding, or explainer videos at enterprise scale and need governance and many languages.",
    whenToPickMenivor:
      "You want punchy, feed-native UGC reels from a screen recording, with a hook and karaoke captions.",
    comparison: {
      primaryJob: "Generate avatar-led training and corporate videos",
      avatar: "Studio avatars for talking-head corporate video",
      captions: "Subtitles available; not word-by-word karaoke",
      billing: "Seat / subscription tiers",
      freeTier: "Free plan with limited minutes",
    },
  },
  {
    slug: "runway",
    name: "Runway",
    positioning:
      "a generative AI video model and creative suite (Gen-3/Gen-4) for text- and image-to-video",
    category: "text-to-video",
    categoryLabel: "generative text-to-video model",
    pricingNote:
      "Free tier with limited credits; Standard around $12/mo and Pro/Unlimited tiers higher. Verify on runwayml.com.",
    strengths: [
      "State-of-the-art generative video from text and image prompts",
      "Cinematic motion, camera control, and video-to-video restyling",
      "A deep creative toolkit favoured by filmmakers and artists",
      "Rapidly improving model quality",
    ],
    menivorEdge: [
      "Menivor produces a complete, postable UGC reel — script, voiceover, avatar, captions — not raw generated clips you still have to assemble",
      "Built around your real screen recording as product proof, rather than synthetic B-roll",
      "Karaoke captions and 9:16 export applied automatically",
      "Pay-per-reel credits",
    ],
    whenToPickThem:
      "You want cutting-edge generative B-roll or cinematic AI clips and are comfortable assembling them into a final edit.",
    whenToPickMenivor:
      "You want a finished avatar-led UGC reel from a screen recording, not generative clips to edit together.",
    comparison: {
      primaryJob: "Generate video clips from text and image prompts",
      avatar: "Not a talking-head avatar tool",
      captions: "No built-in karaoke captions pipeline",
      billing: "Credit / subscription tiers",
      freeTier: "Free tier with limited credits",
    },
  },
  {
    slug: "pika",
    name: "Pika",
    positioning:
      "a generative AI video app for short, stylised text- and image-to-video clips",
    category: "text-to-video",
    categoryLabel: "generative text-to-video app",
    pricingNote:
      "Free tier with limited credits; paid plans from around $10/mo. Verify on pika.art.",
    strengths: [
      "Fast, playful generative clips with fun effects (Pikaffects)",
      "Easy image-to-video and creative transformations",
      "Strong community and social-native output",
      "Low barrier to entry for short creative clips",
    ],
    menivorEdge: [
      "Menivor delivers a full UGC reel with a scripted hook, narration, avatar, and captions — not a standalone generative clip",
      "Uses your real screen recording as the core footage for product credibility",
      "Karaoke captions and native vertical export are built in",
      "Pay-per-reel credits",
    ],
    whenToPickThem:
      "You want quick, fun generative clips and creative effects for experimentation.",
    whenToPickMenivor:
      "You want a structured, avatar-led product reel that is ready to post.",
    comparison: {
      primaryJob: "Generate short stylised clips from prompts",
      avatar: "Not a talking-head avatar tool",
      captions: "No built-in karaoke captions pipeline",
      billing: "Credit / subscription tiers",
      freeTier: "Free tier with limited credits",
    },
  },
  {
    slug: "kling",
    name: "Kling AI",
    positioning:
      "a generative video model (by Kuaishou) known for realistic motion and longer clips",
    category: "text-to-video",
    categoryLabel: "generative text-to-video model",
    pricingNote:
      "Free daily credits; paid plans vary by region and credit pack. Verify on the official Kling site.",
    strengths: [
      "Highly realistic motion and physics in generated clips",
      "Longer clip durations than many rivals",
      "Strong image-to-video quality",
      "Competitive free daily credit allowance",
    ],
    menivorEdge: [
      "Menivor outputs a finished UGC reel — hook, voice, avatar, captions — instead of a raw generated clip to edit",
      "Anchored to your real screen recording rather than fully synthetic footage",
      "Karaoke captions and 9:16 export applied automatically",
      "Pay-per-reel credits",
    ],
    whenToPickThem:
      "You want the most realistic generative motion for standalone AI clips.",
    whenToPickMenivor:
      "You want a ready-to-post avatar-led reel built from your product recording.",
    comparison: {
      primaryJob: "Generate realistic video clips from prompts",
      avatar: "Not a talking-head avatar tool",
      captions: "No built-in karaoke captions pipeline",
      billing: "Credit-based plans",
      freeTier: "Free daily credits",
    },
  },
  {
    slug: "sora",
    name: "Sora",
    positioning:
      "OpenAI's text-to-video model for generating high-fidelity synthetic clips",
    category: "text-to-video",
    categoryLabel: "generative text-to-video model",
    pricingNote:
      "Available through ChatGPT plans (Plus/Pro); availability and limits vary. Verify on openai.com.",
    strengths: [
      "High-fidelity, coherent generative video from text prompts",
      "Backed by OpenAI's research and ecosystem",
      "Strong prompt understanding and scene composition",
      "Useful for concept and B-roll generation",
    ],
    menivorEdge: [
      "Menivor assembles a complete reel (script, voiceover, karaoke captions), not standalone generated footage",
      "Built on your actual screen recording, so the reel shows a real product",
      "Automatic 9:16 export and burned-in captions",
      "Success-only, pay-per-reel credits",
    ],
    whenToPickThem:
      "You want top-tier generative clips for concepting or B-roll and will edit them into a final video.",
    whenToPickMenivor:
      "You want a finished, avatar-led product reel from a screen recording rather than raw synthetic clips.",
    comparison: {
      primaryJob: "Generate synthetic video clips from text",
      avatar: "Not a talking-head avatar tool",
      captions: "No built-in karaoke captions pipeline",
      billing: "Bundled into ChatGPT plans",
      freeTier: "No standalone free tier",
    },
  },
  {
    slug: "google-veo",
    name: "Google Veo",
    positioning:
      "Google's generative video model for high-quality text- and image-to-video (in Gemini/Flow)",
    category: "text-to-video",
    categoryLabel: "generative text-to-video model",
    pricingNote:
      "Offered through Google's Gemini and Flow products; access and limits depend on the plan. Verify on Google's site.",
    strengths: [
      "High-quality generative video with strong prompt adherence",
      "Native audio generation in newer versions",
      "Backed by Google's model and infrastructure",
      "Integrated into Google's creative tooling",
    ],
    menivorEdge: [
      "Menivor produces a postable UGC reel end-to-end, not generative clips you assemble yourself",
      "Centred on your real screen recording for authentic product proof",
      "Karaoke captions and vertical export built in",
      "Pay-per-reel credits",
    ],
    whenToPickThem:
      "You want Google's generative video quality for standalone clips inside its ecosystem.",
    whenToPickMenivor:
      "You want a complete avatar-led reel from a screen recording, ready to post.",
    comparison: {
      primaryJob: "Generate video clips from text and images",
      avatar: "Not a talking-head avatar tool",
      captions: "No built-in karaoke captions pipeline",
      billing: "Bundled into Google plans",
      freeTier: "Limited access via free Gemini tiers",
    },
  },
  {
    slug: "invideo",
    name: "InVideo AI",
    positioning:
      "a prompt-to-video generator that assembles full videos from a single text prompt",
    category: "general-editor",
    categoryLabel: "prompt-to-video generator",
    pricingNote:
      "Free tier with watermark and weekly limits; paid plans from around $20/mo. Verify on invideo.io.",
    strengths: [
      "Generate a full video with stock footage, voiceover, and captions from one prompt",
      "Huge stock media library and template selection",
      "Edit the result with plain-text commands",
      "Broad, general-purpose use for many video types",
    ],
    menivorEdge: [
      "Menivor builds the reel from your own screen recording, not stock footage, so it shows your real product",
      "A natural AI voiceover narrates over that footage",
      "Word-by-word karaoke captions timed to the voiceover",
      "Pay-per-reel credits instead of subscription tiers",
    ],
    whenToPickThem:
      "You want to generate broad, stock-footage-based videos from a text prompt across many use cases.",
    whenToPickMenivor:
      "You specifically want avatar-led product UGC from a screen recording, with karaoke captions.",
    comparison: {
      primaryJob: "Generate stock-based videos from a text prompt",
      avatar: "Avatars/voices available within a broad suite",
      captions: "Auto-captions available",
      billing: "Subscription tiers",
      freeTier: "Free tier with watermark and weekly limits",
    },
  },
  {
    slug: "pictory",
    name: "Pictory",
    positioning:
      "a script- and article-to-video tool that turns text into narrated stock-footage videos",
    category: "faceless-generator",
    categoryLabel: "text-to-video / faceless generator",
    pricingNote:
      "Free trial; paid plans from around $19/mo. Verify on pictory.ai.",
    strengths: [
      "Turn blog posts or scripts into narrated videos automatically",
      "Large stock library, auto-captions, and text-based editing",
      "Good for repurposing written content at volume",
      "Straightforward, approachable workflow",
    ],
    menivorEdge: [
      "Menivor generates avatar-led UGC from a screen recording, not stock-footage slideshows from an article",
      "A natural AI voiceover and word-by-word karaoke captions on every reel",
      "Native 9:16 UGC format built for TikTok, Reels, and Shorts",
      "Success-only, pay-per-reel credits",
    ],
    whenToPickThem:
      "You want to convert articles or scripts into narrated stock-footage videos at volume.",
    whenToPickMenivor:
      "You want avatar-led product UGC from a screen recording rather than text-to-stock slideshows.",
    comparison: {
      primaryJob: "Turn scripts/articles into narrated stock videos",
      avatar: "No lip-synced presenter avatar as the core",
      captions: "Auto-captions available",
      billing: "Subscription tiers",
      freeTier: "Free trial rather than a standing free tier",
    },
  },
  {
    slug: "arcads",
    name: "Arcads",
    positioning:
      "an AI UGC ad generator that turns scripts into videos with realistic AI actors",
    category: "ugc-ad-generator",
    categoryLabel: "AI UGC ad generator",
    pricingNote:
      "Paid plans from around $110/mo; no free tier. Verify on arcads.ai.",
    strengths: [
      "Large library of realistic AI actors for UGC-style ads",
      "Fast script-to-ad generation aimed at performance marketers",
      "Multiple actors and variations for ad testing",
      "Purpose-built for paid-social creative",
    ],
    menivorEdge: [
      "Menivor narrates your real screen recording, so the ad shows your actual product in use",
      "A free tier of 3 reels versus no free tier",
      "Word-by-word karaoke captions built into every reel",
      "Pay-per-reel credits",
    ],
    whenToPickThem:
      "You want a big roster of AI actors reading scripts for high-volume paid-social ad testing.",
    whenToPickMenivor:
      "You want a voiceover over your real product footage as screen-recording-based UGC, with captions, and to try it free.",
    comparison: {
      primaryJob: "Generate UGC-style ads from scripts with AI actors",
      avatar: "AI actors reading to camera",
      captions: "Captions available; not the core focus",
      billing: "Higher-priced monthly subscriptions",
      freeTier: "No free tier",
    },
  },
  {
    slug: "creatify",
    name: "Creatify",
    positioning:
      "an AI UGC video ad platform that generates ads from a product URL",
    category: "ugc-ad-generator",
    categoryLabel: "AI UGC ad generator",
    pricingNote:
      "Free trial credits; paid plans from around $33/mo (annual). Verify on creatify.ai.",
    strengths: [
      "Generate product ads directly from a URL or product link",
      "Library of AI avatars/actors and ad templates",
      "Batch ad generation and a 'Batch Mode' for volume",
      "Aimed squarely at e-commerce performance ads",
    ],
    menivorEdge: [
      "Menivor uses your own screen recording as the footage, so the ad demonstrates the real product rather than pulling from a URL scrape",
      "A natural AI voiceover over your recording plus karaoke captions on every reel",
      "Success-only, pay-per-reel credits that never expire",
    ],
    whenToPickThem:
      "You run e-commerce ads and want to spin up many product-ad variations from a URL quickly.",
    whenToPickMenivor:
      "You want screen-recording-based UGC that shows your actual app or product, with karaoke captions.",
    comparison: {
      primaryJob: "Generate e-commerce UGC ads from a product URL",
      avatar: "AI avatars/actors for ads",
      captions: "Captions available",
      billing: "Subscription tiers",
      freeTier: "Free trial credits",
    },
  },
  {
    slug: "d-id",
    name: "D-ID",
    positioning:
      "an AI presenter and talking-photo platform for avatar videos and agents",
    category: "avatar-generator",
    categoryLabel: "AI presenter / talking-photo platform",
    pricingNote:
      "Free trial credits; paid plans from around $5.9/mo up to business tiers. Verify on d-id.com.",
    strengths: [
      "Animate a photo into a talking presenter",
      "Real-time interactive avatars and an API",
      "Many languages and voices",
      "Popular for avatars embedded in apps and agents",
    ],
    menivorEdge: [
      "Menivor narrates your screen recording as product UGC; avatar video is not available yet",
      "Karaoke captions timed to the voiceover on every reel",
      "Hook-first scripts and native 9:16 export for social",
      "Pay-per-reel credits",
    ],
    whenToPickThem:
      "You want talking-photo avatars or interactive avatar agents to embed via an API.",
    whenToPickMenivor:
      "You want a finished, avatar-led UGC reel over your product footage, with captions.",
    comparison: {
      primaryJob: "Animate photos into talking presenters / agents",
      avatar: "Talking-photo and interactive avatars",
      captions: "Captions available; not word-by-word karaoke",
      billing: "Credit / subscription tiers",
      freeTier: "Free trial credits",
    },
  },
  {
    slug: "colossyan",
    name: "Colossyan",
    positioning:
      "an AI video platform focused on workplace learning and training videos",
    category: "avatar-generator",
    categoryLabel: "avatar video platform for L&D",
    pricingNote:
      "Free plan with limited minutes; paid plans from around $27/mo (annual). Verify on colossyan.com.",
    strengths: [
      "Avatar-led training videos with interactive quizzes",
      "Instant translation and many languages",
      "Templates and workflows tuned for corporate L&D",
      "Collaboration features for teams",
    ],
    menivorEdge: [
      "Menivor makes short-form social UGC, not workplace training modules",
      "The avatar sits over your real screen recording as creator-style content",
      "Hook-first scripts, karaoke captions, and 9:16 export for feeds",
      "Pay-per-reel credits",
    ],
    whenToPickThem:
      "You build workplace learning and training videos and want quizzes, translation, and team workflows.",
    whenToPickMenivor:
      "You want feed-native UGC reels from a screen recording, with a hook and karaoke captions.",
    comparison: {
      primaryJob: "Generate avatar-led training / L&D videos",
      avatar: "Studio avatars for training video",
      captions: "Subtitles available; not word-by-word karaoke",
      billing: "Subscription tiers",
      freeTier: "Free plan with limited minutes",
    },
  },
  {
    slug: "fliki",
    name: "Fliki",
    positioning:
      "a text-to-video and text-to-speech tool for narrated, faceless videos",
    category: "faceless-generator",
    categoryLabel: "text-to-video / TTS generator",
    pricingNote:
      "Free tier with limited minutes; paid plans from around $28/mo (annual). Verify on fliki.ai.",
    strengths: [
      "Turn scripts or blog posts into narrated videos with lifelike voices",
      "2,000+ voices across many languages and dialects",
      "Large stock media library and simple workflow",
      "Strong for faceless narration at volume",
    ],
    menivorEdge: [
      "Menivor generates avatar-led UGC from a screen recording, not narrated stock slideshows",
      "A natural AI voiceover plus word-by-word karaoke captions on every reel",
      "Screen-recording layouts (PiP, hook-intro, split) built in",
    ],
    whenToPickThem:
      "You want to convert text into narrated, faceless videos across many voices and languages.",
    whenToPickMenivor:
      "You want avatar-led product UGC from a screen recording, with karaoke captions.",
    comparison: {
      primaryJob: "Turn text into narrated faceless videos",
      avatar: "No lip-synced presenter avatar as the core",
      captions: "Captions/subtitles available",
      billing: "Subscription tiers",
      freeTier: "Free tier with limited minutes",
    },
  },
  {
    slug: "revid-ai",
    name: "Revid.ai",
    positioning:
      "an AI tool for faceless short-form videos and automated content pipelines",
    category: "faceless-generator",
    categoryLabel: "faceless short-video generator",
    pricingNote:
      "Free tier with limits; paid plans from around $19/mo. Verify on revid.ai.",
    strengths: [
      "Generate faceless shorts from a prompt or script",
      "Automation and scheduling for high-volume posting",
      "Templates for popular faceless formats",
      "Fast top-of-funnel content creation",
    ],
    menivorEdge: [
      "Menivor produces avatar-led product UGC over your real screen recording, not generic faceless montages",
      "Karaoke captions timed to a real voiceover",
      "Hook-first scripts and native vertical export",
      "Pay-per-reel credits",
    ],
    whenToPickThem:
      "You want automated, high-volume faceless shorts for entertainment or aggregation feeds.",
    whenToPickMenivor:
      "You want branded, avatar-led product reels from a screen recording, with karaoke captions.",
    comparison: {
      primaryJob: "Generate faceless short-form videos at volume",
      avatar: "Faceless formats rather than a presenter avatar",
      captions: "Auto-captions available",
      billing: "Subscription tiers",
      freeTier: "Free tier with limits",
    },
  },
  {
    slug: "steve-ai",
    name: "Steve AI",
    positioning:
      "an AI video maker for animated and live-action videos from text",
    category: "general-editor",
    categoryLabel: "text-to-video maker",
    pricingNote:
      "Free plan with limits; paid plans from around $15/mo (annual). Verify on steve.ai.",
    strengths: [
      "Generate animated or live-action videos from a script",
      "Large asset and character library",
      "Good for explainers and animated social content",
      "Approachable for non-editors",
    ],
    menivorEdge: [
      "Menivor makes avatar-led UGC from a real screen recording, not animation or stock assembly",
      "A natural AI voiceover plus karaoke captions on every reel",
      "9:16 UGC format tuned for TikTok, Reels, and Shorts",
      "Pay-per-reel credits",
    ],
    whenToPickThem:
      "You want animated explainers or template-driven videos generated from a script.",
    whenToPickMenivor:
      "You want screen-recording-based product UGC with a voiceover and karaoke captions.",
    comparison: {
      primaryJob: "Generate animated / live-action videos from text",
      avatar: "Characters/avatars for animation, not UGC presenters",
      captions: "Captions available",
      billing: "Subscription tiers",
      freeTier: "Free plan with limits",
    },
  },
  {
    slug: "hedra",
    name: "Hedra",
    positioning:
      "a generative platform for expressive talking-character and avatar videos",
    category: "avatar-generator",
    categoryLabel: "generative avatar / character studio",
    pricingNote:
      "Free tier with limited credits; paid plans from around $10/mo. Verify on hedra.com.",
    strengths: [
      "Expressive talking characters from an image plus audio",
      "Strong lip-sync and emotive facial motion",
      "Creative, character-driven output",
      "Fast generation for short talking clips",
    ],
    menivorEdge: [
      "Menivor turns your screen recording into a full narrated reel with a hook script and captions",
      "Word-by-word karaoke captions and 9:16 export built in",
      "End-to-end pipeline: script, voice, avatar, captions, compose in one render",
      "Pay-per-reel credits",
    ],
    whenToPickThem:
      "You want expressive, character-driven talking clips from an image and audio.",
    whenToPickMenivor:
      "You want a finished product reel narrated over your screen recording, with captions.",
    comparison: {
      primaryJob: "Generate expressive talking-character clips",
      avatar: "Talking characters from image + audio",
      captions: "No built-in karaoke captions pipeline",
      billing: "Credit / subscription tiers",
      freeTier: "Free tier with limited credits",
    },
  },
  {
    slug: "argil",
    name: "Argil",
    positioning:
      "an AI clone/avatar tool for creating talking-head content from a personal avatar",
    category: "avatar-generator",
    categoryLabel: "AI clone / avatar tool",
    pricingNote:
      "Paid plans from around $39/mo; limited free access. Verify on argil.ai.",
    strengths: [
      "Create a personal AI clone for talking-head content",
      "Gesture and style controls for a natural presenter",
      "Aimed at creators who want a consistent on-brand avatar",
      "Good for personal-brand short-form video",
    ],
    menivorEdge: [
      "Menivor narrates your real screen recording as product UGC; it does not make on-camera clones",
      "Karaoke captions timed to the voiceover on every reel",
      "Hook-first scripts and native vertical export",
      "Success-only, pay-per-reel credits",
    ],
    whenToPickThem:
      "You want a personal AI clone as a recurring talking-head presenter for your own brand.",
    whenToPickMenivor:
      "You want a voiceover over your product footage as screen-recording UGC, with captions.",
    comparison: {
      primaryJob: "Generate talking-head content from a personal AI clone",
      avatar: "Personal AI clone / avatar",
      captions: "Captions available; not word-by-word karaoke",
      billing: "Subscription tiers",
      freeTier: "Limited free access",
    },
  },
  {
    slug: "higgsfield",
    name: "Higgsfield",
    positioning:
      "an AI video and motion-control tool focused on cinematic generative clips, camera moves, and VFX-style shots",
    category: "text-to-video",
    categoryLabel: "AI cinematic video / motion tool",
    pricingNote:
      "Credit-based paid plans, commonly from around $9–$17/mo with higher creator tiers; a limited free allowance. Verify on higgsfield.ai.",
    strengths: [
      "Cinematic AI clips with strong camera-motion and VFX controls",
      "Great for stylised, film-like generative b-roll and effects",
      "Motion presets that emulate real camera moves",
      "Popular for visually striking, art-directed short clips",
    ],
    menivorEdge: [
      "Menivor produces a finished, postable reel (script, voiceover and captions), not just a raw generative clip",
      "Word-by-word karaoke captions timed to an ElevenLabs voiceover on every reel",
      "Built to turn your own screen recording into product UGC, not only text-to-video art shots",
      "Success-only, pay-per-reel credits that never expire",
    ],
    whenToPickThem:
      "You want cinematic, art-directed generative clips and camera-motion VFX to use as visuals.",
    whenToPickMenivor:
      "You want a complete talking, captioned UGC reel built from your screen recording and a prompt, ready to post.",
    comparison: {
      primaryJob: "Generate cinematic AI clips and camera-motion VFX shots",
      avatar: "No lip-synced presenter; generative motion, not a narrator",
      captions: "No built-in word-by-word karaoke captions",
      billing: "Credit-based subscription tiers",
      freeTier: "Limited free allowance",
    },
  },
];

const COMPETITOR_BY_SLUG: ReadonlyMap<string, Competitor> = new Map(
  COMPETITORS.map((competitor) => [competitor.slug, competitor]),
);

/** Resolve a competitor by slug, or `undefined` when the slug is unknown. */
export function getCompetitor(slug: string): Competitor | undefined {
  return COMPETITOR_BY_SLUG.get(slug);
}

/** Every competitor slug — used by generateStaticParams and the sitemap. */
export const COMPETITOR_SLUGS: readonly string[] = COMPETITORS.map(
  (competitor) => competitor.slug,
);

/**
 * A few related competitors (same category first, then others) for internal
 * linking on a page, excluding the current one.
 */
export function relatedCompetitors(
  slug: string,
  limit = 4,
): readonly Competitor[] {
  const current = getCompetitor(slug);
  const others = COMPETITORS.filter((competitor) => competitor.slug !== slug);
  if (!current) return others.slice(0, limit);
  const sameCategory = others.filter(
    (competitor) => competitor.category === current.category,
  );
  const rest = others.filter(
    (competitor) => competitor.category !== current.category,
  );
  return [...sameCategory, ...rest].slice(0, limit);
}

// --------------------------------------------------------------------------- //
// Structured 2026 pricing for the /pricing/compare cost-per-reel calculator.
// --------------------------------------------------------------------------- //

/** One published (or credibly reported) monthly plan. */
export interface CompetitorPricePlan {
  readonly name: string;
  /** Monthly-billed price in USD. */
  readonly monthlyUsd: number;
  /**
   * Finished videos the plan includes per month, when the vendor states it.
   * `null` for credit-based plans whose per-video credit burn is not published.
   */
  readonly videosPerMonth: number | null;
  /** Credits per month, for credit-based plans. */
  readonly creditsPerMonth?: number;
}

export interface CompetitorPricing {
  readonly slug: string;
  readonly name: string;
  readonly plans: readonly CompetitorPricePlan[];
  /** Where the numbers come from. */
  readonly sourceUrl: string;
  /** `vendor` = the vendor's own pricing page; `third-party` = vendor does not publish. */
  readonly sourceKind: "vendor" | "third-party";
  /** ISO date the numbers were checked. */
  readonly checkedOn: string;
  /** One honest sentence on how their per-video cost works. */
  readonly note: string;
}

/** Date every entry below was last checked against its source. */
export const PRICING_CHECKED_ON = "2026-09-24";

/**
 * Menivor's own personal credit packs (one credit = one finished reel), as
 * listed on /pricing. One-time purchases; credits do not expire.
 */
interface MenivorPack {
  readonly name: string;
  readonly priceUsd: number;
  readonly reels: number;
}

const STARTER_PACK: MenivorPack = { name: "Starter pack", priceUsd: 19, reels: 30 };
const PRO_PACK: MenivorPack = { name: "Pro pack", priceUsd: 59, reels: 120 };

export const MENIVOR_PACKS: readonly MenivorPack[] = [STARTER_PACK, PRO_PACK];

export const COMPETITOR_PRICING: readonly CompetitorPricing[] = [
  {
    slug: "higgsfield",
    name: "Higgsfield",
    plans: [
      { name: "Starter", monthlyUsd: 19, videosPerMonth: null, creditsPerMonth: 270 },
      { name: "Plus", monthlyUsd: 59, videosPerMonth: null, creditsPerMonth: 1200 },
      { name: "Ultra", monthlyUsd: 129, videosPerMonth: null, creditsPerMonth: 3000 },
    ],
    sourceUrl: "https://techsifted.com/roundups/higgsfield-ai-pricing-2026/",
    sourceKind: "third-party",
    checkedOn: PRICING_CHECKED_ON,
    note: "Credit-based; a clip's credit cost depends on the model, length and resolution (a 5-second 1080p Seedance clip is reported at 45 credits). Higgsfield renamed its tiers several times in 2026, so verify on higgsfield.ai/pricing.",
  },
  {
    slug: "arcads",
    name: "Arcads",
    plans: [
      { name: "Starter", monthlyUsd: 110, videosPerMonth: 10 },
      { name: "Creator", monthlyUsd: 220, videosPerMonth: 20 },
    ],
    sourceUrl: "https://www.layer3labs.io/guides/arcads-pricing",
    sourceKind: "third-party",
    checkedOn: PRICING_CHECKED_ON,
    note: "Arcads does not publish prices; these are reviewer-reported figures (about $11 per video). Higher volume is custom-quoted.",
  },
  {
    slug: "creatify",
    name: "Creatify",
    plans: [
      { name: "Starter", monthlyUsd: 39, videosPerMonth: null, creditsPerMonth: 100 },
      { name: "Pro", monthlyUsd: 99, videosPerMonth: null, creditsPerMonth: 300 },
    ],
    sourceUrl: "https://www.creatify.ai/pricing",
    sourceKind: "vendor",
    checkedOn: PRICING_CHECKED_ON,
    note: "Credit-based; the pricing page does not state how many credits one video uses.",
  },
  {
    slug: "captions",
    name: "Captions",
    plans: [
      { name: "Max", monthlyUsd: 24.99, videosPerMonth: null, creditsPerMonth: 500 },
      { name: "Frontier 1x", monthlyUsd: 69.99, videosPerMonth: null, creditsPerMonth: 1400 },
      { name: "Frontier 2x", monthlyUsd: 139.99, videosPerMonth: null, creditsPerMonth: 2800 },
      { name: "Frontier 4x", monthlyUsd: 279.99, videosPerMonth: null, creditsPerMonth: 5600 },
    ],
    sourceUrl: "https://www.captions.ai/pricing",
    sourceKind: "vendor",
    checkedOn: PRICING_CHECKED_ON,
    note: "Credit-based; the pricing page does not state the credit cost of one AI video.",
  },
  {
    slug: "revid-ai",
    name: "Revid",
    plans: [
      { name: "Hobby", monthlyUsd: 39, videosPerMonth: null },
      { name: "Growth", monthlyUsd: 99, videosPerMonth: null, creditsPerMonth: 2000 },
      { name: "Ultra", monthlyUsd: 199, videosPerMonth: null, creditsPerMonth: 12000 },
    ],
    sourceUrl: "https://www.revid.ai/pricing",
    sourceKind: "vendor",
    checkedOn: PRICING_CHECKED_ON,
    note: "Credit-based; the pricing page does not state credits per video.",
  },
  {
    slug: "submagic",
    name: "Submagic",
    plans: [
      { name: "Starter", monthlyUsd: 19, videosPerMonth: 15 },
      { name: "Pro", monthlyUsd: 39, videosPerMonth: 40 },
      { name: "Business", monthlyUsd: 69, videosPerMonth: 100 },
    ],
    sourceUrl: "https://www.submagic.co/pricing",
    sourceKind: "vendor",
    checkedOn: PRICING_CHECKED_ON,
    note: "Per-video plans. Submagic captions and edits footage you already have rather than generating a reel.",
  },
];

/** Cheapest Menivor pack combination covering `reels` reels, in USD. */
export function menivorCostForReels(reels: number): { usd: number; packs: string } {
  const wanted = Math.max(0, Math.ceil(reels));
  if (wanted === 0) return { usd: 0, packs: "No pack needed" };
  const small = STARTER_PACK;
  const large = PRO_PACK;
  let best = { usd: Number.POSITIVE_INFINITY, large: 0, small: 0 };
  const maxLarge = Math.ceil(wanted / large.reels);
  for (let l = 0; l <= maxLarge; l += 1) {
    const remaining = Math.max(0, wanted - l * large.reels);
    const s = Math.ceil(remaining / small.reels);
    const usd = l * large.priceUsd + s * small.priceUsd;
    if (usd < best.usd) best = { usd, large: l, small: s };
  }
  const parts = [
    best.large > 0 ? `${best.large} x ${large.name}` : "",
    best.small > 0 ? `${best.small} x ${small.name}` : "",
  ].filter(Boolean);
  return { usd: best.usd, packs: parts.join(" + ") };
}

export type CompetitorEstimate =
  | { readonly kind: "plan"; readonly usd: number; readonly plan: string }
  | { readonly kind: "overLargest"; readonly usd: number; readonly plan: string }
  | { readonly kind: "creditsOnly"; readonly fromUsd: number; readonly plan: string };

/**
 * What `reels` finished videos per month cost on a competitor: the cheapest
 * plan that includes enough videos, or - for credit plans whose per-video burn
 * is unpublished - only the entry price, never an invented per-video figure.
 */
export function competitorCostForReels(
  pricing: CompetitorPricing,
  reels: number,
): CompetitorEstimate {
  const counted = pricing.plans.filter((plan) => plan.videosPerMonth !== null);
  const cheapest = [...pricing.plans].sort((a, b) => a.monthlyUsd - b.monthlyUsd)[0];
  if (counted.length === 0) {
    return { kind: "creditsOnly", fromUsd: cheapest?.monthlyUsd ?? 0, plan: cheapest?.name ?? "" };
  }
  const fitting = counted
    .filter((plan) => (plan.videosPerMonth ?? 0) >= reels)
    .sort((a, b) => a.monthlyUsd - b.monthlyUsd)[0];
  if (fitting) return { kind: "plan", usd: fitting.monthlyUsd, plan: fitting.name };
  const largest = [...counted].sort((a, b) => (b.videosPerMonth ?? 0) - (a.videosPerMonth ?? 0))[0];
  return { kind: "overLargest", usd: largest?.monthlyUsd ?? 0, plan: largest?.name ?? "" };
}
