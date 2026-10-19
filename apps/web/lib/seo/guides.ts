/**
 * Editorial guide dataset for the `/guides` hub and `/guides/{slug}` pages.
 *
 * Guides are long-form, how-to editorial content that targets informational
 * queries ("how to make a faceless YouTube channel with AI") and funnels into
 * the product. Each guide is grounded in the same shipped Menivor pipeline as
 * the rest of the SEO surface — no invented capabilities or metrics — and is
 * written to be genuinely useful whether or not the reader signs up.
 *
 * Each guide renders:
 *   - an Article node (editorial content),
 *   - a HowTo node (the ordered `steps`),
 *   - an optional FAQPage node (`faqs`),
 * so a single page contributes three complementary structured-data types.
 */

export interface GuideStep {
  /** Short step title. */
  readonly name: string;
  /** One- or two-sentence instruction. */
  readonly text: string;
}

export interface GuideSection {
  readonly heading: string;
  readonly body: readonly string[];
}

export interface GuideFaq {
  readonly question: string;
  readonly answer: string;
}

export interface Guide {
  /** URL segment: `/guides/{slug}`. */
  readonly slug: string;
  /** H1 / page title. */
  readonly title: string;
  /** Primary keyword phrase for metadata. */
  readonly keyword: string;
  /** Meta description. */
  readonly description: string;
  /** One-sentence lede under the H1. */
  readonly lede: string;
  /** Opening paragraphs before the steps. */
  readonly intro: readonly string[];
  /** Ordered how-to steps (also emitted as HowTo JSON-LD). */
  readonly steps: readonly GuideStep[];
  /** Additional editorial sections after the steps. */
  readonly sections: readonly GuideSection[];
  /** Page FAQ (also emitted as FAQPage JSON-LD). */
  readonly faqs: readonly GuideFaq[];
  /** Use-case slugs to link to (must exist in usecases.ts). */
  readonly relatedTools: readonly string[];
  /** ISO date the guide was first published. */
  readonly datePublished: string;
}

const PUBLISHED = "2026-01-20";

export const GUIDES: readonly Guide[] = [
  {
    slug: "how-to-make-a-faceless-youtube-channel-with-ai",
    title: "How to Make a Faceless YouTube Channel with AI",
    keyword: "faceless YouTube channel with AI",
    description:
      "A step-by-step guide to starting and running a faceless YouTube channel with AI — picking a niche, scripting hooks, and producing narrated videos without being on camera.",
    lede: "Start a faceless YouTube channel that doesn't look like every other AI-and-stock channel — with a natural voice over real footage.",
    intro: [
      "A faceless YouTube channel lets you publish consistently without ever appearing on camera. The catch is that most faceless channels use the same recipe — stock footage, a robotic AI voice, and generic captions — so they blur together and struggle to build trust.",
      "This guide walks through starting a faceless channel that stands out by narrating your own screen recordings with a natural AI voice, so every video shows something real while a consistent voice and format carry the message.",
    ],
    steps: [
      {
        name: "Pick a niche you can show on screen",
        text: "Faceless works best when you can demonstrate something: software, tools, tutorials, finance dashboards, or product walkthroughs. Choose a niche where a screen recording is natural proof.",
      },
      {
        name: "Plan a repeatable format",
        text: "Decide on a consistent structure — a hook, a three-point body, and a call to action — so viewers know what to expect and you can produce faster.",
      },
      {
        name: "Record your screen",
        text: "Capture the product, tool, or workflow you'll talk about. Keep it tight; you'll build the video around the most important 20–40 seconds.",
      },
      {
        name: "Generate the video with an AI pipeline",
        text: "Feed the recording plus a short prompt into Menivor. It writes a hook-first script, narrates it over your footage, and burns in karaoke captions.",
      },
      {
        name: "Publish and iterate on hooks",
        text: "Post to YouTube Shorts (and long-form when relevant), then test different opening lines. Keep the hooks that hold retention and reuse the winning template.",
      },
    ],
    sections: [
      {
        heading: "Why real footage beats a stock montage",
        body: [
          "Anonymous stock montages give viewers nothing concrete to latch onto, and viewers can spot generic AI voiceovers instantly. Narrating your own screen recording keeps the channel faceless while still showing your real product or workflow, which is far more credible and more watchable.",
          "It also gives your channel a recognisable format. A consistent voice and style make every upload feel like part of a series rather than a one-off.",
        ],
      },
      {
        heading: "Keep the economics sane",
        body: [
          "A faceless channel only works if publishing stays cheap enough to sustain. Menivor bills per finished reel with credits that never expire, and a failed render returns its credit, so cost scales with output rather than a monthly retainer.",
        ],
      },
    ],
    faqs: [
      {
        question: "Do faceless channels still get monetised?",
        answer:
          "YouTube monetises original, valuable content regardless of whether a face appears. Narrated videos built on your own screen recordings are original content; avoid reused, unedited third-party footage.",
      },
      {
        question: "How many videos should I post?",
        answer:
          "Consistency matters more than volume. A repeatable template and non-expiring credits make a steady cadence — for example a few Shorts a week — sustainable.",
      },
    ],
    relatedTools: [
      "faceless-youtube-channel-videos",
      "faceless-youtube-shorts-maker",
      "ai-avatar-youtube-shorts",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-make-a-faceless-tiktok-account",
    title: "How to Make a Faceless TikTok Account",
    keyword: "faceless TikTok account",
    description:
      "Grow a faceless TikTok account with AI: choose a niche, script hooks that survive three seconds, and produce narrated videos without showing your face.",
    lede: "Build a faceless TikTok presence that still feels authentic, because every video shows your real footage.",
    intro: [
      "TikTok rewards consistency, and daily filming is the fastest route to burnout. A faceless account solves that, but only if the content still holds attention — TikTok ranks watch-through above almost everything else.",
      "This guide shows how to run a faceless TikTok account using a hook-first script, a natural AI voice, and karaoke captions, so your videos keep people watching without you ever going on camera.",
    ],
    steps: [
      {
        name: "Choose a demonstrable niche",
        text: "Pick a topic you can show on a screen — apps, tools, tips, or product walkthroughs — so a screen recording becomes your visual.",
      },
      {
        name: "Write for the first three seconds",
        text: "TikTok lives and dies on the hook. Lead with the payoff or a pattern interrupt; save the setup for later.",
      },
      {
        name: "Record your screen and prompt Menivor",
        text: "Capture the relevant footage, add a one-line prompt, and let Menivor script it hook-first, narrate it, and burn in karaoke captions.",
      },
      {
        name: "Post daily and test hooks",
        text: "Because billing is success-only, render several hook variations and post the ones that perform. Double down on formats that hold retention.",
      },
    ],
    sections: [
      {
        heading: "What 'faceless but authentic' means",
        body: [
          "Faceless doesn't have to mean anonymous. A narrated reel over your own screen recording still shows your real app, workflow, or product, which reads as genuine content rather than a stock montage.",
          "Karaoke captions matter too: most TikTok is watched muted, so word-by-word captions timed to the narration keep your message legible in the feed.",
        ],
      },
    ],
    faqs: [
      {
        question: "Will faceless videos get suppressed?",
        answer:
          "TikTok doesn't penalise faceless content. It rewards original, engaging video — a hook-first narrated reel over your real footage qualifies. Avoid recycled, unedited clips.",
      },
    ],
    relatedTools: [
      "faceless-tiktok-video-maker",
      "talking-head-tiktok-generator",
      "short-form-video-generator",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-make-ugc-ads-with-ai",
    title: "How to Make UGC Ads with AI",
    keyword: "how to make UGC ads with AI",
    description:
      "Learn how to make UGC-style video ads with AI — from scripting a hook to producing narrated creative that shows your product in action, at testing volume.",
    lede: "Produce UGC-style ads that look like a creator's post, not a commercial — and test them at volume.",
    intro: [
      "User-generated-content (UGC) ads outperform polished brand spots on TikTok, Reels, and Meta because they blend into the feed and feel like a recommendation. The problem is supply: sourcing and briefing creators for every variation is slow and expensive.",
      "This guide covers making UGC ads with AI — where a natural AI voice delivers a hook-first script over your real product footage — so you can produce a full creative test batch without hiring for each one.",
    ],
    steps: [
      {
        name: "Start from real product footage",
        text: "Screen-record your product, app, or landing page. The strongest UGC ads show the product doing the thing, not just talking about it.",
      },
      {
        name: "Write a hook, a value point, and a CTA",
        text: "Keep the structure tight: a scroll-stopping hook, one clear benefit, and a single call to action. Menivor's script step is hook-first by design.",
      },
      {
        name: "Generate the ad",
        text: "Menivor narrates the script over your footage and burns in karaoke captions, exporting native 9:16 video for every placement.",
      },
      {
        name: "Batch-test variations",
        text: "Render many hook and angle variations from one recording. Success-only billing means you only pay for finished ads, so systematic testing stays cheap.",
      },
      {
        name: "Scale the winners",
        text: "Put spend behind the variations that hold attention and convert, and retire the rest. Repeat with fresh hooks.",
      },
    ],
    sections: [
      {
        heading: "Why product footage matters",
        body: [
          "An AI actor reading a script on a plain background is easy to produce but weak on proof. Building the ad on your actual screen recording shows the product in use, which is the single most persuasive thing a UGC ad can do.",
        ],
      },
      {
        heading: "Keep it honest",
        body: [
          "UGC framing is a format, not a licence to mislead. Keep claims accurate, use real customer language where possible, and disclose AI-generated content or paid partnerships wherever your platform or local rules require it.",
        ],
      },
    ],
    faqs: [
      {
        question: "Do I need to hire UGC creators?",
        answer:
          "No. A natural AI voice narrates over your screen recording, so you can produce UGC-style ads without sourcing creators, though you can still mix in human UGC when it fits.",
      },
      {
        question: "How many variations should I test?",
        answer:
          "Enough to find a clear winner — often 5–15 hooks per product. Because you only pay for successful renders, testing at that scale is affordable.",
      },
    ],
    relatedTools: [
      "ai-ugc-ad-generator",
      "product-link-to-video",
      "ugc-ad-for-tiktok",
      "ugc-ad-for-facebook-ads",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-write-a-tiktok-hook",
    title: "How to Write a TikTok Hook That Stops the Scroll",
    keyword: "how to write a TikTok hook",
    description:
      "A practical guide to writing TikTok hooks that survive the first three seconds — with patterns, examples, and how to turn a hook into a finished reel.",
    lede: "The first line decides everything on TikTok. Here's how to write hooks that earn the next three seconds.",
    intro: [
      "On short-form video, the opening line is the whole ballgame. If the first three seconds don't create a reason to keep watching, the algorithm never gives your video a chance to spread.",
      "This guide covers hook patterns that work, mistakes to avoid, and how to turn a strong opening line into a finished reel without switching between four different tools.",
    ],
    steps: [
      {
        name: "Lead with the payoff or a tension",
        text: "State the result, the surprising claim, or the problem immediately. Don't warm up — the setup can come after you've earned attention.",
      },
      {
        name: "Make it specific",
        text: "Concrete beats vague. 'I cut my render time to 90 seconds' outperforms 'here's a productivity tip'.",
      },
      {
        name: "Match the hook to the visual",
        text: "The first frame should support the first line. A screen recording that shows the payoff reinforces the hook instantly.",
      },
      {
        name: "Turn the hook into a reel",
        text: "In Menivor, the hook flows straight into the voiceover and karaoke captions, so a strong opening becomes a finished reel in one pass.",
      },
    ],
    sections: [
      {
        heading: "Hook patterns that reliably work",
        body: [
          "A few dependable structures: the bold claim ('This is the fastest way to…'), the mistake callout ('Stop doing X'), the curiosity gap ('Nobody talks about…'), and the direct result ('Here's how I got Y'). Rotate them so your account doesn't feel repetitive.",
          "Whatever pattern you pick, keep it short. A hook that takes five seconds to land has already lost.",
        ],
      },
      {
        heading: "From hook to habit",
        body: [
          "Menivor's SPARK idea engine suggests hook-led angles so you're not staring at a blank page, and hook performance feeds a win-score that surfaces the openings that actually worked — so writing good hooks becomes a repeatable system, not a guess.",
        ],
      },
    ],
    faqs: [
      {
        question: "How long should a hook be?",
        answer:
          "One line — ideally something a viewer can absorb in under two seconds. The goal is to earn the next three seconds, not to explain everything up front.",
      },
    ],
    relatedTools: [
      "tiktok-hook-script-generator",
      "faceless-tiktok-video-maker",
      "short-form-video-generator",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-make-a-product-demo-video-for-social",
    title: "How to Make a Product Demo Video for Social",
    keyword: "product demo video for social media",
    description:
      "Turn a full product walkthrough into a punchy, feed-native demo reel , with a hook, a voiceover and captions, instead of a shrunken webinar.",
    lede: "A demo that works on your website usually dies in the feed. Here's how to rebuild it for social.",
    intro: [
      "A complete product demo is perfect for your website and terrible for a vertical feed: it's too long, has no hook, and assumes the viewer already cares.",
      "This guide shows how to turn the same footage into a short, narrated demo reel built around the single most compelling moment.",
    ],
    steps: [
      {
        name: "Find the one moment that sells",
        text: "Identify the single feature or result that makes people go 'oh, nice'. That moment is your reel; everything else is context.",
      },
      {
        name: "Record just that flow",
        text: "Capture a tight screen recording of the key moment. Trim dead time before you generate.",
      },
      {
        name: "Generate a hook-led reel",
        text: "Menivor scripts the moment hook-first, narrates it over the recording, and burns in karaoke captions: feed-native, not a cut-down webinar.",
      },
      {
        name: "Produce a few angles",
        text: "Change the prompt to frame the same moment for different audiences, and keep the versions that land.",
      },
    ],
    sections: [
      {
        heading: "Show, don't tell",
        body: [
          "Because the reel is built from your real recording, it shows the product doing the thing — the most convincing proof you can offer — while the voiceover explains the value in a UGC style.",
        ],
      },
    ],
    faqs: [
      {
        question: "Can I reuse one recording for several reels?",
        answer:
          "Yes. Vary the prompt and hook to produce different angles from the same screen recording; you only pay for successful renders.",
      },
    ],
    relatedTools: [
      "product-demo-to-reel",
      "saas-demo-video-maker",
      "product-demo-tiktok",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-add-karaoke-captions-to-videos",
    title: "How to Add Karaoke Captions to Your Videos",
    keyword: "how to add karaoke captions",
    description:
      "Learn how word-by-word karaoke captions work, why they boost retention, and how to add them so they stay perfectly in sync with the audio.",
    lede: "Word-by-word captions are one of the strongest retention tools in short-form. Here's how to do them right.",
    intro: [
      "Most short-form video is watched with the sound off, so captions aren't optional — they're the primary channel. Karaoke captions, where each word highlights as it's spoken, add a rhythm that keeps eyes on the screen.",
      "This guide explains what makes karaoke captions work and how to add them so they don't drift out of sync the way auto-generated subtitles often do.",
    ],
    steps: [
      {
        name: "Get accurate word-level timing",
        text: "Karaoke captions need per-word timestamps, not just line-level timing. The more precise the source, the tighter the captions.",
      },
      {
        name: "Style for mobile",
        text: "Use large, high-contrast text and keep lines short so captions are legible on a phone in a busy feed.",
      },
      {
        name: "Burn them in",
        text: "Rendering captions into the video file (rather than a separate track) means they display everywhere, including where uploaded subtitle files are ignored.",
      },
      {
        name: "Let the pipeline handle it",
        text: "Menivor generates karaoke captions automatically and burns them in, timed to word-level timestamps from the voiceover itself.",
      },
    ],
    sections: [
      {
        heading: "Why sync usually breaks — and how to avoid it",
        body: [
          "Drift happens when captions are timed from a different source than the audio. Menivor treats the voiceover's word-level timestamps as the single timing source for the whole render, so the voice and the on-screen words all reference the same clock.",
          "Correct glyph rendering matters just as much as timing. Menivor bundles fonts with extended Latin coverage, so characters like ş, ğ, ı, İ, ç, and ö render correctly.",
        ],
      },
    ],
    faqs: [
      {
        question: "Are karaoke captions better than normal subtitles?",
        answer:
          "For retention, usually yes. Word-by-word highlighting adds a rhythm that holds attention, and burned-in captions display everywhere without a separate file.",
      },
    ],
    relatedTools: [
      "karaoke-caption-generator",
      "add-captions-to-video",
      "faceless-instagram-reels-maker",
      "short-form-video-generator",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-make-ai-avatar-videos",
    title: "How to Make Avatar Videos, and What to Make Today",
    keyword: "how to make avatar videos",
    description:
      "What avatar video is, what it takes to look right in a feed, and what Menivor can make for you today while its avatar video is not available.",
    lede: "Avatar video is not available in Menivor yet. Here is what makes it work, and what to make today instead.",
    intro: [
      "Avatar video puts a generated person on screen to speak your script. A talking head floating on a studio backdrop reads as synthetic and rarely performs as social content; the versions that work show something real behind or beside the speaker.",
      "Menivor does not offer avatar video today. This guide covers what matters if you use it anywhere, and how to get most of the same result now with a voiced, captioned reel over your real footage.",
    ],
    steps: [
      {
        name: "Write a short, spoken-style script",
        text: "Any narrated video sounds best with conversational lines. Keep sentences short and front-load the point.",
      },
      {
        name: "Show something real",
        text: "Record your screen, the product, app or workflow, so the video has real proof on screen rather than a blank background.",
      },
      {
        name: "Narrate it without filming",
        text: "In Menivor, a natural AI voice reads the hook-first script over your recording. Nobody appears on camera.",
      },
      {
        name: "Add captions and export vertical",
        text: "Karaoke captions are burned in and the whole thing is composed into a native 1080×1920 MP4 in a single render.",
      },
    ],
    sections: [
      {
        heading: "Keeping narration and captions in sync",
        body: [
          "Captions drift when they are timed from a different source than the audio. Menivor times the captions from the voiceover's own word-level timestamps, so each word lands as it is spoken.",
        ],
      },
    ],
    faqs: [
      {
        question: "Can Menivor make avatar videos today?",
        answer:
          "No. Avatar video is not available yet. Menivor makes voiced, captioned reels over your footage or a style scene, and this page will change when avatar video opens.",
      },
    ],
    relatedTools: [
      "ai-avatar-video-generator",
      "talking-head-video-generator",
      "ai-spokesperson-video-generator",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-turn-a-screen-recording-into-a-reel",
    title: "How to Turn a Screen Recording into a Reel",
    keyword: "turn screen recording into a reel",
    description:
      "Turn a raw screen recording into a polished, hook-led vertical reel , with narration and captions, instead of posting the raw capture.",
    lede: "A raw screen recording is rarely postable. Here's how to turn one into a finished reel.",
    intro: [
      "Screen recordings are the richest source material most creators and founders already have — but on their own they're too long, have no hook, and no narration.",
      "This guide walks through turning a raw capture into a tight, narrated 9:16 reel that's ready to post.",
    ],
    steps: [
      {
        name: "Capture the useful part",
        text: "Record the specific action or result you want to show. Aim for a clean 20–60 second capture of the moment that matters.",
      },
      {
        name: "Write a one-line prompt",
        text: "Describe the message and the audience in a sentence. This drives the hook-first script.",
      },
      {
        name: "Run the pipeline",
        text: "Menivor scripts the recording, narrates it, burns in karaoke captions, and composes a native 1080×1920 MP4.",
      },
      {
        name: "Publish or download",
        text: "Download the MP4 and post it to TikTok, Reels and Shorts. Direct posting from Menivor is not open yet.",
      },
    ],
    sections: [
      {
        heading: "Generation, not clipping",
        body: [
          "This is the core difference between Menivor and a clipping tool: a clipper cuts an existing long video into short moments, while Menivor writes and narrates a new reel around your recording. The output is net-new UGC, not a trimmed clip.",
        ],
      },
    ],
    faqs: [
      {
        question: "What layouts can the reel use?",
        answer:
          "Full-frame or split-screen styles, so your real content stays on screen rather than being replaced.",
      },
    ],
    relatedTools: [
      "screen-recording-to-video",
      "vertical-video-generator",
      "app-demo-video-maker",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-make-youtube-shorts-without-showing-your-face",
    title: "How to Make YouTube Shorts Without Showing Your Face",
    keyword: "YouTube Shorts without showing your face",
    description:
      "Make YouTube Shorts without appearing on camera — using a natural AI voice over your screen recording, a hook-first script, and burned-in captions.",
    lede: "You can feed the Shorts shelf every week without ever being on camera.",
    intro: [
      "YouTube Shorts is a discovery engine that rewards volume and a strong opening loop — but filming yourself for every Short isn't realistic for most people.",
      "This guide shows how to produce Shorts without showing your face, using a natural AI voice over your own footage so the videos still feel real.",
    ],
    steps: [
      {
        name: "Plan a repeatable Shorts format",
        text: "Decide on a hook, a single idea, and a payoff. A repeatable structure lets you produce faster and keeps your channel recognisable.",
      },
      {
        name: "Record your screen",
        text: "Capture the tool, product, or concept you're covering so the Short has real footage behind the narration.",
      },
      {
        name: "Generate the Short",
        text: "Menivor scripts it hook-first, narrates it, burns in karaoke captions, and exports a clean 1080×1920 file for the Shorts shelf.",
      },
      {
        name: "Post consistently",
        text: "Non-expiring, success-only credits keep a steady cadence affordable, so you can publish regularly without a subscription to burn down.",
      },
    ],
    sections: [
      {
        heading: "Faceless, but not generic",
        body: [
          "Because the narration sits over your real screen recording, each Short shows your actual product or workflow, which sets it apart from the stock-montage look that dominates faceless Shorts.",
        ],
      },
    ],
    faqs: [
      {
        question: "Can these Shorts funnel to long-form?",
        answer:
          "Yes. A narrated Short built on your real footage is a natural teaser for deeper long-form content or your product.",
      },
    ],
    relatedTools: [
      "faceless-youtube-shorts-maker",
      "youtube-shorts-maker",
      "ai-avatar-youtube-shorts",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-make-instagram-reels-for-business",
    title: "How to Make Instagram Reels for Business",
    keyword: "Instagram Reels for business",
    description:
      "A guide to producing Instagram Reels for business consistently — narrated, captioned, and built from product footage, without a video team.",
    lede: "Keep a business Instagram active with feed-native Reels, without hiring a video team.",
    intro: [
      "Instagram Reels increasingly surfaces content from accounts people don't follow, which makes it a real growth channel for businesses — if you can keep up a steady, polished cadence.",
      "This guide covers producing Reels for business consistently, using a natural AI voice over your product footage and captions styled for the muted feed.",
    ],
    steps: [
      {
        name: "Decide on recurring Reel themes",
        text: "Pick a few repeatable themes — tips, features, offers, behind-the-scenes — so you always have something to post.",
      },
      {
        name: "Record the relevant screen or product",
        text: "Capture footage that supports the theme: a product page, an app flow, or a workflow.",
      },
      {
        name: "Generate a polished Reel",
        text: "Menivor turns the recording into a hook-first Reel with a voiceover and karaoke captions, exported native 1080×1920.",
      },
      {
        name: "Publish and stay consistent",
        text: "Download the MP4 and post or schedule it in Instagram. Consistency compounds on Reels.",
      },
    ],
    sections: [
      {
        heading: "Match Instagram's aesthetic bar",
        body: [
          "Instagram's audience skews toward polish. A narrated reel over your own footage keeps a Reel product-real and on-brand rather than a generic stock montage, and clonable templates help you hold a consistent look across posts.",
        ],
      },
    ],
    faqs: [
      {
        question: "Do I need to be on camera for business Reels?",
        answer:
          "No. A natural AI voice can narrate your product footage, so you can maintain a consistent business presence without filming.",
      },
    ],
    relatedTools: [
      "instagram-reels-maker",
      "faceless-instagram-reels-maker",
      "ai-avatar-instagram-reels",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-create-turkish-ai-videos",
    title: "How to Create Turkish AI Videos",
    keyword: "how to create Turkish AI videos",
    description:
      "A guide to making native Turkish AI videos — with Turkish hook scripts, correct Turkish-glyph captions, and no translation step.",
    lede: "Here's how to make AI videos written and voiced in Turkish from the start.",
    intro: [
      "A translated script often shows it: awkward phrasing, a hook that doesn't land, and broken Turkish characters in the captions.",
      "This guide covers making Turkish AI videos natively — where the script, voiceover, and captions are all generated in Turkish.",
    ],
    steps: [
      {
        name: "Write the script in Turkish, not translated",
        text: "A native Turkish hook reads differently from a translated one. Menivor writes Turkish hook-first scripts directly rather than translating English.",
      },
      {
        name: "Record your screen and prompt in Turkish",
        text: "Provide a Turkish prompt describing the goal and audience so the whole reel is generated in Turkish.",
      },
      {
        name: "Generate with correct Turkish glyphs",
        text: "Menivor renders karaoke captions with bundled Turkish-glyph fonts, so ş, ğ, ı, İ, ç, and ö display correctly instead of breaking.",
      },
      {
        name: "Publish to a Turkish audience",
        text: "Download the native 9:16 MP4 and post it to TikTok, Reels, and Shorts.",
      },
    ],
    sections: [
      {
        heading: "Why native beats translated",
        body: [
          "A native Turkish pipeline — script, voice, and captions — reads more naturally than an English script with translated subtitles, and the hook lands the way it was written.",
        ],
      },
    ],
    faqs: [
      {
        question: "Is Turkish support real or just translation?",
        answer:
          "It's native. Menivor writes Turkish scripts and renders Turkish-glyph captions — not an English script with subtitles bolted on.",
      },
    ],
    relatedTools: [
      "turkish-ai-video-generator",
      "faceless-video-generator",
      "ai-ugc-ad-generator",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-test-ad-creative-at-scale",
    title: "How to Test Ad Creative at Scale",
    keyword: "how to test ad creative at scale",
    description:
      "Systematic creative testing is the biggest lever in paid social. Learn how to produce enough UGC-style variations to find winners without blowing your budget.",
    lede: "Creative is the biggest lever in paid social — but only if you can test enough of it.",
    intro: [
      "On TikTok and Meta, creative usually explains more of your ad performance than targeting or bidding. The teams that win are the ones that test the most variations and scale the winners.",
      "This guide covers how to test ad creative at scale without a production bottleneck, by generating UGC-style variations from a single recording.",
    ],
    steps: [
      {
        name: "Define your variables",
        text: "Decide what you're testing — hooks, angles, or offers — and change one variable at a time so results are readable.",
      },
      {
        name: "Record once, vary the prompt",
        text: "Capture one screen recording, then generate many reels by changing the hook and framing in the prompt.",
      },
      {
        name: "Generate a batch",
        text: "Menivor renders each variation as native 9:16 video with a voiceover and captions. Success-only billing means you only pay for finished ads.",
      },
      {
        name: "Ship, measure, and scale winners",
        text: "Run the batch, cut the losers early, and put budget behind the variations that hold attention and convert. Then repeat with fresh hooks.",
      },
    ],
    sections: [
      {
        heading: "Why cheap variations change the math",
        body: [
          "When each variation costs a creator brief and a fee, you test conservatively. When variations are cheap — you only pay for successful renders and credits never expire — you can test aggressively, which is exactly how you find outlier winners.",
        ],
      },
    ],
    faqs: [
      {
        question: "How many variations is 'at scale'?",
        answer:
          "It depends on spend, but many performance teams test 10+ creatives per concept. The point is to test enough to find a clear winner, then scale it.",
      },
    ],
    relatedTools: [
      "tiktok-ad-maker",
      "tiktok-ads-from-product-page",
      "ugc-ad-for-facebook-ads",
      "lead-gen-video-ad-maker",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-repurpose-a-webinar-into-shorts",
    title: "How to Repurpose a Webinar into Shorts",
    keyword: "repurpose a webinar into shorts",
    description:
      "Turn a long webinar or demo into a series of hook-led, narrated Shorts built for the feed — instead of posting shrunken recordings.",
    lede: "One webinar can seed weeks of short-form — if you rebuild it for the feed instead of trimming it.",
    intro: [
      "A webinar or long demo is a goldmine of content, but posting cut-down segments rarely works: they lack a hook, and they still feel like a slice of a long video.",
      "This guide shows how to repurpose a webinar into Shorts by generating new, hook-led reels around its best moments.",
    ],
    steps: [
      {
        name: "List the standout moments",
        text: "Pull the three to five moments that stand on their own — a strong insight, a surprising result, a clear how-to.",
      },
      {
        name: "Capture or clip the relevant screen",
        text: "For each moment, grab a short screen recording of the supporting visual (a slide, a product view, a chart).",
      },
      {
        name: "Generate a Short per moment",
        text: "Menivor scripts each moment hook-first, narrates it over the footage, and burns in captions: a new reel, not a trimmed segment.",
      },
      {
        name: "Publish as a series",
        text: "Space the Shorts out as a series that points back to the full webinar or your product.",
      },
    ],
    sections: [
      {
        heading: "Rebuild, don't just trim",
        body: [
          "The difference between repurposing that works and repurposing that flops is whether each Short is built for the feed. Generating a new hook-led reel around a moment beats slicing the recording, because the Short gets its own opening instead of starting mid-thought.",
        ],
      },
    ],
    faqs: [
      {
        question: "How many Shorts can one webinar produce?",
        answer:
          "Usually several — one per standout moment. Non-expiring credits make producing a whole series from a single event practical.",
      },
    ],
    relatedTools: [
      "youtube-shorts-maker",
      "product-demo-to-reel",
      "explainer-video-generator",
    ],
    datePublished: PUBLISHED,
  },
  {
    slug: "how-to-choose-an-ai-video-generator",
    title: "How to Choose an AI Video Generator",
    keyword: "how to choose an AI video generator",
    description:
      "A practical framework for choosing an AI video generator — clippers vs avatar tools vs generative models vs end-to-end reel pipelines — based on the job you actually need done.",
    lede: "There's no single 'best' AI video tool — only the right one for the job you're doing.",
    intro: [
      "The AI video space is crowded and the categories blur together, which makes it hard to compare tools fairly. The trick is to start from the job you need done, not from a feature checklist.",
      "This guide breaks the market into clear categories and helps you match one to your actual workflow.",
    ],
    steps: [
      {
        name: "Name the job",
        text: "Are you clipping long videos, generating synthetic footage, making a standalone talking head, or producing UGC-style product reels? Each is a different category.",
      },
      {
        name: "Match the category",
        text: "Clippers cut existing footage; generative models create synthetic clips; avatar tools make talking heads; end-to-end pipelines (Menivor) produce finished reels from a link or a screen recording.",
      },
      {
        name: "Check the whole pipeline",
        text: "A finished reel needs a script, voice, footage, captions, and export. Tools that only do one stage leave you stitching several together.",
      },
      {
        name: "Weigh pricing and language",
        text: "Compare subscription vs pay-per-output, whether failed renders cost you, and whether the tool genuinely supports your language — native scripts and correct caption glyphs, not just translated subtitles.",
      },
    ],
    sections: [
      {
        heading: "Where Menivor fits",
        body: [
          "Menivor is an end-to-end reel pipeline: it turns a link or a screen recording into a finished reel with a hook script, voiceover, karaoke captions, and native 9:16 export, in one pass rather than four tools. Avatar video is not part of it yet. It works in English or Turkish and bills per finished reel with credits that never expire.",
          "If you mostly clip existing long videos, generate cinematic B-roll, or need enterprise training video, another category may fit better — and the comparison pages lay those trade-offs out honestly.",
        ],
      },
    ],
    faqs: [
      {
        question: "Is one tool enough, or do I need several?",
        answer:
          "It depends on the job. A single-stage tool (just captions, just an avatar) usually means stitching several together; an end-to-end pipeline produces a finished reel on its own.",
      },
      {
        question: "How should I compare pricing?",
        answer:
          "Look past the headline price: check whether you pay for failed renders, whether credits expire, and whether it's per-seat or per-output. Pay-per-finished-output tends to suit bursty, test-heavy work.",
      },
    ],
    relatedTools: [
      "ai-ugc-ad-generator",
      "screen-recording-to-video",
      "short-form-video-generator",
    ],
    datePublished: PUBLISHED,
  },
];

const GUIDE_BY_SLUG: ReadonlyMap<string, Guide> = new Map(
  GUIDES.map((guide) => [guide.slug, guide]),
);

/** Resolve a guide by slug, or `undefined` when the slug is unknown. */
export function getGuide(slug: string): Guide | undefined {
  return GUIDE_BY_SLUG.get(slug);
}

/** Every guide slug — used by generateStaticParams and the sitemap. */
export const GUIDE_SLUGS: readonly string[] = GUIDES.map((guide) => guide.slug);

/**
 * Related guides for internal linking, excluding the current one: the next
 * `limit` guides in list order, wrapping around, so every guide receives
 * links from other guides (not only the first few in the list).
 */
export function relatedGuides(slug: string, limit = 4): readonly Guide[] {
  const index = GUIDES.findIndex((guide) => guide.slug === slug);
  const start = index === -1 ? 0 : index + 1;
  const rotated = [...GUIDES.slice(start), ...GUIDES.slice(0, start)];
  return rotated.filter((guide) => guide.slug !== slug).slice(0, limit);
}
