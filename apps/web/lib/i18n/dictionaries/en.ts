import { OFFER } from "@/lib/offer";

/**
 * English message catalog — the master dictionary.
 *
 * Its shape is the source of truth for the `Messages` type: every other locale
 * is typed against it (`Messages`), so a missing or misspelled key in `tr`/`es`
 * is a compile error. Values may contain `{name}` placeholders resolved by the
 * translator.
 */
export const en = {
  common: {
    menivor: "Menivor",
    signIn: "Sign in",
    myReels: "My reels",
    wallet: "Wallet",
    tryAgain: "Try again",
    loading: "Loading…",
  },
  languageSwitcher: {
    label: "Language",
  },
  nav: {
    howItWorks: "How it works",
    captions: "Captions",
    pricing: "Pricing",
    freeTools: "Free tools",
    showcase: "Showcase",
    styles: "Styles",
    editor: "Editor",
    joinWaitlist: "Join the waitlist",
    signIn: "Sign in",
    makeReelFree: "Make a reel free",
    startFree: "Make my first video",
    requestAccess: "Request early access",
    goToReels: "Go to my reels",
    openMenu: "Open menu",
    closeMenu: "Close menu",
    homeAria: "Menivor home",
  },
  footer: {
    howItWorks: "How it works",
    captions: "Captions",
    pricing: "Pricing",
    platforms: "By platform",
    make: "What to make",
    tools: "Free tools",
    guides: "Guides",
    features: "Features",
    providers: "Providers",
    turkish: "Türkçe",
    waitlist: "Waitlist",
    signIn: "Sign in",
    terms: "Terms",
    privacy: "Privacy",
    refunds: "Refunds",
    contact: "Contact",
    tagline: "screen recording → finished reel",
  },
  landing: {
    heroKicker: "screen recording → finished reel",
    heroTitle: "Turn your screen recording into a finished short video.",
    heroBody:
      "Menivor takes a raw screen capture and runs the whole edit: it writes a hook-driven script, narrates it with a natural AI voice, burns in word-level karaoke captions, and renders a 9:16 video ready for TikTok, Reels, and Shorts.",
    heroWaitlistNote:
      "Menivor is in a closed pilot while render capacity comes online. Leave your email and we'll open your spot.",
    heroMakeReelFree: "Make a reel free",
    heroSeePricing: "See pricing",
    heroFreeNote: OFFER.heroNote,
    howKicker: "the pipeline",
    howTitle: "One recording in. One finished reel out.",
    step1Label: "record",
    step1Title: "Start from any screen recording",
    step1Body:
      "Capture your product, demo, or workflow — an existing file works, or use Menivor's desktop recorder with window and full-screen capture, mic plus system audio, and a webcam picture-in-picture track.",
    step2Label: "generate",
    step2Title: "The pipeline runs the edit",
    step2Body:
      "Menivor writes a hook-driven script, narrates it with a natural AI voice over your footage, and burns in word-level karaoke captions — in English or Turkish.",
    step3Label: "publish",
    step3Title: "Render 9:16 and post",
    step3Body:
      "The finished vertical video comes out ready for TikTok, Reels, and Shorts — download it, or hand it to the publishing connectors when your accounts are linked.",
    ctaKicker: "early access",
    ctaTitle: "Be first in when generation opens.",
    ctaWaitlistBody:
      "Menivor is in a closed pilot while provider capacity comes online. Join the waitlist and you'll get one email when your spot opens — nothing else.",
    ctaLiveBody: "Turn your next screen recording into a reel worth posting.",
    ctaCreateFirst: "Create your first reel",
    ctaComparePlans: "Compare plans",
    publicKicker: "open now",
    publicTitle: "Make your first reel today.",
    publicBody: OFFER.publicBody,
    startFree: "Make my first video",
    signupNote:
      OFFER.publicStep,
    openNowLabel: "Open now on the free tier:",
    updatesTitle: "Get launch updates",
    updatesBody: "One email when paid packs and publishing to social platforms open.",
    updatesSubmit: "Get launch updates",
    updatesSuccess: "Thanks. We'll email you when paid packs and publishing open.",
  },
  pricing: {
    kicker: "pricing",
    title: "A monthly plan or a one-time pack, priced per reel.",
    intro:
      "Make reels every month on a plan, or buy a credit pack once and use it when you need it. Pack credits never expire, and a failed render never costs a credit.",
    howHeading: "How Menivor credits work",
    howPara1:
      "One credit pays for one finished reel. Menivor reserves the credit when rendering starts and captures it after the video succeeds. A failed render releases the reservation back to your balance. Purchased credits do not expire, so you can render around launches and campaigns without keeping a monthly subscription active.",
    howPara2:
      `${OFFER.pricingLead} Credit packs cover the script, voiceover, karaoke captions, and final 9:16 composition in one render. The pack selector shows the credit count and checkout price before purchase. Teams that need more volume can contact us for a larger allocation.`,
    howPara3:
      "Estimate a pack from the number of finished reels in your campaign, then keep a small allowance for alternate hooks or layouts. A draft that you choose to render again uses another credit because it creates a new finished video. Review the script and source recording before starting a render to avoid spending credits on preventable revisions.",
    volumeQuestion: "Questions about volume pricing? Email",
    waitlistCtaLabel: "Opens with early access",
    waitlistKicker: "early access",
    waitlistBody:
      "Checkout opens when your account does. Join the waitlist and we'll email you once — your free reels are waiting on the other side.",
  },
  create: {
    navFromTemplate: "From a template",
    navGuidedWizard: "Guided wizard",
    navMyReels: "My reels",
    navWallet: "Wallet",
    title: "Create a video",
    subtitle:
      "Turn a voice memo into a captioned 9:16 reel, or generate an AI video from a text prompt or a single image. Your first credits are free, no account needed.",
    tabNarrationLabel: "Narration reel",
    tabNarrationHint: "Your voice + captions — free",
    tabAiVideoLabel: "AI video",
    tabAiVideoHint: "Text or image → video — 3 credits",
    tablistLabel: "Creation mode",
  },
  newReel: {
    title: "Create a new reel",
    subtitle:
      "Upload a screen recording and we'll script it, voice it and burn in karaoke captions — then render a ready-to-post 9:16 video.",
  },
  library: {
    title: "Reel library",
    subtitleFallback: "Every reel you've generated, with live render status.",
    subtitleCount: "{count} reels · signed in as {email}",
    subtitleCountOne: "{count} reel · signed in as {email}",
    calendar: "Calendar",
    scheduled: "Scheduled",
    newReel: "New reel",
    credits: "credits",
    creditsTitle: "Available credits",
    loadError: "Couldn't load your reels.",
    loadErrorTitle: "Couldn't load your reels",
    emptyTitle: "No reels yet",
    emptyBody: "Generate your first reel to see it here.",
    noMatchTitle: "No reels match your filters",
    noMatchBody: "Try a different status or clear your search.",
    showAll: "Show all reels",
  },
  discover: {
    title: "Discover",
    subtitle:
      "Trending sounds, rising hashtags, viral formats, and recommended templates — ranked by opportunity so you build before the wave peaks.",
    refresh: "Refresh",
    risingNow: "Rising now",
    risingNowDesc:
      "Highest-opportunity trends across all kinds — scored by velocity and saturation.",
    noTrends: "No live trends yet. Check back soon.",
    buildNow: "build now",
    sounds: "Trending sounds",
    soundsDesc: "Sounds with rising velocity and low saturation — attach before the wave peaks.",
    hashtags: "Rising hashtags",
    hashtagsDesc: "Hashtags gaining traction — use them before they saturate.",
    viralFormats: "Viral formats",
    viralFormatsDesc:
      "Proven shot-template genres the pipeline can scaffold into a ready reel.",
    explorerCta: "Want to rank your own trend data?",
    explorerCtaLink: "Open the trends explorer",
    explorerCtaTail: "to paste any count series and score it.",
    backToDiscover: "Back to Discover",
    opportunityScore: "Opportunity",
    phaseLabel: "Phase",
    saturationLabel: "Saturation",
    buildNowLabel: "Build now",
    noDataSoon: "No data yet — check back soon.",
    soundsPageTitle: "Trending Sounds",
    soundsPageSubtitle:
      "Sounds with rising velocity and low saturation. Attach to your next reel before this wave peaks.",
    soundsEmpty: "No trending sounds right now. Check back soon.",
    hashtagsPageTitle: "Rising Hashtags",
    hashtagsPageSubtitle:
      "Hashtags gaining momentum right now — use them in your content before they saturate the feed.",
    hashtagsEmpty: "No trending hashtags right now. Check back soon.",
    formatsPageTitle: "Rising Formats",
    formatsPageSubtitle:
      "Viral format patterns and shot-templates gaining traction — the closest rising-creator signal the API exposes.",
    formatsSignalNote:
      "This page surfaces format-kind trends from the live feed and viral shot-templates. There is no per-creator analytics endpoint; the format signal is the best proxy available.",
    formatsEmpty: "No rising formats right now. Check back soon.",
    trendingTemplates: "Trending templates",
    trendingTemplatesDesc:
      "Viral shot-template genres ready to scaffold into your next reel.",
  },
  showcase: {
    title: "Showcase",
    subtitle:
      "Browse viral shot-templates and your completed reels.",
    templatesHeading: "Template gallery",
    templatesDesc:
      "Proven genre formats the pipeline can scaffold into a ready reel.",
    myReelsHeading: "Your completed reels",
    myReelsDesc:
      "Reels you have rendered — sign in to see yours.",
    signInPrompt: "Sign in to see your completed reels here.",
    noTemplates: "No templates available.",
    noReels:
      "No completed reels yet. Create your first reel to see it here.",
    useTemplate: "Use template",
    previewReel: "Preview reel",
    slots: "slots",
  },
  analyticsDeep: {
    views: {
      title: "Views breakdown",
      subtitle:
        "Job counts by composition layout and language over the selected window.",
      byLayout: "By layout",
      byLanguage: "By language",
      noData: "No view data for this window.",
    },
    retention: {
      title: "Retention and funnel",
      subtitle:
        "Completion rate, failed jobs, render-time percentiles, and funnel progression.",
      created: "Created",
      completed: "Completed",
      failed: "Failed",
      published: "Published",
      completionRate: "Completion rate",
      failRate: "Fail rate",
      renderTime: "Render time",
      p50: "p50",
      p90: "p90",
      avg: "avg",
      samples: "samples measured",
      noData: "No funnel data for this window.",
    },
    hooks: {
      title: "Top hooks",
      subtitle:
        "Your most-used opening lines and templates — all-time data from the analytics service.",
      hooksHeading: "Hooks",
      templatesHeading: "Templates",
      noData: "No data yet. Render reels to see which openings you use most.",
    },
  },
  apiDocs: {
    title: "API reference",
    subtitle:
      "Menivor public endpoints — reels, templates, trends, and analytics.",
    authNote:
      "Authentication: send your API key as the x-api-key request header.",
    requestLabel: "Example request",
    paramsLabel: "Parameters",
    responseLabel: "Response shape",
    required: "required",
    optional: "optional",
    backToOverview: "Overview",
  },
  editor: {
    title: "Reel editor",
    backAria: "Back to source job",
    loadingTitle: "Loading source reel",
    jobLabel: "Job {id}",
    loadErrorTitle: "Could not load source reel",
    renderFailedTitle: "This render failed",
    renderNotReadyTitle: "Render is not ready",
    pauseAria: "Pause preview",
    playAria: "Play selected range",
    cutRangeHeading: "Cut range",
    cutRangeHelp:
      "Set in and out points, then preview only that section. The original render is unchanged.",
    inPoint: "In point",
    outPoint: "Out point",
    selected: "Selected",
    source: "Source",
    previewCut: "Preview cut",
    resetRange: "Reset range",
    copyCutValues: "Copy cut values",
    copied: "Copied",
    exportSelection: "Export selection",
    queuingExport: "Queuing export",
    exportFailedFallback: "The export failed in the render worker.",
    downloadExportedCut: "Download exported cut",
    downloadSource: "Download source",
    timeline: "Timeline",
    seekAria: "Seek timeline",
    advancedHeading: "Advanced — multi-clip timeline",
    loadingDuration:
      "Loading source duration before enabling timeline edits…",
    noSourceTitle: "Choose a completed reel",
    noSourceDetail:
      "Pick a finished reel below to load its render into the editor.",
    openJobs: "Open reel",
    openLibrary: "Open reel library",
    openExportedReel: "Open exported reel",
  },
  studioCatalog: {
    brollTitle: "B-roll library",
    brollSubtitle:
      "Your AI-generated B-roll clips — filter by state, use one in a reel, or download.",
    brollGenerate: "Generate B-roll",
    captionsTitle: "Captions",
    captionsSubtitle:
      "Per-platform caption safe-zones and tools — from the renderer the pipeline uses.",
    captionStyles: "Caption styles",
    voicesTitle: "Voices",
    voicesSubtitle:
      "Narrator voices and lipsync providers — pick a voice and see which engine will render it.",
    myVoices: "My voices",
    avatarsTitle: "Avatars",
    avatarsSubtitle:
      "Provider avatars and your identity-locked characters — pick a presenter or lock a character.",
    characters: "Characters",
    clipsTitle: "Clips",
    clipsSubtitle:
      "Long-to-short clipping jobs — view produced clips and promote any clip into a reel draft.",
    newReel: "New reel",
    refresh: "Refresh",
    promoteToReel: "Promote to reel",
    openDraft: "Open draft",
    safezoneTitle: "Per-platform safe-zones",
    safezoneSubtitle:
      "Caption placement the renderer burns in for each platform surface.",
    captionTools: "Caption tools",
    voicesLipsync: "Lipsync providers",
    voicesNarrator: "Narrator voices",
    avatarsProvider: "Avatars",
    avatarsCharacters: "Characters",
    clippingJobs: "Clipping jobs",
    clipPromoted: "Clip promoted to reel draft",
    noVoices: "No voices available. Check your API configuration.",
    noAvatars: "No avatars available right now. Please try again later.",
    noCharacters: "No saved characters yet. Create one to lock an identity across shots.",
    noClips: "No clipping jobs yet. Start one from a long recording or URL.",
    noSafezones: "No safe-zone data returned.",
    createCharacter: "Create character",
    manageCharacters: "Manage characters",
    createClippingJob: "Create clipping job",
    useVoice: "Use voice",
    useAvatar: "Use avatar",
    useInFilm: "Use in film",
  },
  shareToX: {
    button: "Share to X",
    buttonAria: "Share to X. Opens the post composer in a new tab.",
    downloadAndShareAria:
      "Download the MP4 and share to X. Opens the post composer in a new tab.",
    hint: "X can't attach the video. Download the MP4, then add it in the composer.",
  },
} as const;

/**
 * Widens the literal shape of `en` into the catalog contract every locale must
 * satisfy: identical key structure, but plain `string` values. This makes a
 * missing/misspelled key in another locale a compile error while allowing each
 * locale its own translations.
 */
type Localized<T> = {
  [K in keyof T]: T[K] extends string ? string : Localized<T[K]>;
};

export type Messages = Localized<typeof en>;
