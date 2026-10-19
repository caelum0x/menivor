/**
 * Catalog of Menivor's free, working tools under /tools/<slug>. Each entry
 * carries unique SSR copy (lede, body, steps, FAQs) plus internal links, so the
 * page is useful before the interactive widget even loads. Slugs follow Google
 * Autocomplete phrasing (hl=en, gl=us) checked on 2026-10-08.
 */

import type { FaqEntry } from "../jsonld";

export type FreeToolWidget =
  | "hooks"
  | "script"
  | "script-shorts"
  | "hashtags"
  | "titles"
  | "captions"
  | "ideas"
  | "subtitles"
  | "transcript"
  | "voiceover"
  | "srt-vtt"
  | "shifter"
  | "aspect"
  | "bitrate"
  | "script-length";

export type FreeToolCategory = "AI writing" | "Captions and audio" | "Calculators";

export interface FreeToolLink {
  readonly href: string;
  readonly title: string;
}

export interface FreeTool {
  readonly slug: string;
  readonly widget: FreeToolWidget;
  readonly category: FreeToolCategory;
  /** <title> without the brand suffix (template adds "| Menivor"). */
  readonly title: string;
  readonly h1: string;
  readonly shortName: string;
  readonly keyword: string;
  readonly description: string;
  readonly lede: string;
  /** Where the work happens, stated plainly on the page. */
  readonly privacy: string;
  readonly body: readonly string[];
  readonly steps: readonly string[];
  readonly faqs: readonly FaqEntry[];
  readonly related: readonly string[];
  readonly links: readonly FreeToolLink[];
}

const LLM_PRIVACY =
  "Your topic is sent to Menivor's server, where an AI model writes the result; we do not store what you type. If the AI writer is busy, you get instant results from proven short-form formulas instead.";
const BROWSER_AI_PRIVACY =
  "Runs entirely in your browser. Your file is never uploaded: the open-source model is downloaded once to your device and does the work locally.";
const BROWSER_PRIVACY = "Runs entirely in your browser. Nothing is uploaded.";

export const FREE_TOOLS: readonly FreeTool[] = [
  {
    slug: "tiktok-hook-generator",
    widget: "hooks",
    category: "AI writing",
    title: "Free TikTok Hook Generator: 10 Hooks, No Signup",
    h1: "TikTok hook generator",
    shortName: "TikTok hook generator",
    keyword: "tiktok hook generator",
    description:
      "Type your video topic and get 10 scroll-stopping TikTok hooks in 10 different angles. Free hook generator for TikTok, Reels and Shorts. No signup.",
    lede: "Describe your video in one line. Get ten opening lines, each built on a different hook angle, ready to say or put on screen in the first two seconds.",
    privacy: LLM_PRIVACY,
    body: [
      "Most viewers decide in the first one to two seconds whether to keep watching. The hook is the line that makes that decision for them, so it is worth writing ten and testing the best two or three rather than settling on the first idea.",
      "This generator deliberately spreads its ten hooks across different angles: a curiosity gap, a bold claim, a mistake call-out, a POV line, a question, a before and after, a list tease, a contrarian take, a relatable pain, and a direct call-out of the viewer. Different audiences respond to different angles, so variety beats ten rewordings of the same sentence.",
      "The hooks stick to what you tell it. It will not invent statistics, prices or reviews, which keeps the line honest and keeps you clear of misleading-claims rules on TikTok and Meta.",
    ],
    steps: [
      "Describe the video: the product, topic or story, and who it is for.",
      "Pick the platform and a tone (bold, funny, educational, story or salesy).",
      "Generate, then copy the hooks you like. Film two or three variants and keep the one with the best 3-second view rate.",
    ],
    faqs: [
      { question: "What makes a good TikTok hook?", answer: "A good hook creates a reason to keep watching within two seconds: an open question, a surprising claim you then prove, or a pain the viewer recognises. It should match what the rest of the video actually delivers, otherwise viewers swipe away and retention drops." },
      { question: "Is this TikTok hook generator free?", answer: "Yes. You can generate hooks without an account. Free use is rate limited to a few runs per hour so the tool stays free for everyone." },
      { question: "Can I use these hooks for Reels and YouTube Shorts?", answer: "Yes. Pick Instagram Reels or YouTube Shorts in the platform menu. The hook formats work across all short-form platforms; only the pacing and on-screen text placement differ." },
      { question: "How many hooks should I test?", answer: "Film at least two or three hook variants of the same video. Compare the 2 to 3 second retention in your analytics and keep the winner as the template for your next videos." },
      { question: "Can Menivor turn the hook into a full video?", answer: "Yes. With a free Menivor account you paste a link or topic and get finished vertical videos with a hook-first script, AI voiceover and word-by-word captions." },
    ],
    related: ["tiktok-script-generator", "video-title-generator", "hashtag-generator", "subtitle-generator"],
    links: [
      { href: "/guides/how-to-write-a-tiktok-hook", title: "How to write a TikTok hook" },
      { href: "/tools/tiktok-hook-script-generator", title: "Hook-first scripts turned into finished reels" },
      { href: "/tools/tiktok-ad-maker", title: "TikTok ad maker" },
    ],
  },
  {
    slug: "tiktok-script-generator",
    widget: "script",
    category: "AI writing",
    title: "Free TikTok Script Generator for Reels and Shorts",
    h1: "TikTok script generator",
    shortName: "TikTok script generator",
    keyword: "tiktok script generator",
    description:
      "Free script generator for TikTok, Instagram Reels and YouTube Shorts. Get a hook, timed beats with visuals and a call to action for 15, 30 or 60 seconds.",
    lede: "Turn a topic into a short-form video script with a hook, three to five beats with on-screen visual ideas, and a call to action, sized to 15, 30 or 60 seconds.",
    privacy: LLM_PRIVACY,
    body: [
      "Short-form scripts fail in predictable ways: the hook is buried, the middle wanders, and there is no clear ending. This generator forces the structure that works on TikTok, Reels and Shorts: a hook in the first two seconds, a few tight beats that each deliver one point, and a single call to action.",
      "The length setting controls the word count. People speak roughly 2.5 words per second on short-form video, so a 30-second script lands near 75 words and a 60-second script near 150. Each beat comes with a visual suggestion so you know what to film or which B-roll to cut to.",
      "Use it for product demos, explainers, tips, stories and UGC-style ads. The script uses only what you describe, so add the specific facts you want mentioned.",
    ],
    steps: [
      "Describe the video and add any facts it must mention.",
      "Choose the platform, tone and length (15, 30 or 60 seconds).",
      "Generate, copy the script, and read it aloud once to check the timing before you film.",
    ],
    faqs: [
      { question: "How long should a TikTok script be?", answer: "At a natural pace of about 2.5 words per second, a 15-second video is around 35 to 40 words, 30 seconds around 75 words, and 60 seconds around 150 words. Shorter usually wins unless the topic needs the time." },
      { question: "Does it work for YouTube Shorts and Instagram Reels?", answer: "Yes. Choose the platform and the script adapts its pacing and call to action. The same hook, beats and CTA structure works on all three." },
      { question: "Can it write a script for a TikTok Shop or product video?", answer: "Yes. Describe the product and the one problem it solves. The generator will not invent prices, reviews or claims, so include the facts you want said." },
      { question: "Is my script saved?", answer: "No. The text you type is sent to generate the script and is not stored. Copy the result before you leave the page." },
      { question: "Can Menivor voice and caption the script for me?", answer: "Yes. In Menivor you paste a link or topic and it writes, voices, captions and renders a finished 1080x1920 video you can download and post." },
    ],
    related: ["tiktok-hook-generator", "ai-voiceover-generator", "video-title-generator", "hashtag-generator"],
    links: [
      { href: "/tools/explainer-video-generator", title: "AI explainer video generator" },
      { href: "/guides/how-to-make-youtube-shorts-without-showing-your-face", title: "How to make YouTube Shorts without showing your face" },
    ],
  },
  {
    slug: "hashtag-generator",
    widget: "hashtags",
    category: "AI writing",
    title: "Free Hashtag Generator for TikTok, Reels and Shorts",
    h1: "Hashtag generator for TikTok, Reels and Shorts",
    shortName: "Hashtag generator",
    keyword: "hashtag generator",
    description:
      "Generate 20 relevant hashtags for TikTok, Instagram Reels or YouTube Shorts, ordered from niche to broad. Free hashtag generator, copy in one click.",
    lede: "Describe your video and get 20 hashtags ranked from niche to broad: eight specific tags, eight topic tags and four broad ones, ready to copy.",
    privacy: LLM_PRIVACY,
    body: [
      "Hashtags help short-form platforms understand what a video is about and who to show it to. Broad tags alone put you in an ocean of competition; niche tags alone may have no audience. A mix from specific to broad is the practical middle.",
      "This generator returns lowercase, space-free tags in that order and avoids spam chains such as follow-for-follow tags. On TikTok and Reels, three to six well-chosen tags usually beat thirty generic ones, so pick from the top of the list first.",
      "Captions and on-screen text matter as much as tags now that TikTok, Instagram and YouTube index the words in your caption. Put your main keyword in the first line of the caption, then add the tags.",
    ],
    steps: [
      "Describe the video topic and audience in one line.",
      "Pick TikTok, Instagram Reels or YouTube Shorts.",
      "Generate, then copy the full set or click individual tags to build your own mix.",
    ],
    faqs: [
      { question: "How many hashtags should I use on TikTok?", answer: "Three to six relevant hashtags is a sensible default. TikTok allows more, but tags that do not match the video do not help it reach the right viewers." },
      { question: "Do hashtags still work on Instagram Reels?", answer: "They help with categorisation, but Instagram now leans on caption keywords too. Use a few specific hashtags and put your main keyword in the caption text." },
      { question: "Where do hashtags go on YouTube Shorts?", answer: "Add them to the title or description. YouTube shows the first three hashtags above the title, and #shorts is optional for videos that are already vertical and under three minutes." },
      { question: "Does this tool show hashtag volumes?", answer: "No. It suggests relevant tags based on your topic. Check a tag's search page in the app to see how active it is before relying on it." },
    ],
    related: ["video-title-generator", "tiktok-hook-generator", "tiktok-script-generator"],
    links: [
      { href: "/for/tiktok", title: "Menivor for TikTok" },
      { href: "/guides/how-to-make-instagram-reels-for-business", title: "How to make Instagram Reels for business" },
      { href: "/tools/instagram-reels-maker", title: "Instagram Reels maker" },
    ],
  },
  {
    slug: "video-title-generator",
    widget: "titles",
    category: "AI writing",
    title: "Free Video Title Generator for YouTube and TikTok",
    h1: "Video title generator",
    shortName: "Video title generator",
    keyword: "video title generator",
    description:
      "Get 10 video titles for YouTube, Shorts, TikTok or Reels in six formats, with the keyword up front and length limits respected. Free title generator.",
    lede: "Describe your video and get ten titles in six formats (how-to, list, question, outcome, mistake, comparison) with the searchable keyword at the start.",
    privacy: LLM_PRIVACY,
    body: [
      "A title has two jobs: tell search what the video is about and give a person a reason to tap. Front-loading the keyword handles the first job; a clear outcome or open question handles the second.",
      "Pick YouTube for long-form titles that stay under about 60 characters so they are not cut off in search results. Pick TikTok, Reels or Shorts for caption-style first lines that read naturally and still carry the keyword the platforms now index.",
      "Generate a batch, shortlist three, and test them. YouTube lets you A/B test titles on long-form videos; on short-form, reuse the best-performing pattern on your next posts.",
    ],
    steps: [
      "Describe what the video shows or teaches.",
      "Choose the platform and tone.",
      "Generate ten titles and copy the ones that fit. Keep the main keyword in the first few words.",
    ],
    faqs: [
      { question: "How long should a YouTube title be?", answer: "YouTube allows 100 characters but search results and suggested videos often truncate around 60 to 70. Keep the important words in the first 60 characters." },
      { question: "Do TikTok videos have titles?", answer: "TikTok uses the caption's first line as the de facto title, and it is indexed for TikTok search. Write that line like a title with the keyword early." },
      { question: "Should I use clickbait titles?", answer: "Only if the video delivers on the promise. Titles that overpromise raise click-through but hurt watch time, which hurts distribution more." },
      { question: "Is the video title generator free?", answer: "Yes, with no signup. Free runs are rate limited per visitor to keep the service available." },
    ],
    related: ["hashtag-generator", "tiktok-hook-generator", "tiktok-script-generator"],
    links: [
      { href: "/for/youtube-shorts", title: "Menivor for YouTube Shorts" },
      { href: "/tools/youtube-shorts-maker", title: "YouTube Shorts maker" },
      { href: "/guides/how-to-make-a-faceless-youtube-channel-with-ai", title: "How to make a faceless YouTube channel with AI" },
    ],
  },
  {
    slug: "tiktok-caption-generator",
    widget: "captions",
    category: "AI writing",
    title: "Free TikTok Caption Generator: 10 Captions, No Signup",
    h1: "TikTok caption generator",
    shortName: "TikTok caption generator",
    keyword: "tiktok caption generator",
    description:
      "Type your video topic and get 10 ready-to-post TikTok, Reels or Shorts captions in 10 different angles. Free caption generator, no signup needed.",
    lede: "Describe your video in one line. Get ten post captions, each written in a different angle, ready to paste under your TikTok, Reels or Shorts upload.",
    privacy: LLM_PRIVACY,
    body: [
      "A caption is not the same job as a hook. The hook has to earn the first two seconds inside the video; the caption sits underneath it and has to earn a comment, a follow, or a second watch from someone who already finished the video.",
      "This generator spreads its ten captions across different angles so you are not just rewording the same sentence: a direct statement, a question that invites replies, a relatable callout, a bold claim, a list tease, a behind-the-scenes note, a community shoutout, a challenge or dare, a curiosity gap, and a plain description for when you want the caption to stay out of the way.",
      "Captions stay short on purpose, use at most two hashtags, and never invent prices, stats or reviews, so you are not left editing out something misleading before you post.",
    ],
    steps: [
      "Describe the video: what happens in it, and who it is for.",
      "Pick the platform and a tone (bold, funny, educational, story or salesy).",
      "Generate, then copy the caption that fits. Pair it with a few hashtags from the hashtag generator.",
    ],
    faqs: [
      { question: "What makes a good TikTok caption?", answer: "A good caption gives a reason to comment, reply, or watch again: a question, a relatable observation, or a short statement that adds context the video did not say out loud. It should not repeat the hook word for word." },
      { question: "How long should a TikTok caption be?", answer: "Short. The app only shows the first line or two before 'more', so the strongest line should come first even if the rest of the caption is brief." },
      { question: "Is this TikTok caption generator free?", answer: "Yes. You can generate captions without an account. Free use is rate limited to a few runs per hour so the tool stays free for everyone." },
      { question: "Can I use it for Instagram Reels and YouTube Shorts?", answer: "Yes. Pick Instagram Reels or YouTube Shorts in the platform menu; the caption style adjusts to how each app's audience reads captions." },
    ],
    related: ["tiktok-hook-generator", "hashtag-generator", "tiktok-script-generator", "video-title-generator"],
    links: [
      { href: "/guides/how-to-write-a-tiktok-hook", title: "How to write a TikTok hook" },
      { href: "/tools/tiktok-hook-generator", title: "TikTok hook generator" },
    ],
  },
  {
    slug: "video-idea-generator",
    widget: "ideas",
    category: "AI writing",
    title: "Free Video Idea Generator for TikTok, Reels, Shorts",
    h1: "Video idea generator",
    shortName: "Video idea generator",
    keyword: "video idea generator",
    description:
      "Describe your niche or product and get 10 specific, filmable short-form video ideas across different formats. Free video idea generator, no signup.",
    lede: "No topic yet? Describe your niche, product or audience in one line and get ten specific, filmable video concepts instead of a blank page.",
    privacy: LLM_PRIVACY,
    body: [
      "Every other tool here assumes you already know what the video is about. This one is for the step before that: you know the niche or the product, but not the next ten things to film.",
      "The ideas are spread across formats on purpose so a week of posts does not look like the same video ten times: a how-to walkthrough, a myth-bust, a day-in-the-life moment, a before-and-after, a top-3 list, a reaction or review, a behind-the-scenes look, a common-mistake callout, a Q&A answer, and a trend tie-in.",
      "Each idea is one filmable sentence, not a vague theme, so you can read it and know roughly what to point the camera at. Pick the one that fits today and send it straight into the hook or script generator.",
    ],
    steps: [
      "Describe your niche, product or the kind of videos you post.",
      "Pick the platform and a tone (bold, funny, educational, story or salesy).",
      "Generate ten ideas, then take the one you like into the hook or script generator to write it up.",
    ],
    faqs: [
      { question: "I don't have a topic yet, what do I type in?", answer: "Describe your niche, product, or audience in a few words, for example 'a small bakery that wants more weekend foot traffic'. The generator turns that into ten specific video concepts." },
      { question: "Is this video idea generator free?", answer: "Yes. You can generate ideas without an account. Free use is rate limited to a few runs per hour so the tool stays free for everyone." },
      { question: "What do I do once I pick an idea?", answer: "Paste the idea into the hook generator for an opening line, or the script generator for a full timed script with voiceover and captions." },
      { question: "Can Menivor turn the idea straight into a video?", answer: "Yes. With a free Menivor account you paste a link or the idea itself and get a finished vertical video with a hook-first script, AI voiceover and word-by-word captions." },
    ],
    related: ["tiktok-hook-generator", "tiktok-script-generator", "video-title-generator"],
    links: [
      { href: "/tools/tiktok-script-generator", title: "TikTok script generator" },
      { href: "/tools/tiktok-hook-generator", title: "TikTok hook generator" },
    ],
  },
  {
    slug: "youtube-shorts-script-generator",
    widget: "script-shorts",
    category: "AI writing",
    title: "Free YouTube Shorts Script Generator, No Signup",
    h1: "YouTube Shorts script generator",
    shortName: "YouTube Shorts script generator",
    keyword: "youtube shorts script generator",
    description:
      "Get a timed YouTube Shorts script with a hook, beats with on-screen visual ideas and a call to action, sized to 15, 30 or 60 seconds. Free, no signup.",
    lede: "Turn a topic into a YouTube Shorts script: a hook for the first two seconds, three to five timed beats with on-screen visual ideas, and a call to action.",
    privacy: LLM_PRIVACY,
    body: [
      "Shorts gets judged by the same first few seconds as TikTok, but it lives inside YouTube search and the long-form ecosystem, which rewards a clear premise stated early and a call to action that fits the channel, not just the single clip.",
      "This generator defaults to the YouTube Shorts platform so the hook, pacing and call-to-action phrasing are written for that audience from the first result, rather than a generic script you then have to adjust.",
      "The same script flows straight into Menivor's voiceover and karaoke captions, so a working Shorts script becomes a finished, postable vertical video in the same pass instead of a separate editing step.",
    ],
    steps: [
      "Describe the Short: the topic, product or story, and who it is for.",
      "Pick a tone and a length (15, 30 or 60 seconds).",
      "Generate, then copy the script or continue into Menivor to render the voiceover and captions.",
    ],
    faqs: [
      { question: "How long should a YouTube Shorts script be?", answer: "Shorts run up to 3 minutes, but 15 to 30 seconds keeps completion rate high for most topics. Pick 60 seconds only when the idea genuinely needs the extra beats." },
      { question: "Does this work for TikTok and Reels too?", answer: "Yes. Switch the platform in the menu; the structure (hook, beats, call to action) stays the same across TikTok, Reels and Shorts." },
      { question: "Is this YouTube Shorts script generator free?", answer: "Yes. You can generate scripts without an account. Free use is rate limited to a few runs per hour so the tool stays free for everyone." },
      { question: "Can Menivor voice and render the Short for me?", answer: "Yes. With a free Menivor account the same script becomes a finished vertical video with an AI voiceover and word-by-word captions." },
    ],
    related: ["tiktok-script-generator", "video-title-generator", "tiktok-hook-generator"],
    links: [
      { href: "/for/youtube-shorts", title: "Menivor for YouTube Shorts" },
      { href: "/tools/video-title-generator", title: "Video title generator" },
    ],
  },
  {
    slug: "subtitle-generator",
    widget: "subtitles",
    category: "Captions and audio",
    title: "Free Subtitle Generator: Video or Audio to SRT/VTT",
    h1: "Subtitle and caption generator for video",
    shortName: "Subtitle generator",
    keyword: "subtitle generator",
    description:
      "Upload a short video or audio clip and get timed SRT or VTT subtitles in your browser with Whisper AI. Free caption generator, no upload, no signup.",
    lede: "Drop in a video or audio clip. An open-source Whisper speech model transcribes it in your browser and gives you timed captions as SRT or WebVTT.",
    privacy: BROWSER_AI_PRIVACY,
    body: [
      "Most viewers watch short-form video with the sound off, so captions are not optional. This tool writes timed captions for you using the open-source Whisper speech model running on your own device through WebAssembly or WebGPU, so the file never leaves your computer.",
      "Captions are split into readable lines of about 42 characters, the common subtitle guideline, and exported as SRT (for desktop and mobile video editors, Premiere Pro, DaVinci Resolve and YouTube uploads) or WebVTT (for web players). Short clips up to 10 minutes work best; the first run downloads the model, about 80 MB, and later runs reuse it.",
      "Whisper is accurate but not perfect. Read through the captions before you publish and fix names and jargon in the text box; the timings are kept when you edit.",
    ],
    steps: [
      "Choose a video or audio file (MP4, MOV, WebM, MP3, WAV or M4A, up to 10 minutes).",
      "Pick the spoken language, or leave it on English, and start. The first run downloads the model.",
      "Review the captions, then download SRT or VTT and import them into your editor or upload them to YouTube.",
    ],
    faqs: [
      { question: "Is my video uploaded anywhere?", answer: "No. The audio is decoded and transcribed in your browser. Only the open-source model files are downloaded from a public CDN." },
      { question: "Which subtitle formats can I download?", answer: "SRT and WebVTT. SRT is accepted by Premiere Pro, DaVinci Resolve, Final Cut (via import), most mobile editors and YouTube. VTT is the format HTML5 video players use." },
      { question: "How long can the video be?", answer: "Up to 10 minutes and 200 MB per file. Transcription speed depends on your device: a recent laptop handles a one-minute clip in well under a minute." },
      { question: "Can I get word-by-word animated captions?", answer: "This free tool gives standard subtitle lines. Menivor's video tool burns in word-by-word karaoke captions timed to each spoken word on the finished video." },
      { question: "Which languages are supported?", answer: "Whisper is multilingual. Choose the language from the menu for the best accuracy; English is the most accurate." },
    ],
    related: ["video-to-text", "srt-to-vtt", "subtitle-shifter", "ai-voiceover-generator"],
    links: [
      { href: "/tools/add-captions-to-video", title: "Add captions to video" },
      { href: "/tools/karaoke-caption-generator", title: "Karaoke caption generator" },
      { href: "/guides/how-to-add-karaoke-captions-to-videos", title: "How to add karaoke captions to videos" },
    ],
  },
  {
    slug: "video-to-text",
    widget: "transcript",
    category: "Captions and audio",
    title: "Free Video to Text Converter (Private, In-Browser)",
    h1: "Video to text converter",
    shortName: "Video to text",
    keyword: "video to text",
    description:
      "Convert a video or audio file to text with Whisper AI running in your browser. Free transcription, nothing uploaded, copy or download the transcript.",
    lede: "Turn a video or voice recording into a plain-text transcript you can copy, edit, or repurpose into posts, scripts and show notes.",
    privacy: BROWSER_AI_PRIVACY,
    body: [
      "Transcripts are the fastest way to repurpose a video: pull quotes for posts, turn a webinar into a blog outline, or find the 30 seconds worth clipping into a short. This converter gives you the full text of a recording without uploading it to anyone.",
      "It uses the same open-source Whisper speech model as our subtitle generator, run locally in your browser. You get the text as paragraphs, plus the option to grab timestamped SRT captions from the subtitle generator if you need timing.",
      "For YouTube videos you own, download the file from YouTube Studio and drop it in. We do not scrape other people's videos.",
    ],
    steps: [
      "Choose a video or audio file up to 10 minutes long.",
      "Select the spoken language and start. The model downloads once, then runs on your device.",
      "Copy the transcript or download it as a .txt file.",
    ],
    faqs: [
      { question: "Is this video to text converter really free?", answer: "Yes. It runs on your own device, so there is no server cost to pass on and no signup." },
      { question: "Can I convert a YouTube video to text?", answer: "For your own videos, download the file from YouTube Studio and use it here. YouTube also shows auto-generated transcripts under the video description for many public videos." },
      { question: "How accurate is the transcription?", answer: "Whisper is close to human accuracy on clear English speech. Music, crosstalk and heavy accents reduce accuracy, so skim the result before you publish it." },
      { question: "Can I turn the transcript into short videos?", answer: "Yes. Paste the key points into Menivor as a topic and it writes and renders vertical videos with a voiceover and captions." },
    ],
    related: ["subtitle-generator", "tiktok-script-generator", "srt-to-vtt"],
    links: [
      { href: "/guides/how-to-repurpose-a-webinar-into-shorts", title: "How to repurpose a webinar into Shorts" },
      { href: "/tools/screen-recording-to-video", title: "Screen recording to video" },
      { href: "/tools/tutorial-video-generator", title: "Tutorial video generator" },
    ],
  },
  {
    slug: "ai-voiceover-generator",
    widget: "voiceover",
    category: "Captions and audio",
    title: "Free AI Voiceover Generator (Text to Speech, WAV)",
    h1: "AI voiceover generator",
    shortName: "AI voiceover generator",
    keyword: "ai voiceover generator free",
    description:
      "Turn a script into a natural AI voiceover and download a WAV file. Free text to speech that runs in your browser with an open-weight model. No signup.",
    lede: "Paste a script, pick a voice and download a natural-sounding voiceover as WAV, generated on your device with an open-weight text-to-speech model.",
    privacy: BROWSER_AI_PRIVACY,
    body: [
      "Faceless videos, product demos and explainers all need a clean voiceover. This tool uses a compact open-weight speech model with 82 million parameters, released under the Apache 2.0 license, running locally in your browser. There is no character quota and no watermark.",
      "Pick from American and British English voices, paste up to 1,000 characters at a time and download the WAV file to drop into Premiere, DaVinci Resolve or any mobile editor. Short sentences and punctuation give the most natural pacing.",
      "The first run downloads the model (about 90 MB) and caches it. Generation speed depends on your device; WebGPU-capable browsers such as recent Chrome and Edge are fastest.",
    ],
    steps: [
      "Paste your script (up to 1,000 characters).",
      "Choose a voice and press Generate. The first run downloads the voice model.",
      "Play it back and download the WAV file.",
    ],
    faqs: [
      { question: "Can I use the voiceover commercially?", answer: "The model weights are released under Apache 2.0, which permits commercial use. Make sure the script itself is yours to use." },
      { question: "Is there a character limit?", answer: "Each generation takes up to 1,000 characters so it stays fast in the browser. For longer scripts, generate paragraph by paragraph." },
      { question: "Which languages are supported?", answer: "This tool offers American and British English voices, which are the model's strongest." },
      { question: "Can Menivor add the voiceover to a finished video?", answer: "Yes. Menivor writes the script, voices it, adds footage and burns in word-by-word captions, then gives you a ready-to-post MP4." },
    ],
    related: ["tiktok-script-generator", "subtitle-generator", "tiktok-hook-generator"],
    links: [
      { href: "/tools/faceless-video-generator", title: "Faceless video generator" },
      { href: "/guides/how-to-make-a-faceless-tiktok-account", title: "How to make a faceless TikTok account" },
      { href: "/tools/explainer-video-generator", title: "AI explainer video generator" },
    ],
  },
  {
    slug: "srt-to-vtt",
    widget: "srt-vtt",
    category: "Captions and audio",
    title: "SRT to VTT Converter (and VTT to SRT), Free Online",
    h1: "SRT to VTT converter",
    shortName: "SRT to VTT converter",
    keyword: "srt to vtt",
    description:
      "Convert SRT subtitles to WebVTT or VTT back to SRT instantly in your browser. Free online converter: paste or upload, preview the result and download.",
    lede: "Paste or upload an SRT or VTT file and convert it to the other format instantly. Timings, line breaks and cue order are preserved.",
    privacy: BROWSER_PRIVACY,
    body: [
      "SRT and WebVTT carry the same information, timed lines of text, with small syntax differences. VTT starts with a WEBVTT header, uses a period before milliseconds (00:00:01.000) and does not need cue numbers. SRT numbers every cue and uses a comma (00:00:01,000).",
      "HTML5 video players and most web platforms expect VTT, while video editors and YouTube accept SRT. This converter handles both directions, strips VTT-only extras such as NOTE and STYLE blocks and cue settings when going to SRT, and renumbers cues cleanly.",
      "The conversion runs in your browser, so it is instant and private, and it works on files with thousands of cues.",
    ],
    steps: [
      "Paste subtitle text or choose an .srt or .vtt file. The input format is detected automatically.",
      "Pick the output format: VTT or SRT.",
      "Copy the result or download the converted file.",
    ],
    faqs: [
      { question: "What is the difference between SRT and VTT?", answer: "Both are plain-text subtitle formats. VTT (WebVTT) begins with a WEBVTT line, uses a period in timestamps and supports styling and positioning. SRT numbers each cue and uses a comma in timestamps. Players on the web use VTT; editors and YouTube take SRT." },
      { question: "Does converting lose any data?", answer: "Text and timings are preserved exactly. VTT-only styling, positioning and NOTE blocks have no SRT equivalent, so they are dropped when converting to SRT." },
      { question: "Can I convert VTT to SRT too?", answer: "Yes. Choose SRT as the output and paste or upload a VTT file." },
      { question: "Is my subtitle file uploaded?", answer: "No. The conversion is plain JavaScript running in your browser." },
    ],
    related: ["subtitle-shifter", "subtitle-generator", "video-to-text"],
    links: [
      { href: "/tools/add-captions-to-video", title: "Add captions to video" },
      { href: "/guides/how-to-add-karaoke-captions-to-videos", title: "How to add karaoke captions to videos" },
    ],
  },
  {
    slug: "subtitle-shifter",
    widget: "shifter",
    category: "Captions and audio",
    title: "Subtitle Shifter: Fix SRT/VTT Timing Online, Free",
    h1: "Subtitle shifter",
    shortName: "Subtitle shifter",
    keyword: "subtitle shifter",
    description:
      "Shift SRT or VTT subtitle timing earlier or later by any amount, or fix frame-rate drift. Free online subtitle time shifter that runs in your browser.",
    lede: "Subtitles out of sync? Move every cue earlier or later by a fixed offset, or stretch timings to fix drift between 23.976, 24, 25 and 30 fps versions.",
    privacy: BROWSER_PRIVACY,
    body: [
      "Subtitles usually go out of sync for one of two reasons. Either they are consistently early or late, often because an intro was trimmed or added, which a fixed offset fixes. Or they start in sync and drift further apart over time, which means the subtitle was timed for a different frame rate and needs to be stretched.",
      "Enter a positive offset to delay subtitles or a negative one to show them earlier. For drift, pick the frame rate the subtitles were made for and the frame rate of your video; the tool scales every timestamp by the ratio. Cues pushed before 00:00:00 are removed.",
      "Tip: find one line near the start and one near the end, note how far off each is, and you will know immediately whether you need an offset (same gap) or a frame-rate fix (growing gap).",
    ],
    steps: [
      "Paste or upload your .srt or .vtt file.",
      "Enter the offset in seconds (for example 2.5 or -1.2), and optionally a frame-rate correction.",
      "Download the shifted file in the same format, or switch the output to the other format.",
    ],
    faqs: [
      { question: "How do I make subtitles appear earlier?", answer: "Use a negative offset. For example, -2 shows every line two seconds earlier. Lines that would start before zero are clamped or removed." },
      { question: "Why do my subtitles drift out of sync over time?", answer: "The subtitle was timed for a different frame rate, typically 23.976 vs 25 fps. Use the frame-rate correction to stretch the timings by the right ratio." },
      { question: "Can I shift subtitles in VLC instead?", answer: "VLC can delay subtitles during playback with the G and H keys, but it does not save the change. This tool writes a corrected file you can reuse anywhere." },
      { question: "Does it support VTT files?", answer: "Yes, both SRT and WebVTT are supported for input and output." },
    ],
    related: ["srt-to-vtt", "subtitle-generator", "video-bitrate-calculator"],
    links: [
      { href: "/tools/karaoke-caption-generator", title: "Karaoke caption generator" },
      { href: "/tools/add-captions-to-video", title: "Add captions to video" },
    ],
  },
  {
    slug: "aspect-ratio-calculator",
    widget: "aspect",
    category: "Calculators",
    title: "Video Aspect Ratio Calculator for TikTok, Reels, Shorts",
    h1: "Video aspect ratio calculator",
    shortName: "Aspect ratio calculator",
    keyword: "aspect ratio calculator",
    description:
      "Calculate pixel sizes for any aspect ratio, simplify a resolution to its ratio, and see how footage fits 9:16 for TikTok, Reels and Shorts. Free calculator.",
    lede: "Find the exact pixel size for 9:16, 4:5, 1:1 or any ratio, reduce a resolution to its ratio, and see what happens when landscape footage goes vertical.",
    privacy: BROWSER_PRIVACY,
    body: [
      "TikTok, Instagram Reels and YouTube Shorts are all built for 9:16 vertical video at 1080 x 1920 pixels. Uploading anything else means black bars or an automatic crop that can cut off faces, text and products.",
      "This calculator does three jobs. It solves the missing width or height for any ratio (rounded to even pixels, which H.264 and H.265 encoders require), it simplifies a resolution such as 1080 x 1350 to its ratio (4:5), and it shows how a source frame fits a target frame either padded with bars or cropped to fill.",
      "The table below lists the recommended upload sizes for each major short-form placement, including the safe-zone notes that keep your captions clear of platform buttons.",
    ],
    steps: [
      "Enter a ratio (such as 9:16) and either a width or a height to get the other side.",
      "Or enter any width and height to see the simplified ratio.",
      "Use the fit check to see how your footage lands inside a 1080 x 1920 frame, padded or cropped.",
    ],
    faqs: [
      { question: "What is the aspect ratio for TikTok, Reels and Shorts?", answer: "9:16 vertical. The recommended resolution is 1080 x 1920 pixels for all three." },
      { question: "What is 1080 x 1350 in aspect ratio?", answer: "4:5. It is the tallest portrait ratio the Instagram feed shows without cropping." },
      { question: "Why should dimensions be even numbers?", answer: "H.264 and H.265 encode colour at half resolution (4:2:0), so width and height must be divisible by 2. Odd sizes cause export errors or a one-pixel edge." },
      { question: "How do I turn a landscape video into 9:16?", answer: "Either crop to the centre (fills the screen but cuts the sides) or pad with bars or a blurred background (keeps everything but shrinks it). The fit check here shows the exact pixel sizes for both." },
    ],
    related: ["video-bitrate-calculator", "subtitle-generator", "tiktok-hook-generator"],
    links: [
      { href: "/for/tiktok", title: "Menivor for TikTok" },
      { href: "/for/instagram-reels", title: "Menivor for Instagram Reels" },
      { href: "/tools/screen-recording-to-video", title: "Screen recording to vertical video" },
    ],
  },
  {
    slug: "video-bitrate-calculator",
    widget: "bitrate",
    category: "Calculators",
    title: "Video Bitrate and File Size Calculator (Free)",
    h1: "Video bitrate and file size calculator",
    shortName: "Bitrate calculator",
    keyword: "video bitrate calculator",
    description:
      "Work out video file size from bitrate and duration, or the bitrate needed to hit a target size. Free calculator with recommended bitrates for 1080p and 4K.",
    lede: "Two calculators in one: file size from bitrate and length, or the video bitrate that fits a size limit, with audio and container overhead accounted for.",
    privacy: BROWSER_PRIVACY,
    body: [
      "File size is bitrate multiplied by duration. An 8,000 kbps video with 128 kbps audio runs about 61 MB per minute. That makes it easy to check whether an export will fit an upload limit, an email attachment or a messaging app before you render.",
      "Going the other way, enter a target size and duration and the calculator returns the video bitrate to set in your encoder, after reserving the audio bitrate and a small allowance for the MP4 container.",
      "The bits-per-pixel figure is a quick quality sanity check. For H.264 at 30 fps, values around 0.1 look clean for typical footage; much lower and fast motion will smear. H.265 and AV1 reach similar quality at roughly half the bitrate.",
    ],
    steps: [
      "Pick a mode: file size from bitrate, or bitrate for a target size.",
      "Enter the duration (seconds or mm:ss) and the bitrates or target size.",
      "Read the result and the bits-per-pixel quality check, and set the bitrate in your export settings.",
    ],
    faqs: [
      { question: "How do I calculate video file size?", answer: "File size in megabytes = (video kbps + audio kbps) x seconds / 8 / 1000. For example, 8,128 kbps for 60 seconds is about 61 MB." },
      { question: "What bitrate should I use for 1080p vertical video?", answer: "For uploads, 8 to 12 Mbps H.264 at 30 fps and 12 to 15 Mbps at 60 fps (YouTube's published SDR recommendations). Platforms re-encode anyway, so a clean high-bitrate upload gives them the best source." },
      { question: "Why is my exported file bigger than calculated?", answer: "Variable bitrate encoders can overshoot the average on complex scenes, and some exporters add a higher audio bitrate. Use two-pass encoding or a max-rate cap for a hard limit." },
      { question: "Does this work for H.265 and AV1?", answer: "Yes. File size depends only on bitrate and duration. H.265 and AV1 just need a lower bitrate for the same quality." },
    ],
    related: ["aspect-ratio-calculator", "subtitle-shifter", "srt-to-vtt"],
    links: [
      { href: "/for/youtube-shorts", title: "Menivor for YouTube Shorts" },
      { href: "/tools/youtube-shorts-maker", title: "YouTube Shorts maker" },
    ],
  },
  {
    slug: "script-length-calculator",
    widget: "script-length",
    category: "Calculators",
    title: "Video Script Length Calculator: Words to Minutes",
    h1: "Video script length calculator",
    shortName: "Script length calculator",
    keyword: "script length calculator",
    description:
      "Convert a video script's word count to its spoken length, or a target length to the words you need, at slow, natural or fast speaking paces. Free calculator.",
    lede: "Work out how many words a script needs for a target video length, or how long a script you already wrote will run, at three speaking paces.",
    privacy: BROWSER_PRIVACY,
    body: [
      "Script length and spoken word count are not the same as reading time, because a script includes pauses, pacing changes and visual beats that a silent read skips over. Working from a words-per-minute pace gets much closer to the real runtime.",
      "Natural speaking pace for voiceover and explainer videos runs about 150 words per minute. Slower, deliberate delivery drops to around 120 wpm, and fast, energetic delivery (common in short-form hooks and ads) runs up to 170 wpm or more.",
      "Use this to size a script before recording: pick a target video length, get the word budget, then write to it. Or paste in a word count from a script you already have and see how long it will actually run at each pace.",
    ],
    steps: [
      "Pick a speaking pace (slow, natural or fast).",
      "Choose whether you're calculating from a target video length or from a script you already have.",
      "Enter the video length or the word count to get the other number.",
    ],
    faqs: [
      { question: "How many words is a 1 minute video script?", answer: "About 150 words at a natural speaking pace, 120 for slow and deliberate delivery, or up to 170 for fast, energetic delivery." },
      { question: "How many words is a 60 second TikTok or Reel script?", answer: "Short-form scripts tend to run faster than long-form, often 160 to 180 words per minute, so a 60-second script is usually 160 to 180 words." },
      { question: "Does this account for pauses?", answer: "The words-per-minute pace already reflects natural speech including normal pauses. For a script with long dramatic pauses or on-screen-only text, add extra seconds manually." },
      { question: "How many words is a 10 minute video?", answer: "At a natural 150 wpm pace, about 1,500 words. At a slower, more deliberate pace it can be closer to 1,200." },
    ],
    related: ["video-title-generator", "ai-voiceover-generator", "video-bitrate-calculator"],
    links: [
      { href: "/tools/ai-voiceover-generator", title: "AI voiceover generator" },
      { href: "/tools/video-idea-generator", title: "Video idea generator" },
    ],
  },
];

export const FREE_TOOL_SLUGS: readonly string[] = FREE_TOOLS.map((tool) => tool.slug);

export const FREE_TOOL_CATEGORIES: readonly FreeToolCategory[] = [
  "AI writing",
  "Captions and audio",
  "Calculators",
];

export function getFreeTool(slug: string): FreeTool | undefined {
  return FREE_TOOLS.find((tool) => tool.slug === slug);
}
