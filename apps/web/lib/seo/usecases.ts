import { OFFER } from "@/lib/offer";

/**
 * Use-case / free-tool landing-page dataset for `/tools/{slug}`.
 *
 * Each entry is a genuine angle Menivor supports, described in terms of the
 * shipped pipeline (link or screen recording → script → voice → karaoke
 * captions). Copy is differentiated per use case to avoid thin doorway pages.
 */

export interface UseCaseFaq {
  readonly question: string;
  readonly answer: string;
}

export interface UseCase {
  /** URL segment: `/tools/{slug}`. */
  readonly slug: string;
  /** H1 / page title. */
  readonly title: string;
  /** Primary keyword phrase for metadata. */
  readonly keyword: string;
  /** One-sentence lede under the H1. */
  readonly lede: string;
  /** 3–5 paragraphs of genuine, differentiated body copy. */
  readonly body: readonly string[];
  /** Concrete outcomes / feature bullets for this angle. */
  readonly highlights: readonly string[];
  /** "Best for" audience line. */
  readonly bestFor: string;
  /** Page-specific FAQ (also emitted as FAQPage JSON-LD). */
  readonly faqs: readonly UseCaseFaq[];
  /** Optional CTA into a free in-browser tool with closely related intent, shown above the fold. */
  readonly relatedTool?: { readonly href: string; readonly title: string };
}

export const USE_CASES: readonly UseCase[] = [
  {
    slug: "product-link-to-video",
    title: "Turn a Product Link into Short Videos",
    keyword: "product link to video",
    lede: "Paste a product or landing page link and get three vertical reels, each opening with a different hook.",
    body: [
      "Most product pages already say what the product does, who it is for and why it is worth buying. Menivor reads the page behind the link you paste and turns it into hook-first scripts, so you do not have to write the ad yourself.",
      "Each run renders three vertical reels in 9:16 from the same link, and each one opens with a different hook. The rest of the reel is voiced by a natural AI voice and carries word-by-word captions, so it reads with the sound off.",
      "You pick the look with one click: a gameplay split-screen, a satisfying loop, a story-style scene and more. The reels come back as MP4 files you download and post to TikTok, Instagram Reels and YouTube Shorts.",
    ],
    highlights: [
      "One input: the URL of your product or landing page",
      "Three reels per run, each with a different opening hook",
      "AI voiceover and word-by-word captions in every reel",
      "1080×1920 MP4 files ready for TikTok, Reels and Shorts",
    ],
    bestFor: "Founders, shop owners and marketers who want ad reels without writing a script.",
    faqs: [
      {
        question: "What kind of link can I paste?",
        answer:
          "A public product page, landing page or app page. Menivor reads the text on the page to write the hooks and the script, so a page that explains the product clearly gives the best reels.",
      },
      {
        question: "Why three reels instead of one?",
        answer:
          "The opening line decides whether people keep watching. Three reels with three different hooks let you post or test them side by side and keep the one that works.",
      },
      {
        question: "Can I try it for free?",
        answer: OFFER.seoFaqFree,
      },
    ],
  },
  {
    slug: "tiktok-ads-from-product-page",
    title: "TikTok Ads from a Product Page",
    keyword: "TikTok ads from product page",
    lede: "Turn the page you already sell from into vertical TikTok ad reels with a hook, a voiceover and captions.",
    body: [
      "A TikTok ad has to earn attention in its first line, say one thing clearly and end on a reason to tap. Your product page already holds the material for that: the promise, the features and the price. Menivor reads that page from its link and writes the ad script for you.",
      "Every run gives you three vertical ad reels with different opening hooks, voiced by a natural AI voice and captioned word by word. Captions matter on TikTok because many people scroll with the sound off.",
      "Download the reels and upload them to your TikTok account or to your ad manager as creatives. Because each reel opens differently, you can run them as a small hook test instead of betting on one version.",
    ],
    highlights: [
      "Ad scripts written from your product page, no brief needed",
      "Three hook variations per run for simple creative tests",
      "Word-by-word captions for sound-off viewing",
      "Native 9:16 MP4 you upload as a TikTok ad creative",
    ],
    bestFor: "Online stores, apps and SaaS teams that need TikTok ad creatives fast and cheaply.",
    faqs: [
      {
        question: "Does Menivor run the ad on TikTok for me?",
        answer:
          "No. Menivor makes the ad reels; you download them and upload them to TikTok or your ad manager yourself.",
      },
      {
        question: "Do I need footage of my product?",
        answer:
          "No. Menivor writes and voices the ad from the page and renders it over a style you pick. If you have a screen recording of your app or site, you can use that as the footage instead.",
      },
    ],
  },
  {
    slug: "add-captions-to-video",
    title: "Add Captions to a Video Automatically",
    keyword: "add captions to video automatically",
    lede: "Upload your own vertical video and get it back with word-by-word captions burned in, timed to its own audio.",
    body: [
      "Not every reel needs a new script. If you already filmed a clip or recorded your screen with your own voice, Menivor can caption it for you: it uses the audio in your video to time the captions, so nothing is re-voiced.",
      "The captions are word by word and burned into the video, so they show up on every platform without a separate subtitle file. That keeps the clip readable for people watching with the sound off.",
      "You get the result back as a vertical MP4 to download and post. If you would rather have Menivor write and voice the reel too, paste a link or type a topic instead.",
    ],
    highlights: [
      "Captions timed to the audio already in your video",
      "Word-by-word captions burned into the MP4",
      "Your own voice and footage, nothing re-voiced",
      "Vertical export for TikTok, Reels and Shorts",
    ],
    bestFor: "Creators who film their own clips and want clean captions without editing them by hand.",
    faqs: [
      {
        question: "Does Menivor change my audio?",
        answer:
          "No. When you caption your own video, Menivor keeps its audio and uses it to time the captions.",
      },
      {
        question: "Are the captions a separate file?",
        answer:
          "No. They are burned into the video, so they display on every platform without a subtitle upload.",
      },
    ],
  },
  {
    slug: "ai-ugc-ad-generator",
    title: "AI UGC Video Generator for Ads",
    keyword: "AI UGC video generator",
    lede: "Turn a screen recording into an AI UGC video with a natural AI voiceover and karaoke captions.",
    body: [
      "An AI UGC video pairs a creator-style voiceover with real product footage. With Menivor, you record your product or app and add a short prompt; Menivor writes a hook-first script, narrates it over the recording.",
      "Because the whole thing is generated from your screen recording, the ad shows your actual product in action — the single most persuasive thing a UGC ad can do — while the voiceover and karaoke captions carry the message.",
      `${OFFER.seoFreeVideos} After that, one credit produces one successfully rendered reel; failed renders return the reserved credit, and purchased credits never expire.`,
    ],
    highlights: [
      "Hook-first script written for you (English or Turkish)",
      "A natural AI voiceover over your real product footage",
      "Word-by-word karaoke captions burned in",
      "Native 1080×1920 export for TikTok, Reels, and Shorts",
    ],
    bestFor: "Founders and marketers creating UGC ads at volume.",
    faqs: [
      {
        question: "What is an AI UGC video generator?",
        answer:
          "An AI UGC video generator combines product footage with an AI-written script, voiceover, and captions to produce creator-style videos without filming a spokesperson. Menivor uses your screen recording as the product footage.",
      },
      {
        question: "What do I need to create an AI UGC video?",
        answer:
          "A screen recording of your product or app and a short prompt describing the message. Menivor handles the script, voiceover, and captions.",
      },
      {
        question: "Can I use the AI UGC video generator for free?",
        answer:
          `${OFFER.seoFaqFree} After those reels, you can buy non-expiring credit packs when checkout is available.`,
      },
      {
        question: "Can I test multiple hooks for one product?",
        answer:
          "Yes. Because billing is success-only and credits never expire, you can render several hook variations and keep the ones that perform.",
      },
      {
        question: "Do the ads work in Turkish?",
        answer:
          "Yes. Menivor writes scripts and voiceovers in English or Turkish, and its captions render Turkish characters correctly.",
      },
    ],
  },
  {
    slug: "tiktok-hook-script-generator",
    title: "Viral TikTok Script Generator",
    keyword: "viral TikTok script generator",
    lede: "Start from a hook, not a blank page: get a structured, hook-first script, then render it straight into a finished reel.",
    body: [
      "Most script tools start with a topic and hope the opening line works out. Menivor's script step is hook-first by design: it produces structured, hook-led scripts (in English or Turkish) rather than generic paragraphs, and you can pull fresh angles from the SPARK idea engine instead of staring at a blank page. Want to see hook lines on their own first? Try the free TikTok hook generator.",
      "Unlike a standalone script tool, Menivor doesn't stop at text. The same hook flows straight into voiceover and karaoke captions timed to the narration — so a strong opening line becomes a finished, postable reel in the same pass.",
      "Hook performance is tracked through the Hook Performance Loop and feeds a win-score on templates, so the scripts that actually land become easier to find and reuse over time.",
    ],
    highlights: [
      "Structured, hook-first scripts in English or Turkish",
      "SPARK idea engine for fresh angles",
      "Scripts flow into voiceover and captions automatically",
      "Win-score ranking surfaces scripts that perform",
    ],
    bestFor: "Creators who want a full script, not just an opening line.",
    faqs: [
      {
        question: "Does it only write scripts?",
        answer:
          "No. The script is the first stage of a full pipeline — it flows into voiceover and karaoke captions to produce a finished reel.",
      },
      {
        question: "Can I write scripts in Turkish?",
        answer:
          "Yes. Menivor writes hook-first scripts in English or Turkish natively.",
      },
      {
        question: "I just want hook lines, not a full script. Is there a tool for that?",
        answer:
          "Yes — the free TikTok hook generator writes 10 opening-line options on their own, with no script or render attached.",
      },
    ],
    relatedTool: {
      href: "/tools/tiktok-hook-generator",
      title: "Just want hook lines? Try the free TikTok hook generator",
    },
  },
  {
    slug: "faceless-video-generator",
    title: "Faceless Video Generator",
    keyword: "faceless video generator",
    lede: "Publish consistently without ever being on camera: a natural AI voice narrates for you.",
    body: [
      "You don't need to show your face to post daily. With Menivor, a natural AI voice narrates over a screen recording, so you get a clear, human-sounding explainer without filming yourself.",
      "This is a different take on 'faceless' than generic stock-footage montages: because the voiceover plays over your own screen recording, the video still shows something real — your product, your workflow, your walkthrough — instead of anonymous B-roll.",
      "Karaoke captions keep the video watchable with the sound off, and native 9:16 export means it's ready to post to TikTok, Reels, and Shorts the moment it renders.",
    ],
    highlights: [
      "A natural AI voiceover, no camera required",
      "Your real screen recording as the backdrop",
      "Karaoke captions for sound-off viewing",
      "English or Turkish narration",
    ],
    bestFor: "Creators and founders who want to post without being on camera.",
    faqs: [
      {
        question: "Is this just stock footage with captions?",
        answer:
          "No. A natural AI voice narrates your script over your own screen recording, so the video shows your real product or workflow, not anonymous B-roll.",
      },
      {
        question: "Can I stay fully anonymous?",
        answer:
          "Yes. The voice is a natural AI voice and the picture is your recording or a style scene, so you never have to appear on camera or record your own voice.",
      },
    ],
  },
  {
    slug: "screen-recording-to-video",
    title: "Screen Recording to Video",
    keyword: "screen recording to video",
    lede: "Drop in a raw screen capture and get back a polished, narrated vertical reel.",
    body: [
      "A raw screen recording is rarely postable on its own — it's too long, has no hook, and no narration. Menivor is built specifically to fix that: it takes your screen capture plus a prompt and returns a tight, hook-led 9:16 reel.",
      "The pipeline scripts the recording, narrates it with a natural AI voice, lays it out full-frame or as a split screen, and burns in word-by-word karaoke captions, then composes everything into a 1080×1920 MP4.",
      "This is the core thing Menivor does that pure clippers don't: it isn't cutting an existing long video into moments, it's turning a screen recording into net-new UGC.",
    ],
    highlights: [
      "Purpose-built for screen recordings, not long-video clipping",
      "Full-frame and split-screen styles",
      "Natural AI voiceover + karaoke captions applied automatically",
      "1080×1920 MP4 ready to post",
    ],
    bestFor: "Anyone turning product demos or walkthroughs into reels.",
    faqs: [
      {
        question: "How is this different from a clipping tool?",
        answer:
          "Clippers cut an existing long video into short moments. Menivor generates a new narrated reel from your screen recording and a prompt.",
      },
      {
        question: "What layouts are available?",
        answer:
          "Your recording can fill the frame or sit in a split-screen style above a moving loop.",
      },
    ],
  },
  {
    slug: "ai-avatar-video-generator",
    title: "Avatar Video Generator (Not Available Yet)",
    keyword: "avatar video generator",
    lede: "Avatar video is not available in Menivor yet. Here is what you can make today without anyone on camera.",
    body: [
      "Avatar video, a generated person speaking your script on camera, is not available in Menivor yet. This page stays up so you know where it stands, and it will change the day avatar video opens.",
      "What Menivor makes today is a voiced, captioned reel: a hook-first script, a natural AI voiceover and word-by-word captions over your screen recording, a recording of your page, or a moving style scene. Nobody has to be on camera.",
      "For most product and explainer reels the voice-over-footage format does the same job: your real product stays on screen while the voice carries the message, and there is no uncanny face to distract from it.",
    ],
    highlights: [
      "Avatar video: not available yet",
      "A natural AI voiceover instead of a face",
      "Your real footage or page as the picture",
      "Word-by-word captions and a 9:16 MP4",
    ],
    bestFor: "Marketers who want video without filming, using what works today.",
    faqs: [
      {
        question: "Can Menivor make avatar videos?",
        answer:
          "Not yet. Avatar video is not available. Menivor renders voiced, captioned reels over your footage or a style scene.",
      },
      {
        question: "What can I make instead?",
        answer:
          "A hook-first reel narrated by a natural AI voice over your screen recording or page, with word-by-word captions, in one of several one-click styles.",
      },
    ],
  },
  {
    slug: "karaoke-caption-generator",
    title: "Karaoke Caption Generator",
    keyword: "karaoke caption generator",
    lede: "Burn in word-by-word captions that land exactly on the spoken word.",
    body: [
      "Karaoke captions — where each word highlights as it's spoken — are one of the strongest retention tools in short-form video. Menivor generates them automatically and burns them in, so they're part of the video file, not a separate track.",
      "Timing comes from the voiceover's own word-level timestamps, which Menivor treats as the single timing authority. That's why the captions stay tight to the narration instead of drifting the way auto-generated subtitles often do.",
      "Bundled fonts cover extended Latin glyphs, so Turkish characters like ş, ğ, and ı render correctly out of the box.",
    ],
    highlights: [
      "Word-by-word karaoke highlighting",
      "Burned into the MP4, no separate file",
      "Timed to the voiceover's word-level timestamps",
      "Correct Turkish-glyph rendering",
    ],
    bestFor: "Creators who want captions that actually improve retention.",
    faqs: [
      {
        question: "Are captions burned in or a separate file?",
        answer:
          "They're burned into the video, so they display everywhere without needing a separate subtitle track.",
      },
      {
        question: "Do Turkish characters render correctly?",
        answer:
          "Yes. Menivor bundles fonts with full Turkish glyph coverage, so Turkish captions render correctly.",
      },
    ],
  },
  {
    slug: "turkish-ai-video-generator",
    title: "Turkish AI Video Generator",
    keyword: "Turkish AI video generator",
    lede: "Make AI UGC videos in Turkish — native scripts, voiceovers, and correctly rendered captions.",
    body: [
      "Turkish is one of the languages Menivor writes and voices natively: it writes Turkish hook scripts, narrates them, and renders correct Turkish-glyph karaoke captions.",
      "The full pipeline works the same in Turkish as in English — screen recording plus prompt in, a finished narrated 9:16 reel out — with no separate translation step.",
    ],
    highlights: [
      "Turkish hook scripts and narration",
      "Correct Turkish-glyph karaoke captions",
      "Same full pipeline as English",
    ],
    bestFor: "Creators and brands publishing Turkish-language video.",
    faqs: [
      {
        question: "Is Turkish a real feature or just translation?",
        answer:
          "It's native. Menivor writes the script directly in Turkish and renders Turkish-glyph captions — not an English script with translated subtitles.",
      },
      {
        question: "Can I switch between Turkish and English?",
        answer:
          "Yes. You pick the language per reel; the full pipeline works identically in English or Turkish.",
      },
    ],
  },
  {
    slug: "saas-demo-video-maker",
    title: "SaaS Demo Video Maker",
    keyword: "SaaS demo video maker",
    lede: "Turn a product walkthrough into a punchy UGC reel that actually gets watched.",
    body: [
      "A full product demo is great for your website and terrible for a feed. Menivor takes the same screen recording and turns it into a short, hook-led reel: a tight script, a voiceover, and captions that keep viewers watching past the first line.",
      "Because the reel is built from your actual product recording, it shows the software doing the thing — the most convincing possible proof — while the voiceover narrates the value in a UGC style.",
      "It's an efficient way for SaaS teams to produce a steady stream of feed-native demo clips without a video editor or a spokesperson.",
    ],
    highlights: [
      "Product walkthrough → feed-native reel",
      "Shows your real software in action",
      "Voiceover narration in a UGC style",
      "English or Turkish",
    ],
    bestFor: "SaaS founders and product marketers.",
    faqs: [
      {
        question: "Can I reuse one demo recording for several reels?",
        answer:
          "Yes. Vary the prompt and hook to produce different angles from the same screen recording; you only pay for successful renders.",
      },
      {
        question: "Do I need a spokesperson?",
        answer:
          "No. A natural AI voice reads the script, so no one has to appear on camera.",
      },
    ],
  },
  {
    slug: "talking-head-video-generator",
    title: "Talking-Head Style Video Generator",
    keyword: "talking-head video generator",
    lede: "Get the one-voice, one-idea explainer format without filming, using a natural AI voiceover over your content.",
    body: [
      "A talking-head video is one voice delivering one idea. Menivor gives you that format without a camera: it writes a hook-first script, narrates it with a natural AI voice and burns in word-by-word captions over your screen recording or your own selfie clip.",
      "Avatar video, a generated person speaking your script on camera, is not available in Menivor yet. If you want a face on screen today, upload a short clip of yourself as the footage and let Menivor script, voice and caption around it.",
      "Karaoke captions and native vertical export finish it into something postable.",
    ],
    highlights: [
      "A natural AI voiceover, no filming required",
      "Your own selfie clip or screen recording as the footage",
      "Hook-first script around one idea",
      "Native 9:16 export with captions",
    ],
    bestFor: "Creators who want the explainer format without filming.",
    faqs: [
      {
        question: "Does Menivor generate an on-camera avatar?",
        answer:
          "Not yet. Avatar video is not available. Menivor narrates your script over your footage, including a selfie clip if you upload one.",
      },
      {
        question: "Is the video on a blank background?",
        answer:
          "No. The narration plays over your screen recording, your clip, or a moving style scene.",
      },
    ],
  },
  {
    slug: "product-demo-to-reel",
    title: "Product Demo Video Maker",
    keyword: "product demo video maker",
    lede: "Turn a product walkthrough or screen recording into a short, narrated vertical reel.",
    body: [
      "Long demos don't perform in a vertical feed. Menivor rebuilds a demo as short-form UGC: it scripts the key moment, narrates it, and burns in karaoke captions, then exports a native 1080×1920 reel.",
      "Rather than trimming your demo down, Menivor generates a new hook-led reel around the part that matters — so the result is made for the feed, not a shrunken version of a webinar.",
      "You can produce several reels from one demo by changing the prompt, and only successful renders cost a credit.",
    ],
    highlights: [
      "Long demo → short narrated reel",
      "Hook-led script around the key moment",
      "Karaoke captions and 9:16 export",
      "Multiple reels from one recording",
    ],
    bestFor: "Teams repurposing demos and webinars for social.",
    faqs: [
      {
        question: "Does it just trim my demo?",
        answer:
          "No. It generates a new hook-led reel with a natural AI voiceover and captions around the most important moment of your demo.",
      },
    ],
  },
  {
    slug: "faceless-tiktok-video-maker",
    title: "Faceless TikTok Video Maker",
    keyword: "faceless TikTok video maker",
    lede: "Post to TikTok every day without ever showing your face: a natural AI voice narrates over your screen recording.",
    body: [
      "TikTok rewards consistency, but daily filming is the fastest way to burn out. Menivor removes the camera entirely: record your screen, write a one-line prompt, and a natural AI voice reads a hook-first script over your footage while karaoke captions carry the message with the sound off.",
      "Unlike faceless channels built from stock clips and robotic text-to-speech, a Menivor reel still shows something real — your app, your workflow, your product — so it reads as genuine content rather than an anonymous montage. Because billing is success-only, you can render several hooks per day and keep the ones the algorithm favours.",
    ],
    highlights: [
      "No camera, no filming: a natural AI voice narrates",
      "Your real screen recording as the backdrop, not stock B-roll",
      "Hook-first scripts tuned for TikTok's first three seconds",
      "Karaoke captions for sound-off For You feed viewing",
    ],
    bestFor: "Creators building a daily TikTok presence without going on camera.",
    faqs: [
      {
        question: "Will faceless videos still perform on TikTok?",
        answer:
          "Yes. TikTok ranks watch-through, and a hook-first script with a natural AI voiceover and karaoke captions is built to hold attention. Because the voiceover sits over your real screen recording, the content still feels authentic.",
      },
      {
        question: "How many faceless videos can I make?",
        answer:
          "As many as you like. One credit renders one finished reel, failed renders return the credit, and credits never expire — so daily posting stays affordable.",
      },
    ],
  },
  {
    slug: "faceless-youtube-shorts-maker",
    title: "Faceless YouTube Shorts Maker",
    keyword: "faceless YouTube Shorts maker",
    lede: "Feed the Shorts shelf without being on camera — narrated, hook-first vertical videos from a screen recording.",
    body: [
      "YouTube Shorts is a discovery engine that rewards volume and a strong opening loop. Menivor lets you supply that volume without filming: it scripts your screen recording hook-first, narrates it with a natural AI voice, and burns in karaoke captions, then exports a clean 1080×1920 MP4 ready for the Shorts shelf.",
      "Because the reel is generated from your actual recording rather than recycled stock, it can double as a channel trailer for your long-form content or your product. You can spin multiple angles from a single screen capture and only pay for the renders that finish.",
    ],
    highlights: [
      "Natural AI voiceover — no camera or microphone needed",
      "Hook-first opening built for the Shorts loop",
      "1080×1920 export ready for the Shorts shelf",
      "Multiple Shorts from one screen recording",
    ],
    bestFor: "Creators and founders feeding YouTube Shorts consistently.",
    faqs: [
      {
        question: "Do I need a YouTube channel already?",
        answer:
          "No. Menivor produces the Shorts; you download the MP4 and upload it to a new or existing channel yourself; direct posting from Menivor is not open yet.",
      },
    ],
  },
  {
    slug: "faceless-instagram-reels-maker",
    title: "Faceless Instagram Reels Maker",
    keyword: "faceless Instagram Reels maker",
    lede: "Grow on Reels without appearing on camera — a natural AI voiceover and karaoke captions do the work.",
    body: [
      "Instagram Reels favours polished, high-retention short video, and increasingly surfaces content from accounts you don't follow. Menivor builds that content faceless: a natural AI voice reads a hook-first script over your screen recording, with word-by-word karaoke captions styled for the mute-by-default Reels feed.",
      "The narrated-over-recording format keeps a Reel on-brand and product-real instead of a generic stock montage, which matters when Instagram's audience skews toward aesthetics.",
    ],
    highlights: [
      "A natural AI voiceover, no filming required",
      "Karaoke captions styled for the muted Reels feed",
      "Your real product footage behind the narration",
      "Captions in English or Turkish",
    ],
    bestFor: "Brands and creators growing on Instagram Reels without a camera.",
    faqs: [
      {
        question: "Can I match my brand look on Reels?",
        answer:
          "You control the prompt, the hook, and the style (full-frame, split screen or another one-click style), and you can clone proven templates from the marketplace as a starting point.",
      },
    ],
  },
  {
    slug: "faceless-youtube-channel-videos",
    title: "Faceless YouTube Channel Video Generator",
    keyword: "faceless YouTube channel generator",
    lede: "Run a faceless YouTube channel with a repeatable narrated video pipeline instead of stock-and-TTS montages.",
    body: [
      "Most faceless YouTube channels rely on the same three ingredients — stock footage, an AI voice, and generic captions — which is exactly why so many look identical. Menivor gives a faceless channel a differentiator: a natural AI voiceover over your own screen recording, with a hook-first script and karaoke captions timed to the narration.",
      "You can standardise your channel's format by cloning a template with a proven win-score, then remix it per video so every upload keeps the same structure while the content changes. Success-only, non-expiring credits make a high-upload-cadence channel practical.",
    ],
    highlights: [
      "Your real footage instead of stock-montage sameness",
      "Repeatable templates with a win-score",
      "Hook-first scripts and karaoke captions on every video",
      "Non-expiring credits for a high upload cadence",
    ],
    bestFor: "Faceless channel operators who want a distinctive, repeatable format.",
    faqs: [
      {
        question: "How do I keep every video consistent?",
        answer:
          "Clone a template from the marketplace and remix it per video. Each remix runs the full pipeline, so the structure stays identical while the script and recording change.",
      },
      {
        question: "Is this cheaper than hiring an editor?",
        answer:
          "You pay per finished reel with credits that never expire, and no render costs a credit unless it succeeds — so cost scales with output, not a monthly retainer.",
      },
    ],
  },
  {
    slug: "talking-head-tiktok-generator",
    title: "Talking-Head Style TikTok Generator",
    keyword: "talking-head TikTok generator",
    lede: "Make an explainer-style TikTok over your product footage with a natural AI voice. No filming, no editing.",
    body: [
      "The explainer format dominates TikTok's education and product niches because one clear voice builds trust fast. Menivor writes a hook-first script and narrates it with a natural AI voice over your product footage, with karaoke captions timed word by word.",
      "Avatar video, a generated person speaking your script on camera, is not available in Menivor yet. Use your own clip as the footage if you want a face on screen.",
    ],
    highlights: [
      "A natural AI voiceover, generated for you",
      "Your product footage or selfie clip on screen",
      "Voice and captions timed to one source",
      "Native 9:16 export",
    ],
    bestFor: "Creators who want the explainer format without filming.",
    faqs: [
      {
        question: "Does a generated person appear on screen?",
        answer:
          "No. Avatar video is not available yet. The reel is narrated over your footage, and you can upload your own clip if you want a face on it.",
      },
    ],
  },
  {
    slug: "ai-avatar-instagram-reels",
    title: "Avatar Instagram Reels (Not Available Yet)",
    keyword: "avatar Instagram Reels",
    lede: "Avatar Reels are not available in Menivor yet. Make consistent, narrated Reels over your own footage today.",
    body: [
      "Avatar video, a generated person speaking your script on camera, is not available in Menivor yet. For Instagram, what you can make today is a Reel with a hook-first script, a natural AI voiceover and karaoke captions over your screen recording or product page.",
      "Because the narration plays over your actual footage rather than a studio backdrop, the Reel stays product-real and on-brand, which suits Instagram's aesthetic-driven audience. Pick one style and keep it for a recognisable series.",
    ],
    highlights: [
      "Avatar Reels: not available yet",
      "Natural AI voiceover over your footage",
      "Karaoke captions clear of the Reels controls",
      "One render: script, voice, captions",
    ],
    bestFor: "Brands wanting a consistent narrated series on Reels.",
    faqs: [
      {
        question: "Can I keep the same voice across all my Reels?",
        answer:
          "Yes. Pick one voice and one style and reuse them, so your Reels share a recognisable format while the script and footage change per post.",
      },
    ],
  },
  {
    slug: "ai-avatar-youtube-shorts",
    title: "Avatar YouTube Shorts (Not Available Yet)",
    keyword: "avatar YouTube Shorts",
    lede: "Avatar Shorts are not available in Menivor yet. Make narrated Shorts over your own footage, exported as a clean 1080×1920 file.",
    body: [
      "YouTube Shorts rewards a strong opening and a clean, native vertical file. Menivor delivers both today: a natural AI voice narrates a hook-first script over your screen recording, and the pipeline composes a 1080×1920 MP4 with karaoke captions burned in.",
      "Avatar video, a generated person speaking your script on camera, is not available in Menivor yet. A narrated Short that shows your real product or workflow is a natural funnel into your long-form videos or your app.",
    ],
    highlights: [
      "Avatar Shorts: not available yet",
      "Hook-first opening for the Shorts loop",
      "Native 1080×1920 export, captions burned in",
      "Non-expiring, success-only credits",
    ],
    bestFor: "Creators funnelling Shorts viewers to long-form or a product.",
    faqs: [
      {
        question: "Are the captions burned in for Shorts?",
        answer:
          "Yes. Karaoke captions are burned into the MP4, so they display on the Shorts shelf without a separate subtitle track.",
      },
    ],
  },
  {
    slug: "ugc-ad-for-tiktok",
    title: "UGC Ad Maker for TikTok",
    keyword: "TikTok UGC ad maker",
    lede: "Create native-feeling TikTok UGC ads that show your product in action — at testing volume.",
    body: [
      "TikTok ads that look like ads get scrolled; ads that look like a creator's post get watched. Menivor builds the second kind: it turns your screen recording into a UGC-style ad with a hook-first script, a natural AI voiceover, and karaoke captions — the format TikTok's audience actually engages with.",
      "Because the ad is generated from your real product footage, it demonstrates the thing you're selling instead of talking about it abstractly. Success-only billing means you can render a dozen hook variations for one product and only pay for the ones that finish, which is exactly how performance creative testing should work.",
    ],
    highlights: [
      "Native, creator-style TikTok ad format",
      "Shows your real product via your screen recording",
      "Hook variations for creative testing at volume",
      "English or Turkish scripts and captions",
    ],
    bestFor: "Performance marketers testing TikTok UGC creative.",
    faqs: [
      {
        question: "How is this better for TikTok ads than a polished brand video?",
        answer:
          "TikTok users skip content that looks like an ad. A UGC-style reel with a hook, a natural AI voiceover, and karaoke captions blends into the feed and shows the product in use, which typically holds attention longer.",
      },
      {
        question: "Can I test many hooks per product?",
        answer:
          "Yes. Billing is success-only and credits never expire, so you can render many hook variations and keep the winners.",
      },
    ],
  },
  {
    slug: "ugc-ad-for-instagram",
    title: "UGC Ad Maker for Instagram",
    keyword: "Instagram UGC ad maker",
    lede: "Generate Instagram UGC ads that feel like a recommendation, not a banner.",
    body: [
      "On Instagram, the highest-performing paid creative is often indistinguishable from organic Reels. Menivor produces that look: a natural AI voice reads a hook-first script over your product recording, with karaoke captions styled for the muted feed, so the ad sits naturally between organic posts.",
      "The screen-recording foundation means the ad proves the product visually, and the pay-per-reel model lets you build a whole ad set of variations without a subscription.",
    ],
    highlights: [
      "Organic-feeling Reels ad format",
      "Karaoke captions for the muted feed",
      "Real product footage as proof",
      "Scripts in English or Turkish",
    ],
    bestFor: "Advertisers running Instagram Reels UGC creative.",
    faqs: [
      {
        question: "Can I produce a full ad set of variations?",
        answer:
          "Yes. Vary the prompt and hook to generate multiple ad variations from one recording, and only pay for the renders that succeed.",
      },
    ],
  },
  {
    slug: "ugc-ad-for-facebook-ads",
    title: "UGC Ad Maker for Facebook & Meta Ads",
    keyword: "Facebook UGC ad maker",
    lede: "Produce UGC-style vertical creative for Meta ads without hiring creators or filming.",
    body: [
      "Meta's ad auction favours creative that stops the scroll, and UGC-style video often does better than polished brand spots. Menivor generates that creative from a screen recording: a hook-first script, a natural AI voiceover over your footage, and karaoke captions, exported as native 9:16 video that fits Reels, Stories, and the Feed placements.",
      "Instead of briefing and paying UGC creators for every variation, you render as many as you need and pay only for successful outputs. That makes systematic creative testing — the single biggest lever in Meta ad performance — dramatically cheaper.",
    ],
    highlights: [
      "Native 9:16 creative for Meta placements",
      "UGC format that stops the scroll",
      "Systematic variation testing at low cost",
      "No creator sourcing or filming",
    ],
    bestFor: "Media buyers who need a constant supply of Meta ad creative.",
    faqs: [
      {
        question: "What placements does the output fit?",
        answer:
          "Menivor exports native 1080×1920 vertical video, which fits Reels, Stories, and vertical Feed placements across Meta.",
      },
    ],
  },
  {
    slug: "tiktok-ad-maker",
    title: "TikTok Ad Maker",
    keyword: "TikTok ad maker",
    lede: "Turn a screen recording into a scroll-stopping TikTok ad with a natural AI voiceover and captions.",
    body: [
      "A good TikTok ad earns its watch time in the first second and never feels like a commercial. Menivor's pipeline is built for exactly that: a hook-first script, a natural AI voiceover delivering it over your product recording, and karaoke captions that keep the message readable with the sound off.",
      "Because everything is generated from your recording and a prompt, you can produce a steady stream of ad variations for split-testing without a studio, a spokesperson, or an editor — and only successful renders cost a credit.",
    ],
    highlights: [
      "Hook-first script for the first second",
      "Natural AI voiceover over your product footage",
      "Karaoke captions for sound-off viewing",
      "Variation testing without a studio",
    ],
    bestFor: "Brands and marketers producing TikTok ad creative in volume.",
    faqs: [
      {
        question: "Do I need actors or a studio?",
        answer:
          "No. A natural AI voice reads the script over your screen recording, so no filming, actors, or studio setup is required.",
      },
    ],
  },
  {
    slug: "instagram-reels-maker",
    title: "Instagram Reels Maker",
    keyword: "Instagram Reels maker",
    lede: "Turn a screen recording and a prompt into a polished, narrated Instagram Reel.",
    body: [
      "A raw screen recording is too long and too flat for the Reels feed. Menivor rebuilds it as a Reel: a hook-first script, a natural AI voice narration over your footage, and karaoke captions burned in — exported as a native 1080×1920 MP4 ready to post.",
      "The result is feed-native rather than a shrunken desktop demo, and because it's built from your real recording it stays product-authentic. Download the MP4 and post it to Instagram Reels; direct posting from Menivor is not open yet.",
    ],
    highlights: [
      "Hook-first Reel from a screen recording",
      "Natural AI voiceover and karaoke captions built in",
      "Native 1080×1920 export",
      "A finished MP4 ready to upload to Reels",
    ],
    bestFor: "Anyone turning product recordings into Instagram Reels.",
    faqs: [
      {
        question: "Can I post straight to Instagram from Menivor?",
        answer:
          "Not yet. Direct posting is not open; once a reel renders, download the MP4 and post it yourself.",
      },
    ],
  },
  {
    slug: "youtube-shorts-maker",
    title: "YouTube Shorts Maker",
    keyword: "YouTube Shorts maker",
    lede: "Turn a screen recording into a hook-first, narrated YouTube Short with captions burned in.",
    body: [
      "Menivor is a purpose-built Shorts pipeline: drop in a screen recording, add a prompt, and get back a 1080×1920 Short with a hook-first script, a natural AI voiceover and karaoke captions. It's designed for the Shorts loop, where a weak opening kills reach.",
      "Rather than trimming a long video into a Short, Menivor generates a new reel around the moment that matters, so it's made for the shelf instead of being a cut-down webinar. Non-expiring credits keep a steady publishing cadence affordable.",
    ],
    highlights: [
      "Purpose-built for the Shorts loop",
      "Hook-first script and a natural AI voiceover",
      "Karaoke captions burned into the MP4",
      "Non-expiring, success-only credits",
    ],
    bestFor: "Creators and teams publishing YouTube Shorts regularly.",
    faqs: [
      {
        question: "Does it clip my long videos into Shorts?",
        answer:
          "No. Menivor generates a new narrated Short from a screen recording and a prompt, built around the key moment rather than cut from existing footage.",
      },
    ],
  },
  {
    slug: "explainer-video-generator",
    title: "AI Explainer Video Generator",
    keyword: "AI explainer video generator",
    lede: "Explain how something works with a natural AI voiceover over a real screen recording.",
    body: [
      "The best explainers show the thing while a voice explains the why. Menivor produces exactly that: it scripts your screen recording hook-first, narrates it with a natural AI voice, and burns in karaoke captions so each step is easy to follow with or without sound.",
      "Because the explainer is built on your actual recording rather than generic animation, viewers see the real interface or product, which makes the explanation concrete. It's ideal for onboarding clips, feature explainers, and how-it-works reels.",
    ],
    highlights: [
      "Voiceover narration over a real screen recording",
      "Hook-first structure so viewers stay",
      "Karaoke captions for step-by-step clarity",
      "Native vertical export for social",
    ],
    bestFor: "Product and marketing teams explaining how something works.",
    faqs: [
      {
        question: "Is this animation or real footage?",
        answer:
          "It's built from your real screen recording with a natural AI voiceover over it, not generic animation, so viewers see the actual product.",
      },
    ],
  },
  {
    slug: "product-demo-tiktok",
    title: "Product Demo Video for TikTok",
    keyword: "product demo TikTok video",
    lede: "Turn a product walkthrough into a punchy, narrated TikTok that actually gets watched.",
    body: [
      "A full walkthrough is great for your website and dead on arrival in a TikTok feed. Menivor reshapes it: it scripts the single most compelling moment hook-first, narrates it over the recording, and burns in karaoke captions — a feed-native demo instead of a shrunken tutorial.",
      "Since the reel shows your product doing the thing, it's the most convincing proof you can offer, and the UGC framing keeps it native to TikTok. Render several angles from one walkthrough and keep the ones that land.",
    ],
    highlights: [
      "Walkthrough reshaped into a feed-native demo",
      "Hook-first around the key moment",
      "Natural AI voiceover and karaoke captions",
      "Multiple angles from one recording",
    ],
    bestFor: "Founders and product marketers demoing on TikTok.",
    faqs: [
      {
        question: "Can I get several TikToks from one demo recording?",
        answer:
          "Yes. Change the prompt and hook to generate different angles from the same walkthrough; you only pay for successful renders.",
      },
    ],
  },
  {
    slug: "app-demo-video-maker",
    title: "App Demo Video Maker",
    keyword: "app demo video maker",
    lede: "Show your app in action with a narrated vertical reel built from a screen recording.",
    body: [
      "Screen-record your app doing something useful, add a prompt, and Menivor turns it into a demo reel: a hook-first script, a natural AI voice narration over your recording, and karaoke captions, exported native 9:16. It's the fastest way to show, not tell, what your app does.",
      "The narrated-over-recording format works whether you're promoting on social, embedding on a landing page, or building an App Store preview companion. Because it's generated from your real screens, every claim is visually backed.",
    ],
    highlights: [
      "Your real app screens as the footage",
      "Voiceover narration and karaoke captions",
      "Native 9:16 reel for social or landing pages",
      "Multiple reels from one recording",
    ],
    bestFor: "App founders and mobile marketers.",
    faqs: [
      {
        question: "Can I use this for an App Store preview?",
        answer:
          "The 9:16 output is ideal for social; for App Store previews you can adapt the same recording and messaging, though store previews have their own format requirements to follow.",
      },
    ],
  },
  {
    slug: "testimonial-video-generator",
    title: "Customer Review Video Generator",
    keyword: "customer review video generator",
    lede: "Turn a real customer review or story into a UGC-style reel with a natural AI voiceover.",
    body: [
      "Written reviews rarely travel in a video feed. Menivor converts the message into a UGC-style review reel: a hook-first script based on the review, delivered by a natural AI voiceover over your product recording, with karaoke captions — so the proof shows the product while the voiceover tells the outcome.",
      "This keeps customer stories honest and on-brand: use real customer quotes, with the customer's permission, as the script source, and let the voiceover and your own footage carry them. It's a scalable way to turn a backlog of reviews into social-ready proof.",
    ],
    highlights: [
      "Real written reviews reshaped into short reels",
      "Natural AI voiceover over your product footage",
      "Karaoke captions for sound-off viewing",
      "Scale a review backlog into social proof",
    ],
    bestFor: "Brands turning real customer reviews and stories into video.",
    faqs: [
      {
        question: "Does Menivor invent customer quotes?",
        answer:
          "No. You supply the message from real customer quotes you have permission to use, and Menivor formats it into a reel. Keep the content truthful and disclose AI-generated content where your platform or local rules require it.",
      },
    ],
  },
  {
    slug: "tutorial-video-generator",
    title: "AI Tutorial Video Generator",
    keyword: "AI tutorial video generator",
    lede: "Turn a how-to screen recording into a tight, narrated tutorial reel.",
    body: [
      "Tutorials live and die on clarity and pacing. Menivor takes your how-to screen recording and a prompt, writes a hook-first script that front-loads the payoff, narrates it with a natural AI voice, and burns in karaoke captions so each step is readable at a glance.",
      "Because the tutorial is built on your real recording, viewers follow along on the actual interface rather than an illustration. It's ideal for quick tips, feature how-tos, and educational short-form that funnels into deeper content.",
    ],
    highlights: [
      "Hook-first structure that front-loads the payoff",
      "Real interface footage, step by step",
      "Karaoke captions for at-a-glance following",
      "Native vertical export for social",
    ],
    bestFor: "Educators and product teams making short how-to content.",
    faqs: [
      {
        question: "Is this better than a plain screen recording?",
        answer:
          "Yes for social. A raw recording has no hook, narration, or captions; Menivor adds all three, turning it into a tutorial reel built for the feed.",
      },
    ],
  },
  {
    slug: "how-to-video-maker",
    title: "How-To Video Maker",
    keyword: "how-to video maker",
    lede: "Make a clear, narrated how-to reel from a screen recording in one pass.",
    body: [
      "Menivor turns a screen recording of a process into a how-to reel: a structured, hook-first script, a natural AI voice narration over the footage, and karaoke captions — all in a single render. No timeline editing, no separate voiceover session.",
      "The format suits any 'here's how to do X' content where showing the steps on a real screen beats describing them. Pair it with the SPARK idea engine to pull fresh how-to angles instead of starting from a blank page.",
    ],
    highlights: [
      "Structured how-to script, hook-first",
      "Voiceover narration over your real screens",
      "Karaoke captions on every step",
      "SPARK idea engine for fresh angles",
    ],
    bestFor: "Anyone teaching a process on social.",
    faqs: [
      {
        question: "Do I have to record the voiceover myself?",
        answer:
          "No. Menivor narrates the script with a natural AI voice, so you never record your own audio.",
      },
    ],
  },
  {
    slug: "listicle-video-generator",
    title: "Listicle Video Generator",
    keyword: "listicle video generator",
    lede: "Turn a 'top 5' idea into a fast, narrated listicle reel with karaoke captions.",
    body: [
      "Listicles — 'top 5 tools', '3 mistakes', '7 tips' — are reliable short-form formats because the structure itself creates retention. Menivor scripts a listicle hook-first, narrates each item over your screen recording so each point can show something real.",
      "Karaoke captions keep the countdown readable with the sound off, and because the list structure is repeatable, you can turn a single theme into a whole series by changing the prompt. Only finished renders cost a credit.",
    ],
    highlights: [
      "Hook-first listicle structure for retention",
      "Voiceover narration per list item",
      "Karaoke captions for the countdown",
      "Repeatable format for a whole series",
    ],
    bestFor: "Creators who post recurring listicle content.",
    faqs: [
      {
        question: "Can I turn one topic into a series?",
        answer:
          "Yes. The listicle structure is repeatable — change the prompt to generate new lists on the same theme, and pay only for successful renders.",
      },
    ],
  },
  {
    slug: "fitness-video-generator",
    title: "Fitness Content Video Generator",
    keyword: "fitness video generator AI",
    lede: "Post fitness tips, program breakdowns, and offers without filming yourself at the gym.",
    body: [
      "Fitness creators post constantly, and not every idea justifies a filmed clip. Menivor lets coaches and fitness brands ship tip reels, program explainers, and offer promos narrated over a screen recording — a workout plan, an app, a booking flow — plus karaoke captions for the muted feed.",
      "It's a practical way to keep a fitness account active between filmed content, and test hooks for a challenge or program launch — in English or Turkish.",
    ],
    highlights: [
      "Tip, program, and offer reels without filming",
      "Natural AI voiceover over your app or plan",
      "Karaoke captions for the muted feed",
      "English or Turkish scripts",
    ],
    bestFor: "Fitness coaches and brands posting between filmed content.",
    faqs: [
      {
        question: "Can I promote a program or challenge?",
        answer:
          "Yes. Use the prompt to frame a program or challenge, and render several hook variations to find the one that converts.",
      },
    ],
  },
  {
    slug: "finance-video-generator",
    title: "Finance & Fintech Video Generator",
    keyword: "finance video generator AI",
    lede: "Explain a finance concept, product, or fintech feature with a narrated reel.",
    body: [
      "Finance content rewards clarity and trust, and a clear narrated walkthrough delivers both. Menivor scripts a finance explainer hook-first, narrates it over your screen recording — a fintech app, a dashboard, a chart — with karaoke captions so a dense concept stays followable.",
      "For fintech marketers, the screen-recording foundation means you can show the real product while the voiceover explains the value. Keep claims accurate and add any disclosures your jurisdiction requires.",
    ],
    highlights: [
      "Hook-first explainers for dense concepts",
      "Voiceover over a real app or dashboard",
      "Karaoke captions for followability",
      "Scripts in English or Turkish",
    ],
    bestFor: "Fintech marketers and finance educators.",
    faqs: [
      {
        question: "Can it show my fintech app?",
        answer:
          "Yes. Record the app, and Menivor narrates over that footage so viewers see the real product while the concept is explained.",
      },
    ],
  },
  {
    slug: "ecommerce-product-video-maker",
    title: "E-commerce Product Video Maker",
    keyword: "ecommerce product video maker",
    lede: "Turn a product screen recording into a UGC-style reel that sells.",
    body: [
      "E-commerce conversions rise when shoppers see a product in use, not just in a photo. Menivor turns a screen recording — a product page, an unboxing capture, an app flow — into a UGC-style reel with a hook-first script, a natural AI voiceover, and karaoke captions, exported native 9:16 for social and ads.",
      "The pay-per-reel model suits catalogues: render a reel per SKU or per angle and pay only for finished outputs.",
    ],
    highlights: [
      "UGC-style reels that show the product in use",
      "Natural AI voiceover and karaoke captions",
      "Practical per-SKU economics",
      "Scripts in English or Turkish",
    ],
    bestFor: "E-commerce brands and sellers producing product video.",
    faqs: [
      {
        question: "Can I make a reel for every product?",
        answer:
          "Yes. Render one per SKU or angle; success-only, non-expiring credits make catalogue-scale production practical.",
      },
    ],
  },
  {
    slug: "real-estate-video-maker",
    title: "Real Estate Video Maker",
    keyword: "real estate video maker AI",
    lede: "Turn a listing walkthrough or screen recording into a narrated property reel.",
    body: [
      "Real estate lives on video, but not every agent wants to be on camera for every listing. Menivor generates a property reel from a screen recording — a listing page, a floor-plan tool, a virtual tour capture — with a hook-first script, a natural AI voiceover, and karaoke captions, in a native vertical format.",
      "Agents can keep a consistent presence across listings without filming each one, and test hooks for a hot property — in English or Turkish. Keep every claim about a property accurate and compliant.",
    ],
    highlights: [
      "Property reels without filming every listing",
      "Natural AI voiceover over a listing or tour capture",
      "Karaoke captions for the muted feed",
      "English or Turkish scripts",
    ],
    bestFor: "Real estate agents and agencies producing listing video.",
    faqs: [
      {
        question: "Do I need to film each property?",
        answer:
          "No. Screen-record a listing page or virtual tour, and Menivor narrates over it — no on-camera filming required per listing.",
      },
    ],
  },
  {
    slug: "restaurant-video-maker",
    title: "Restaurant & Local Business Video Maker",
    keyword: "restaurant video maker AI",
    lede: "Promote a menu, offer, or reservation flow with a narrated social reel.",
    body: [
      "Restaurants and local businesses need a steady stream of social video but rarely have a content team. Menivor lets an owner or manager screen-record a menu, a booking page, or a delivery app and turn it into a promo reel with a hook-first script, a natural AI voiceover, and karaoke captions — no filming, no editor.",
      "It's fast enough to promote a daily special or a weekend offer.",
    ],
    highlights: [
      "Promo reels for menus, offers, and bookings",
      "Natural AI voiceover — no filming required",
      "Fast enough for daily specials",
      "Scripts in English or Turkish",
    ],
    bestFor: "Restaurants and local businesses running their own social.",
    faqs: [
      {
        question: "Is this practical for a small business owner?",
        answer:
          "Yes. Record a screen, write one line, and Menivor handles the script, voice, and captions, with no editing skills needed.",
      },
    ],
  },
  {
    slug: "coach-content-video-maker",
    title: "Coach & Creator Content Video Maker",
    keyword: "coach content video maker",
    lede: "Ship coaching tips, offers, and lead magnets as narrated reels between filmed content.",
    body: [
      "Coaches and personal-brand creators need volume to stay top-of-mind, but filming every idea isn't realistic. Menivor lets you turn a screen recording — a workbook, a booking calendar, a course dashboard — into a reel with a hook-first script, a natural AI voiceover, and karaoke captions, so you can post daily without being on camera daily.",
      "Use it to test hooks for a lead magnet, explain a framework, or promote a program, and pull fresh angles from the SPARK idea engine when you run dry.",
    ],
    highlights: [
      "Daily reels without daily filming",
      "Natural AI voiceover over your materials",
      "SPARK idea engine for fresh angles",
      "English or Turkish delivery",
    ],
    bestFor: "Coaches and personal-brand creators posting at volume.",
    faqs: [
      {
        question: "Can I still mix in my own filmed videos?",
        answer:
          "Absolutely. Menivor is ideal for the days you can't film, keeping your account active with narrated reels between your own on-camera content.",
      },
    ],
  },
  {
    slug: "saas-marketing-video-maker",
    title: "SaaS Marketing Video Maker",
    keyword: "SaaS marketing video maker",
    lede: "Produce a steady stream of feed-native SaaS marketing reels from product recordings.",
    body: [
      "SaaS teams need constant marketing video — feature launches, use-case explainers, comparison reels — but a design or video hire rarely keeps up. Menivor turns product screen recordings into narrated reels with hook-first scripts and karaoke captions, so marketing can ship social video on its own cadence.",
      "Because each reel is built from real product footage, it doubles as proof, and templates with a win-score let you standardise a repeatable format across the whole content calendar.",
    ],
    highlights: [
      "Feature, use-case, and comparison reels",
      "Real product footage as proof",
      "Repeatable templates with a win-score",
      "No design or video hire required",
    ],
    bestFor: "SaaS marketing teams shipping social video regularly.",
    faqs: [
      {
        question: "Can marketing run this without a video editor?",
        answer:
          "Yes. A screen recording and a prompt are enough; Menivor handles script, voice, captions, and compose in one render.",
      },
    ],
  },
  {
    slug: "course-promo-video-maker",
    title: "Online Course Promo Video Maker",
    keyword: "course promo video maker",
    lede: "Promote a course or cohort with a narrated reel built from your curriculum screens.",
    body: [
      "Course creators need promo video that shows what's inside without a full production. Menivor turns a screen recording of your curriculum, platform, or lesson into a promo reel with a hook-first script, a natural AI voiceover, and karaoke captions — feed-native and ready to run as organic or paid.",
      "Test different value-prop hooks for a launch, produce a reel per module. Only finished renders cost a credit, so launch-week experimentation stays cheap.",
    ],
    highlights: [
      "Promo reels from your curriculum screens",
      "Natural AI voiceover and karaoke captions",
      "Hook testing for launches",
      "Scripts in English or Turkish",
    ],
    bestFor: "Course creators and educators promoting cohorts.",
    faqs: [
      {
        question: "Can I make a reel per module?",
        answer:
          "Yes. Record each module's screen and generate a reel per module; non-expiring credits make a full series affordable.",
      },
    ],
  },
  {
    slug: "app-store-preview-video-maker",
    title: "App Preview & Promo Video Maker",
    keyword: "app preview video maker",
    lede: "Turn app screen recordings into narrated promo reels for social and stores.",
    body: [
      "App marketers need short, punchy video that shows the app in seconds. Menivor takes your app screen recording and generates a promo reel with a hook-first script, a natural AI voiceover, and karaoke captions, exported native 9:16 for TikTok, Reels, Shorts, and paid social.",
      "The narrated-over-recording format shows the real UI while selling the benefit, and you can render variations for different audiences or features. For store previews specifically, follow each store's own format and content requirements.",
    ],
    highlights: [
      "Promo reels from real app footage",
      "Natural AI voiceover and karaoke captions",
      "Native 9:16 for social and paid",
      "Variations per audience or feature",
    ],
    bestFor: "App marketers producing promo and social video.",
    faqs: [
      {
        question: "Does this replace an official App Store preview?",
        answer:
          "It's built for social and paid promo. Store previews have specific format and content rules, so adapt the recording and messaging to each store's requirements.",
      },
    ],
  },
  {
    slug: "shopify-product-video-maker",
    title: "Shopify Product Video Maker",
    keyword: "Shopify product video maker",
    lede: "Turn a Shopify product page recording into a UGC-style reel for ads and social.",
    body: [
      "Shopify stores convert better with video, and UGC-style product reels are the workhorse of DTC advertising. Menivor turns a screen recording of your product page or app into a reel with a hook-first script, a natural AI voiceover, and karaoke captions — native 9:16 for Reels, TikTok, and Meta ads.",
      "Per-SKU economics make it practical to build a reel for every product.",
    ],
    highlights: [
      "UGC reels from a product-page recording",
      "Natural AI voiceover and karaoke captions",
      "Per-SKU production economics",
      "Scripts in English or Turkish",
    ],
    bestFor: "Shopify and DTC merchants producing product video.",
    faqs: [
      {
        question: "Can I make ads for every product?",
        answer:
          "Yes. Render a reel per product or angle and pay only for finished outputs, which keeps catalogue-scale ad production affordable.",
      },
    ],
  },
  {
    slug: "crypto-video-generator",
    title: "Crypto & Web3 Video Generator",
    keyword: "crypto video generator AI",
    lede: "Explain a token, dApp, or feature with a narrated reel — no camera required.",
    body: [
      "Crypto and Web3 audiences move on short-form video, and a clear walkthrough of the real product builds the trust the space often lacks. Menivor scripts a hook-first explainer, narrates it over your screen recording — a dApp, a chart, a wallet flow — with karaoke captions for followability.",
      "It's a fast way to ship explainers and updates without filming. Keep claims accurate and add risk disclosures where required — never promise returns.",
    ],
    highlights: [
      "Hook-first explainers for complex topics",
      "Voiceover over a real dApp or chart",
      "Karaoke captions for followability",
      "Scripts in English or Turkish",
    ],
    bestFor: "Web3 projects and crypto educators.",
    faqs: [
      {
        question: "Can I show my dApp or protocol?",
        answer:
          "Yes. Record the interface, and Menivor narrates over it. Keep all claims accurate and include any disclosures your jurisdiction requires.",
      },
    ],
  },
  {
    slug: "beauty-product-ugc-generator",
    title: "Beauty & Skincare UGC Generator",
    keyword: "beauty UGC video generator",
    lede: "Create UGC-style beauty and skincare reels that feel like a recommendation.",
    body: [
      "Beauty and skincare thrive on UGC that feels personal, not produced. Menivor builds that feel from a screen recording — a product page, an ingredient breakdown, an app — with a hook-first script, a natural AI voiceover, and karaoke captions styled for the muted, aesthetic-driven feed.",
      "Test routine hooks, before/after framings, and offer angles at volume. Keep every product claim truthful and compliant with advertising rules.",
    ],
    highlights: [
      "Personal-feeling UGC beauty reels",
      "Natural AI voiceover and karaoke captions",
      "Hook and angle testing at volume",
      "Scripts in English or Turkish",
    ],
    bestFor: "Beauty and skincare brands producing UGC creative.",
    faqs: [
      {
        question: "Can I test different angles?",
        answer:
          "Yes. Render multiple hook and framing variations from one recording and keep the ones that perform; you only pay for successful renders.",
      },
    ],
  },
  {
    slug: "agency-ugc-video-generator",
    title: "Agency UGC Video Generator",
    keyword: "agency UGC video generator",
    lede: "Produce client UGC reels at volume without sourcing creators for every brief.",
    body: [
      "Agencies win on turnaround and creative volume, and creator sourcing is the bottleneck. Menivor lets an agency produce UGC-style reels for clients from a screen recording and a prompt — hook-first script, natural AI voiceover, karaoke captions — so you can ship a full creative test batch in the time it used to take to brief one creator.",
      "Success-only, non-expiring credits fit project-based billing. Templates with a win-score help you standardise a repeatable house style across clients.",
    ],
    highlights: [
      "Client reels without creator sourcing",
      "Full creative test batches, fast",
      "Repeatable house style via templates",
      "Scripts in English or Turkish",
    ],
    bestFor: "Marketing and creative agencies serving multiple clients.",
    faqs: [
      {
        question: "Does this fit project-based billing?",
        answer:
          "Yes. Credits are purchased and never expire, and you only spend one per finished reel, which maps cleanly to per-project or per-client budgets.",
      },
    ],
  },
  {
    slug: "affiliate-marketing-video-maker",
    title: "Affiliate Marketing Video Maker",
    keyword: "affiliate marketing video maker",
    lede: "Promote affiliate products with narrated review and demo reels at scale.",
    body: [
      "Affiliate marketing is a volume game: more product reels, more clicks. Menivor lets you turn a screen recording of a product or landing page into a review or demo reel with a hook-first script, a natural AI voiceover, and karaoke captions — without filming yourself for every offer.",
      "Spin up a reel per product across your affiliate portfolio, test hooks to find what converts, and publish across TikTok, Reels, and Shorts. Keep disclosures honest and mark affiliate relationships as your platform requires.",
    ],
    highlights: [
      "Review and demo reels per offer",
      "Natural AI voiceover — no filming",
      "Hook testing for conversion",
      "Publish across TikTok, Reels, Shorts",
    ],
    bestFor: "Affiliate marketers running multiple offers.",
    faqs: [
      {
        question: "Can I scale across many products?",
        answer:
          "Yes. Generate a reel per product and pay only for finished renders, which keeps a large affiliate portfolio affordable to cover.",
      },
    ],
  },
  {
    slug: "lead-gen-video-ad-maker",
    title: "Lead-Gen Video Ad Maker",
    keyword: "lead generation video ad maker",
    lede: "Create UGC-style lead-gen video ads that drive sign-ups and demo requests.",
    body: [
      "Lead-gen creative needs a sharp hook and a clear offer, delivered in a format that fits the feed. Menivor generates a lead-gen reel from a screen recording — a landing page, a form, a product — with a hook-first script, a natural AI voiceover, and karaoke captions, exported native 9:16 for paid social.",
      "Because it's cheap to produce variations, you can systematically test hooks and offers to lower cost-per-lead.",
    ],
    highlights: [
      "Hook-first lead-gen reels",
      "Natural AI voiceover over your funnel screens",
      "Cheap variation testing for lower CPL",
      "Scripts in English or Turkish",
    ],
    bestFor: "B2B and B2C marketers running lead-gen campaigns.",
    faqs: [
      {
        question: "How does this lower cost-per-lead?",
        answer:
          "By making variation testing cheap: render many hook and offer variations, run them, and scale the winners. You only pay for renders that finish.",
      },
    ],
  },
  {
    slug: "product-launch-video-maker",
    title: "Product Launch Video Maker",
    keyword: "product launch video maker",
    lede: "Announce a launch with a narrated hype reel built from your product screens.",
    body: [
      "A launch needs video the moment it goes live, across every channel. Menivor turns a screen recording of the new product or feature into a launch reel with a hook-first script, a natural AI voiceover, and karaoke captions, exported native 9:16 for social and ads — ready on launch day, not a week later.",
      "Render variations for different audiences and channels, and reuse the same recording for a teaser, an announcement, and a walkthrough.",
    ],
    highlights: [
      "Launch-day reels from product screens",
      "Natural AI voiceover and karaoke captions",
      "Teaser, announcement, and walkthrough variants",
      "Scripts in English or Turkish",
    ],
    bestFor: "Teams launching a product or major feature.",
    faqs: [
      {
        question: "Can I make several launch assets from one recording?",
        answer:
          "Yes. Change the prompt to produce a teaser, an announcement, and a walkthrough from the same screen recording.",
      },
    ],
  },
  {
    slug: "feature-announcement-video-maker",
    title: "Feature Announcement Video Maker",
    keyword: "feature announcement video maker",
    lede: "Ship a crisp 'what's new' reel every time you release a feature.",
    body: [
      "Shipping a feature without a video is a missed growth loop. Menivor turns a screen recording of the new feature into a 'what's new' reel with a hook-first script, a natural AI voiceover, and karaoke captions — fast enough to publish alongside the release notes.",
      "The narrated-over-recording format shows the feature working while the voiceover explains the benefit, and a repeatable template keeps every announcement on-brand. Only finished renders cost a credit.",
    ],
    highlights: [
      "'What's new' reels on release day",
      "Feature shown working, benefit explained",
      "Repeatable, on-brand template",
      "Success-only credits",
    ],
    bestFor: "Product and growth teams announcing releases.",
    faqs: [
      {
        question: "Can I standardise the announcement format?",
        answer:
          "Yes. Clone a template with a win-score and remix it per release so every feature announcement follows the same structure.",
      },
    ],
  },
  {
    slug: "onboarding-video-maker",
    title: "Onboarding Video Maker",
    keyword: "onboarding video maker",
    lede: "Turn a setup screen recording into a friendly, narrated onboarding reel.",
    body: [
      "New users drop off when setup feels unclear. Menivor turns a screen recording of your onboarding flow into a guided reel with a hook-first script, a natural AI voiceover, and karaoke captions, so users can watch the exact steps on the real interface.",
      "Use it for in-app welcome clips, help-centre reels, or social 'getting started' content, and produce a version per feature or persona. The narrated-over-recording format keeps it human without a filmed host.",
    ],
    highlights: [
      "Guided onboarding on the real interface",
      "Natural AI voiceover and karaoke captions",
      "Versions per feature or persona",
      "No filmed host required",
    ],
    bestFor: "Product and success teams reducing onboarding drop-off.",
    faqs: [
      {
        question: "Where can I use onboarding reels?",
        answer:
          "In-app welcome flows, help-centre articles, and social 'getting started' content — the 9:16 output works across all of them.",
      },
    ],
  },
  {
    slug: "faq-video-generator",
    title: "FAQ Video Generator",
    keyword: "FAQ video generator",
    lede: "Answer your top questions as short, narrated reels instead of a wall of text.",
    body: [
      "FAQs buried in text rarely get read. Menivor turns each common question into a short reel: a hook-first script that states the question and answers it, delivered by a natural AI voiceover over a relevant screen recording, with karaoke captions for skimmability.",
      "Build a whole FAQ series from your support inbox, publish them to social and your help centre. Pull fresh question angles from the SPARK idea engine when you run out.",
    ],
    highlights: [
      "One reel per common question",
      "Natural AI voiceover over relevant footage",
      "Karaoke captions for skimmability",
      "A full FAQ series from your inbox",
    ],
    bestFor: "Support and marketing teams turning FAQs into video.",
    faqs: [
      {
        question: "Can I turn my whole FAQ into a series?",
        answer:
          "Yes. Generate one reel per question; non-expiring, success-only credits make a full series practical to produce.",
      },
    ],
  },
  {
    slug: "ai-spokesperson-video-generator",
    title: "Spokesperson Video Generator (Not Available Yet)",
    keyword: "spokesperson video generator",
    lede: "A generated on-camera spokesperson is not available in Menivor yet. Give your brand a consistent voice today instead.",
    body: [
      "Avatar video, a generated person speaking your script on camera, is not available in Menivor yet. A recurring brand voice still makes a brand recognisable: Menivor narrates your hook-first script with the same natural AI voice across every reel, over your screen recording, with karaoke captions.",
      "Because the narration plays over your actual product footage, each video shows something real, and a consistent style keeps the brand format stable, in English or Turkish.",
    ],
    highlights: [
      "On-camera spokesperson: not available yet",
      "The same natural AI voice across reels",
      "Your real footage on screen",
      "English or Turkish narration",
    ],
    bestFor: "Brands wanting a recognisable, recurring voice.",
    faqs: [
      {
        question: "Do I need to disclose AI narration?",
        answer:
          "Follow the disclosure rules of your platform and jurisdiction. Menivor produces the reel; keeping the content truthful and disclosed where required is up to you.",
      },
    ],
  },
  {
    slug: "vertical-video-generator",
    title: "Vertical Video Generator",
    keyword: "vertical video generator",
    lede: "Generate native 1080×1920 vertical video with a natural AI voiceover and captions in one pass.",
    body: [
      "Everything about Menivor is built for vertical: the styles, the caption styling, and the compose step all target a native 1080×1920 frame, so you never crop or letterbox a landscape video to fit a feed.",
      "Drop in a screen recording, add a prompt, and get back a vertical reel with a hook-first script, a natural AI voice narration, and karaoke captions — ready for TikTok, Reels, and Shorts without any reframing.",
    ],
    highlights: [
      "Native 1080×1920, never cropped landscape",
      "Styles designed for vertical",
      "Karaoke captions styled for mobile",
      "Ready for TikTok, Reels, and Shorts",
    ],
    bestFor: "Anyone who needs true vertical video, not reframed landscape.",
    faqs: [
      {
        question: "Will my video be cropped from a landscape source?",
        answer:
          "No. Menivor composes a native 1080×1920 vertical frame, with the voiceover and captions laid out for vertical rather than reframed from a wide video.",
      },
    ],
  },
  {
    slug: "short-form-video-generator",
    title: "Short-Form Video Generator",
    keyword: "short-form video generator",
    lede: "One pipeline for every short-form platform — narrated reels from a screen recording.",
    body: [
      "Short-form is now the default format across TikTok, Reels, and Shorts, and the winning structure is the same everywhere: a strong hook, a clear voice, and readable captions. Menivor generates all three from a screen recording — a hook-first script, a natural AI voiceover, and karaoke captions — in a single 1080×1920 render.",
      "Instead of stitching a script tool, a voice tool, and a caption editor, you run one pipeline and post the same reel across every platform. Success-only, non-expiring credits keep a multi-platform cadence affordable.",
    ],
    highlights: [
      "One pipeline for TikTok, Reels, and Shorts",
      "Hook, voiceover, and karaoke captions in one render",
      "No tool-stitching across four apps",
      "Non-expiring, success-only credits",
    ],
    bestFor: "Creators and teams publishing across every short-form platform.",
    faqs: [
      {
        question: "Can I use the same reel on every platform?",
        answer:
          "Yes. The native 1080×1920 output works across TikTok, Instagram Reels, and YouTube Shorts, and you download it once and post it to each; direct posting from Menivor is not open yet.",
      },
    ],
  },
  {
    slug: "reel-script-templates",
    title: "Instagram Reel Script Templates",
    keyword: "instagram reel script template",
    lede: "Twelve fill-in-the-blank script templates by niche — read them, swap in your own words, then render the result as a reel.",
    body: [
      "A template is faster than a blank page: the structure (hook, three beats, call to action) is already decided, so the only work left is filling in your own specifics. Each template below names the niche it fits best and the blank you need to fill, in brackets.",
      "None of these are meant to be read word for word on camera. Swap the bracketed part for your own product, result or story, say it in your own voice, and the rhythm of the template does the rest.",
      "Once a template reads right out loud, the fastest next step is the TikTok script generator, which turns the same idea into a full timed script with beats and on-screen visual notes, ready for voiceover and captions.",
    ],
    highlights: [
      "Before/after: 'I used to [struggle]. Then I tried [thing]. Here's what changed.' — fits fitness, skincare, home organizing.",
      "Myth-bust: 'Everyone tells you [common advice]. Here's why that's wrong, and what actually works.' — fits coaching, finance, nutrition.",
      "Day-in-the-life: 'Here's what a normal [job/role] day actually looks like.' — fits creators, founders, tradespeople.",
      "Top-3 list: '3 things I wish I knew before I started [activity].' — fits any how-to or beginner niche.",
      "Behind-the-scenes: 'Here's what [product/process] actually looks like before it's finished.' — fits makers, small brands.",
      "Common mistake: 'If you're doing [common mistake], stop. Do this instead.' — fits tutorials and service businesses.",
      "POV: 'POV: you finally figured out [problem].' — fits relatable, comedic or aspirational niches.",
      "Q&A: 'The question I get asked most about [topic] is [question]. Here's my honest answer.' — fits coaches, consultants.",
      "Review/reaction: 'I tried [product/method] so you don't have to. Here's what happened.' — fits reviews and recommendations.",
      "Challenge: 'I'm trying [challenge] for [timeframe]. Day [X]: here's how it's going.' — fits fitness, habit and creative niches.",
      "Trend tie-in: 'Using [trending format] to show [your topic] because it's just too real not to.' — fits any niche riding a current trend.",
      "Direct offer: 'If you want [outcome], here's exactly how to get it.' — fits product demos and service pitches.",
    ],
    bestFor: "Creators who want a proven structure to adapt, not a blank page.",
    faqs: [
      {
        question: "Do I just read these templates word for word?",
        answer:
          "No. Replace the bracketed part with your own specifics and say the rest in your own voice. The template is the structure, not the script.",
      },
      {
        question: "What's the difference between a template and the script generator?",
        answer:
          "A template is a fixed structure you fill in by hand. The script generator writes a full, unique script from your topic, with timed beats and on-screen visual notes.",
      },
      {
        question: "Can these become a finished video?",
        answer:
          "Yes. Once you've written the lines, Menivor can voice them and burn in karaoke captions over your screen recording or footage to produce a finished reel.",
      },
    ],
    relatedTool: {
      href: "/tools/tiktok-script-generator",
      title: "Want a unique script instead of a template? Try the free script generator",
    },
  },
  {
    slug: "video-hook-ideas",
    title: "50+ Video Hook Ideas by Category",
    keyword: "video hook ideas",
    lede: "Fifty opening lines, grouped by the angle they use, so you can find a hook that fits your video instead of starting from nothing.",
    body: [
      "The first line of a short-form video has one job: make the next line worth watching. These are grouped by angle on purpose — curiosity, bold claims, mistakes, relatable pain and more — because different audiences respond to different angles, and ten rewordings of the same angle test worse than ten different ones.",
      "Read a category, swap the bracketed part for your own topic, and say it the way you'd actually talk. If none of these fit the exact wording you need, the free TikTok hook generator writes ten fresh ones from your specific topic in a few seconds.",
    ],
    highlights: [
      "Curiosity gap: 'Nobody talks about this part of [topic].' / 'The thing about [topic] nobody tells you.'",
      "Bold claim: '[Topic] is easier than you think. Here's proof.' / 'You can fix [topic] in under a minute.'",
      "Mistake callout: 'Stop doing this if you care about [topic].' / 'You're probably getting [topic] wrong.'",
      "POV: 'POV: you finally figured out [topic].' / 'POV: someone shows you the right way to do [topic].'",
      "Question: 'Why does nobody explain [topic] like this?' / 'What if [topic] took half the effort?'",
      "Before/after: 'Before vs after: [topic].' / 'Same [topic], one small change. Look at the difference.'",
      "List tease: '3 things I'd do differently with [topic].' / 'The only 3 steps you need for [topic].'",
      "Contrarian take: 'Unpopular opinion: most advice about [topic] is wrong.' / 'Hot take: [topic] isn't the problem. This is.'",
      "Relatable pain: 'If [topic] keeps frustrating you, this is for you.' / 'Tired of [topic] not working? Same. Until this.'",
      "Direct call-out: 'If you're into [topic], save this.' / 'Calling everyone who cares about [topic].'",
    ],
    bestFor: "Anyone stuck on an opening line, across any niche.",
    faqs: [
      {
        question: "How many hooks should I test?",
        answer:
          "Film at least two or three hook variants of the same video and compare the first few seconds of retention in your analytics. Keep the winner as the template for your next videos.",
      },
      {
        question: "Can I get hooks written for my exact topic instead of these examples?",
        answer:
          "Yes — the free TikTok hook generator takes your specific topic and writes ten original hooks across these same angles in a few seconds.",
      },
    ],
    relatedTool: {
      href: "/tools/tiktok-hook-generator",
      title: "Want hooks written for your exact topic? Try the free TikTok hook generator",
    },
  },
  {
    slug: "product-hunt-launch-video-maker",
    title: "AI Product Hunt Launch Video Maker",
    keyword: "product hunt launch video maker",
    lede: "Paste your Product Hunt listing or landing page link and get a vertical launch video with a hook, a voiceover and captions, ready before your 12:01am PT post.",
    body: [
      "Product Hunt rewards a video that gets to the point: name the problem in the first few seconds, show the product solving it, and end on why someone should try it today. Menivor reads the page behind the link you paste — your landing page or your PH listing draft — and writes that script for you instead of you staring at a blank editor the night before launch.",
      "Each run renders three vertical reels, each opening with a different hook, so you can post the strongest one in your PH gallery and reuse the other two on X and LinkedIn the same morning without filming anything new. Every reel is voiced by a natural AI voice and carries word-by-word captions, which matters because most people browse Product Hunt with the sound off.",
      "If you already have a screen recording of your product instead of just a landing page, Menivor can caption that directly — same pipeline, your own footage, no re-voicing. Either way you get back 1080×1920 MP4 files, done well before launch day, not scrambled together at 11pm the night before.",
    ],
    highlights: [
      "One input: your landing page link or PH listing draft",
      "Three reels per run, each with a different opening hook for your gallery, X and LinkedIn",
      "Word-by-word captions for sound-off browsing — most PH traffic doesn't unmute",
      "1080×1920 MP4s ready well before your 12:01am PT launch window",
    ],
    bestFor: "Founders launching on Product Hunt who need a demo video without a film crew or a late night in an editor.",
    faqs: [
      {
        question: "Does this follow Product Hunt's own video guidance?",
        answer:
          "Yes — keep it to one problem and one solution shown end-to-end, skip the intro logo animation, and caption it, since most PH browsers watch without sound. Menivor's reels are built to that structure by default.",
      },
      {
        question: "Can I use the same video on X and LinkedIn too?",
        answer:
          "Yes. Each run gives you three differently-hooked reels from the same input, so you can post one in your PH gallery and reuse the others as your launch-day posts elsewhere without generating anything new.",
      },
      {
        question: "What if I only have a landing page and no demo footage?",
        answer:
          "That's the default case — paste the landing page link and Menivor writes, voices and captions the reel from what's already on the page. If you do have a screen recording, you can caption that instead.",
      },
      {
        question: "Can I try it for free?",
        answer: OFFER.seoFaqFree,
      },
    ],
    relatedTool: {
      href: "/tools/product-link-to-video",
      title: "Prefer a general ad reel instead of a launch-specific one? Try product link to video",
    },
  },
];

const USE_CASE_BY_SLUG: ReadonlyMap<string, UseCase> = new Map(
  USE_CASES.map((useCase) => [useCase.slug, useCase]),
);

/** Resolve a use case by slug, or `undefined` when unknown. */
export function getUseCase(slug: string): UseCase | undefined {
  return USE_CASE_BY_SLUG.get(slug);
}

/** Every use-case slug — used by generateStaticParams and the sitemap. */
export const USE_CASE_SLUGS: readonly string[] = USE_CASES.map(
  (useCase) => useCase.slug,
);

/** Related use cases for internal linking, excluding the current one. */
export function relatedUseCases(slug: string, limit = 4): readonly UseCase[] {
  return USE_CASES.filter((useCase) => useCase.slug !== slug).slice(0, limit);
}
