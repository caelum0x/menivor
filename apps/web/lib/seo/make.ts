/**
 * Content-type landing-page dataset for `/make/{type}`.
 *
 * Each entry is a category page ("make a faceless video", "make a talking-head
 * video") that sits above the individual templates and use cases: it explains
 * the format, why Menivor's pipeline is a good fit, and routes to the concrete
 * styles that produce it. Copy is grounded in what renders today (the style
 * catalog, a natural AI voice, word captions); avatar video is described as not
 * available yet. `templates` slugs are kept for the graph; links to them are
 * dropped by the dead-link guard while no `/templates` page exists.
 */

export interface MakeFaq {
  readonly question: string;
  readonly answer: string;
}

export interface MakeType {
  /** URL segment: `/make/{slug}`. */
  readonly slug: string;
  /** Display title / H1. */
  readonly title: string;
  /** Primary keyword phrase for metadata. */
  readonly keyword: string;
  /** One-sentence lede under the H1. */
  readonly lede: string;
  /** 3 paragraphs of format-specific body copy. */
  readonly body: readonly string[];
  /** Ordered "how Menivor makes it" steps (also emitted as HowTo JSON-LD). */
  readonly steps: readonly { readonly name: string; readonly text: string }[];
  /** What you get — differentiated bullets. */
  readonly highlights: readonly string[];
  /** "Best for" audience line. */
  readonly bestFor: string;
  /** Template slugs (`/templates/{slug}`) that produce this content type. */
  readonly templates: readonly string[];
  /** Platform slugs (`/for/{slug}`) this type suits. */
  readonly platforms: readonly string[];
  /** Use-case slugs (`/tools/{slug}`) for this type. */
  readonly useCases: readonly string[];
  readonly faqs: readonly MakeFaq[];
}

export const MAKE_TYPES: readonly MakeType[] = [
  {
    slug: "faceless-video",
    title: "Make a Faceless Video",
    keyword: "faceless video maker",
    lede: "Run a whole channel without showing your face: narrated, captioned reels over gameplay, moving footage or satisfying loops.",
    body: [
      "A faceless video carries a message with narration and captions instead of a person on camera, so you can post consistently without a camera, a studio, or being on screen. It is the model behind most high-volume Shorts and TikTok channels: repeatable formats, fast turnaround, no personal exposure.",
      "Menivor is built for it. You give a link, a topic or a script; it writes a hook-first narration, voices it with a natural AI voice, burns karaoke captions timed to the audio, and lays it over a moving background: block-world gameplay, a satisfying loop, a cartoon narrator scene or your own footage.",
      "Because credits are captured only on success and never expire, a faceless operator can batch variations, keep the winners, and never burn budget on a failed render. Download the 1080×1920 MP4 and post it to TikTok, Reels and Shorts.",
    ],
    steps: [
      { name: "Pick a faceless style", text: "Choose a style: story time over gameplay, satisfying split, cartoon narrator, meme hook or POV text." },
      { name: "Add your link, topic or script", text: "Paste a link, type a topic or paste a script; Menivor writes the hook-first narration in English or Turkish." },
      { name: "Menivor narrates and captions it", text: "A natural AI voice reads the script and word-by-word karaoke captions are burned over the moving background." },
      { name: "Download and post", text: "Download the 1080×1920 MP4 and post it to TikTok, Reels and YouTube Shorts." },
    ],
    highlights: [
      "No camera and no face required",
      "Narration and karaoke captions over gameplay, loops or your footage",
      "Batch-friendly: success-only credits that never expire",
      "Story time, satisfying split, cartoon narrator and meme hook styles",
    ],
    bestFor: "Channel operators posting at volume without appearing on camera.",
    templates: ["minecraft-reddit-split", "faceless-facts", "story-time", "listicle", "countdown-ranking", "asmr-satisfying-loop"],
    platforms: ["tiktok", "youtube-shorts", "instagram-reels"],
    useCases: ["faceless-video-generator", "faceless-tiktok-video-maker", "faceless-youtube-shorts-maker", "faceless-instagram-reels-maker"],
    faqs: [
      {
        question: "How do I make a faceless video?",
        answer:
          "Pick a faceless style, add a link, topic or script, and Menivor writes and narrates a hook-first script, burns karaoke captions, and lays it over a moving background. No camera needed.",
      },
      {
        question: "Which styles are faceless?",
        answer:
          "Every style that ships today: block-world gameplay split, meme hook, satisfying split, POV text, before and after, story time and the cartoon narrator. They run on narration, captions and moving footage. You never appear on screen.",
      },
      {
        question: "Can I batch faceless videos affordably?",
        answer:
          "Yes. One credit renders one finished reel, credits are only captured on success, and they never expire, so you can produce many variations and keep the ones that perform.",
      },
      {
        question: "What voice narrates a faceless video?",
        answer:
          "A natural AI voice you choose, in English or Turkish, with karaoke captions timed word-by-word to that narration.",
      },
    ],
  },
  {
    slug: "talking-head",
    title: "Make a Talking-Head Style Video",
    keyword: "talking head video maker",
    lede: "Turn one idea into a clear, voiced explainer reel, with your own selfie clip or no camera at all.",
    body: [
      "A talking-head video is one voice delivering one idea: the format that builds authority and personal brand fastest. Filming consistently is the bottleneck. Menivor removes most of it: it writes the script, voices it with a natural AI voice and burns in captions, over your screen recording, your own selfie clip or a moving style scene.",
      "Avatar video, where a generated person speaks your script on camera, is not available in Menivor yet. What ships today is the voiced explainer: a hook-first script, a narrator voice and word-by-word captions, which carries the same single idea without anyone filming.",
      "It is the format for founders, educators and B2B teams who need to show up on video regularly. Keep it to one idea, land a single takeaway, and download the MP4 for TikTok, Reels, Shorts or LinkedIn.",
    ],
    steps: [
      { name: "Choose a style", text: "Pick the voiceover reel, POV text or before and after style." },
      { name: "Write your idea", text: "Give the one idea you are explaining, and add a screen recording or a selfie clip if you have one." },
      { name: "Menivor scripts, voices and captions it", text: "A hook-first script is written and voiced, with karaoke captions burned in." },
      { name: "Download and post", text: "Download the 1080×1920 MP4 for TikTok, Reels, Shorts or LinkedIn." },
    ],
    highlights: [
      "A natural AI voice, so no filming is required",
      "Use your own selfie clip or screen recording as the footage",
      "Hook-first script kept to a single clear takeaway",
      "Authority-first tone for explainers and thought leadership",
    ],
    bestFor: "Founders, educators, and B2B creators building a personal brand on video.",
    templates: ["talking-head-explainer", "meme-explainer", "greenscreen-react", "product-demo-ad"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts", "linkedin"],
    useCases: ["talking-head-video-generator", "ai-avatar-video-generator", "explainer-video-generator", "ai-spokesperson-video-generator"],
    faqs: [
      {
        question: "Can I make an explainer video without filming myself?",
        answer:
          "Yes. Menivor narrates your script with a natural AI voice over a screen recording or a moving style scene. If you prefer your own face, upload a short selfie clip as the footage.",
      },
      {
        question: "Can a generated avatar speak my script?",
        answer:
          "Not yet. Avatar video is not available in Menivor today. The voiced explainer, with captions over your footage or a style scene, is what renders now.",
      },
      {
        question: "How long should an explainer reel be?",
        answer:
          "Short, around a single idea. The format is strongest when the takeaway is one repeatable sentence.",
      },
      {
        question: "Does it work in Turkish?",
        answer:
          "Yes. Menivor writes and voices the script in English or Turkish and burns Turkish-glyph captions timed to the audio.",
      },
    ],
  },
  {
    slug: "product-demo",
    title: "Make a Product Demo Video",
    keyword: "product demo video maker",
    lede: "Turn a link or a screen recording into a demo ad: your real product on screen, a voiceover from hook to call to action.",
    body: [
      "A product demo video shows the thing working, which is the most persuasive thing an ad can do. Menivor is built around exactly this: paste your product link or upload a screen recording, and it writes a hook-first script, narrates it and captions it over your real footage: the hook, the pain, the live demo, and a call to action.",
      "This is the 'a startup can make its own marketing' workflow in one flow. A link run records your page as moving footage; a screen recording run uses your own capture. Split-screen styles put your product on top and a moving loop below, so viewers watch the real product while the voice carries the message.",
      "Success-only billing means you can render several hooks over the same footage and ship the winners. Download the 1080×1920 MP4 for TikTok, Reels, LinkedIn and landing pages.",
    ],
    steps: [
      { name: "Paste a link or record your product", text: "Paste your product page, or capture a screen recording of your app in action." },
      { name: "Add a one-line pitch", text: "Write what it does and for whom; Menivor turns it into a hook-first script with a call to action." },
      { name: "Menivor voices and captions the demo", text: "A natural AI voice narrates the hook and the demo while your footage fills the frame, with captions burned in." },
      { name: "Download and post", text: "Download the MP4 for TikTok, Reels, LinkedIn, ads and landing pages." },
    ],
    highlights: [
      "Your real page or screen recording as the footage",
      "Hook, pain, live demo and call-to-action structure",
      "Split-screen and before and after styles built in",
      "Test multiple hooks on success-only, non-expiring credits",
    ],
    bestFor: "SaaS founders, product marketers, and agencies producing demo ads at volume.",
    templates: ["product-demo-ad", "tutorial-howto", "testimonial-ad", "before-after"],
    platforms: ["tiktok", "instagram-reels", "linkedin"],
    useCases: ["saas-demo-video-maker", "product-demo-to-reel", "app-demo-video-maker", "saas-marketing-video-maker"],
    faqs: [
      {
        question: "What do I need to make a product demo video?",
        answer:
          "Your product link, or a screen recording and a one-line pitch. Menivor writes the hook and script, narrates it and captions it over your footage.",
      },
      {
        question: "Why keep the real product on screen?",
        answer:
          "Viewers trust what they can see working. Your real footage shows the product while the voiceover and captions carry the message, which is the combination that converts.",
      },
      {
        question: "Can I make demos for paid social?",
        answer:
          "Yes. Demo reels suit ads on TikTok and Instagram; success-only billing lets you test hooks and creatives cheaply.",
      },
      {
        question: "Can I use it for a tutorial instead of an ad?",
        answer:
          "Yes. Upload a screen recording of the steps and ask for a how-to; the script walks through it with a save line instead of a sales line.",
      },
    ],
  },
  {
    slug: "quote-video",
    title: "Make a Motivational Quote Video",
    keyword: "quote video maker",
    lede: "Turn a theme or a single line into a motivational reel: a narrated build, the quote at the peak, a follow line.",
    body: [
      "A quote video works on rhythm and restraint: a tension hook, a narrated build over moving footage, and a single punch-line quote that lands at the emotional peak. It is the daily-posting format behind most mindset, stoicism and discipline pages.",
      "Give Menivor a theme like 'discipline over motivation', or the exact quote you want to land, and it writes the build, narrates it with a natural AI voice and burns clean captions over a moving background.",
      "It is faceless, short and fast to batch, which is what daily quote pages need. Download the 1080×1920 MP4 and post it to Reels, TikTok and Shorts.",
    ],
    steps: [
      { name: "Choose a style", text: "The voiceover reel or satisfying split suits the tension-build-quote arc." },
      { name: "Give a theme or the exact quote", text: "Provide a theme like 'discipline over motivation', or the precise line to land." },
      { name: "Menivor builds and times it", text: "It writes the narrated build and lands the quote at the end, with clean captions." },
      { name: "Download and post", text: "Download the 1080×1920 MP4 for daily posting on Reels, TikTok and Shorts." },
    ],
    highlights: [
      "A narrated build with the quote at the peak",
      "Faceless: narration and captions over moving footage",
      "Supply your own line or let Menivor write one to theme",
      "Short and batch-friendly for daily posting",
    ],
    bestFor: "Mindset, stoicism, fitness, and discipline pages posting daily motivation.",
    templates: ["quote-motivation", "faceless-facts", "story-time"],
    platforms: ["instagram-reels", "tiktok", "youtube-shorts"],
    useCases: ["faceless-video-generator", "short-form-video-generator", "vertical-video-generator"],
    faqs: [
      {
        question: "Can I supply my own quote?",
        answer:
          "Yes. Give the exact line to land and Menivor builds the narrated ramp up to it. Leave it out and it writes a quote to fit your theme.",
      },
      {
        question: "Is a quote video faceless?",
        answer:
          "Yes. It is narration and clean captions over moving footage with nobody on camera, which is why it suits daily posting.",
      },
      {
        question: "Why keep quote videos short?",
        answer:
          "Motivation lands on impact, not length. A short build gives the quote room to hit before attention fades.",
      },
      {
        question: "Can I batch a week of quotes at once?",
        answer:
          "Yes. Because credits are success-only and never expire, you can render a batch of themed quotes and schedule them across the week.",
      },
    ],
  },
  {
    slug: "listicle",
    title: "Make a Listicle Video",
    keyword: "listicle video maker",
    lede: "Turn a topic into a rapid-fire numbered list built for saves: a numbered hook, punchy items, the best pick, a save line.",
    body: [
      "A listicle video is reference content people save to act on later, which is why the format compounds reach through saves and shares. It opens on a numbered promise ('five free tools for founders'), fires through punchy items with bold captions, highlights the best pick, and asks for the save.",
      "Give Menivor the topic and it writes the list, narrates it and paces each item to the captions so it is scannable on mute. POV text and meme hook styles give the opening line its punch. It is faceless by default.",
      "It is a fit for value, edutainment and marketing channels, and it works in the LinkedIn feed too, where 'N things' posts do well. Download the MP4 for TikTok, Reels, Shorts or anywhere else.",
    ],
    steps: [
      { name: "Choose a style", text: "POV text, meme hook or the plain voiceover reel all suit a list." },
      { name: "Give your list topic", text: "Type a topic like 'five free tools for founders'; Menivor writes the numbered list and best pick." },
      { name: "Menivor narrates and paces it", text: "A natural AI voice reads the list and bold karaoke captions are timed so each item reads at a glance on mute." },
      { name: "Download and post", text: "Download the 1080×1920 MP4 for TikTok, Reels and Shorts." },
    ],
    highlights: [
      "Numbered hook that pulls viewers to the end",
      "Bold captions built to be scannable on mute",
      "Save and share friendly, faceless by default",
      "Works in any of the shipped styles",
    ],
    bestFor: "Value, edutainment, and marketing creators optimizing for saves and shares.",
    templates: ["listicle", "countdown-ranking", "faceless-facts"],
    platforms: ["tiktok", "instagram-reels", "youtube-shorts", "linkedin"],
    useCases: ["listicle-video-generator", "faceless-video-generator", "short-form-video-generator"],
    faqs: [
      {
        question: "How many items should a listicle video have?",
        answer:
          "A handful: enough to keep pace but few enough to finish while attention holds. The number in the hook is a promise, so deliver exactly that many.",
      },
      {
        question: "Is a listicle video faceless?",
        answer:
          "Yes by default: it runs on narration and bold captions over moving footage. You can use your own clip as the footage if you want a face on it, but it is not required.",
      },
      {
        question: "What's the difference between a listicle and a countdown?",
        answer:
          "A listicle presents items in order for reference and saves; a countdown builds to a number-one reveal for suspense and debate. Ask for either in your topic and the script follows.",
      },
      {
        question: "Why optimize listicles for saves?",
        answer:
          "List content is acted on later, so viewers save it. Saves and shares extend reach beyond the first view, which is why the last line asks for the save.",
      },
    ],
  },
];

export function getMakeType(slug: string): MakeType | undefined {
  return MAKE_TYPES.find((type) => type.slug === slug);
}

export const MAKE_TYPE_SLUGS: readonly string[] = MAKE_TYPES.map(
  (type) => type.slug,
);

/** Other content types, for the cross-link mesh. */
export function otherMakeTypes(slug: string): readonly MakeType[] {
  return MAKE_TYPES.filter((type) => type.slug !== slug);
}
