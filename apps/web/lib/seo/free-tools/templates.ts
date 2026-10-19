/**
 * Instant, offline results for the free writing tools: proven short-form
 * formulas filled with the visitor's topic. Used whenever the AI generator is
 * unavailable (not configured, rate limited, or erroring), so every tool
 * always returns something useful. Pure and seeded, so "shuffle" gives new
 * variants and tests are deterministic.
 */

import type { GenerateOutput, GenerateRequest } from "./generate";

const STOPWORDS = new Set(
  "a an and are as at be but by for from how i in into is it its my of on or our so that the their this to was we what when who why will with you your about after before can do does get got have just more most new not now only over than them then there these they very".split(
    " ",
  ),
);

/** Small deterministic PRNG (mulberry32). */
export function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pickOne<T>(items: readonly T[], rand: () => number): T {
  return items[Math.floor(rand() * items.length) % items.length] as T;
}

/** Topic cleaned for insertion into a sentence. */
export function topicPhrase(topic: string): string {
  return topic
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[.!?]+$/, "")
    .replace(/^(a|an|the)\s+/i, "")
    .slice(0, 120);
}

/**
 * The core noun phrase of a topic for use inside a hook or title: cut at the
 * first clause marker, at most six words, first letter lowercased unless the
 * word is an acronym or a proper-looking brand (internal capitals).
 */
export function corePhrase(topic: string): string {
  const base = topicPhrase(topic);
  const cut = base.split(/,|;|:| - | (?:for|who|that|which|so|because|to help|when|where|while) /i)[0] ?? base;
  const words = cut.trim().split(" ").slice(0, 6);
  const first = words[0] ?? "";
  const keepCase = /^[A-Z0-9]{2,}$/.test(first) || /[a-z][A-Z]/.test(first);
  if (first && !keepCase) words[0] = first.charAt(0).toLowerCase() + first.slice(1);
  return words.join(" ") || base;
}

/** Content keywords in order of appearance, without stopwords or duplicates. */
export function keywords(topic: string, limit = 6): string[] {
  const words = topic
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\p{L}\p{N}\s-]/gu, " ")
    .split(/[\s-]+/)
    .filter((word) => word.length > 2 && !STOPWORDS.has(word));
  return [...new Set(words)].slice(0, limit);
}

/** One formula list per hook angle, in the order the AI prompt uses. */
const HOOK_ANGLES: readonly (readonly string[])[] = [
  ["Nobody talks about this part of {t}.", "The thing about {t} that nobody tells you.", "I wish someone had told me this about {t} sooner."],
  ["This changed how I think about {t}.", "{T} is easier than you think. Here is proof.", "You can get {t} right in under a minute."],
  ["Stop doing this if you care about {t}.", "The biggest mistake people make with {t}.", "You are probably getting {t} wrong."],
  ["POV: you finally figured out {t}.", "POV: someone shows you the right way to do {t}.", "POV: {t} actually works for you this time."],
  ["Why does nobody explain {t} like this?", "Want better results with {t}? Watch this.", "What if {t} took half the effort?"],
  ["Before vs after: {t}.", "My {t} before I learned this, and after.", "Same {t}, one small change. Look at the difference."],
  ["3 things I would do differently with {t}.", "3 {t} tips you can use today.", "The only 3 steps you need for {t}."],
  ["Unpopular opinion: most advice about {t} is wrong.", "Hot take: {t} is not the problem. This is.", "Everyone says the same thing about {t}. I disagree."],
  ["If {t} keeps frustrating you, this is for you.", "Tired of {t} not working? Same. Until this.", "This is your sign to fix {t} today."],
  ["If you are into {t}, save this.", "Calling everyone who cares about {t}.", "Send this to a friend who needs help with {t}."],
];

/** One formula list per caption angle, in the order the AI prompt uses. */
const CAPTION_ANGLES: readonly (readonly string[])[] = [
  ["This is your sign to try {t}.", "{T}, finally explained.", "Here is what I wish I knew about {t} sooner."],
  ["Is this the easiest way to {t}? Tell me what I'm missing.", "Does anyone else struggle with {t}?"],
  ["If {t} has been frustrating you, you're not alone.", "Nobody warns you about this part of {t}."],
  ["{T}. That's it. That's the post.", "{T} changes everything once you see it."],
  ["3 things about {t} I didn't expect.", "The {t} tip that actually works."],
  ["Behind the scenes of how I do {t}.", "What {t} actually looks like, no filter."],
  ["Shoutout to everyone figuring out {t} right now.", "This one's for the {t} community."],
  ["Try {t} for a week and tell me how it goes.", "Bet you haven't tried {t} like this."],
  ["Why does {t} feel harder than it should be?", "What's your biggest {t} question?"],
  ["{T}, in case you needed a reminder.", "A quick note on {t} before you scroll on."],
];

/** One formula list per video-idea angle, in the order the AI prompt uses. */
const IDEA_ANGLES: readonly (readonly string[])[] = [
  ["Film a step-by-step walkthrough of how you do {t}.", "Show the exact process behind {t} from start to finish."],
  ["Bust a common myth about {t} and show the real answer.", "React to the most common wrong advice about {t}."],
  ["Film a day-in-the-life moment that involves {t}.", "Show a normal day where {t} actually comes up."],
  ["Show a before-and-after result from {t}.", "Compare the old way of doing {t} to the new way."],
  ["List the top 3 things you'd tell a beginner about {t}.", "Rank 3 mistakes people make with {t}, worst to least bad."],
  ["Give an honest review or reaction to a product or method tied to {t}.", "Try something new related to {t} on camera and react live."],
  ["Show the messy, unfiltered behind-the-scenes of {t}.", "Reveal something about {t} most people never see."],
  ["Call out the one mistake that quietly ruins {t} for people.", "Explain the mistake you made with {t} so viewers can skip it."],
  ["Answer the question you get asked most about {t}.", "Do a quick Q&A on {t} using real questions you've received."],
  ["Put your own spin on a trending format using {t}.", "Tie a current trend or sound to {t} in your own way."],
];

const TITLE_FORMULAS: readonly string[] = [
  "How to {t} (Step by Step)",
  "{T}: The Complete Beginner Guide",
  "5 {T} Tips That Actually Work",
  "{T} Mistakes to Avoid",
  "Is {T} Worth It? Honest Breakdown",
  "{T} Explained Simply",
  "I Tried {T} So You Do Not Have To",
  "{T}: What Nobody Tells You",
  "The Fastest Way to {t}",
  "{T} Before and After",
  "{T} vs the Usual Way: What Changed",
  "Why {T} Matters More Than You Think",
];

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function titleCase(text: string): string {
  return text
    .split(" ")
    .map((word, index) => (index > 0 && STOPWORDS.has(word.toLowerCase()) ? word.toLowerCase() : capitalize(word)))
    .join(" ");
}

function fill(formula: string, topic: string, titled = false): string {
  const t = titled ? titleCase(topic) : topic;
  return formula.replace(/\{T\}/g, titled ? t : capitalize(t)).replace(/\{t\}/g, t);
}

function shuffle<T>(items: readonly T[], rand: () => number): T[] {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rand() * (i + 1));
    [copy[i], copy[j]] = [copy[j] as T, copy[i] as T];
  }
  return copy;
}

export function templateHooks(topic: string, seed = 1): string[] {
  const rand = seeded(seed);
  const t = corePhrase(topic);
  return HOOK_ANGLES.map((angle) => fill(pickOne(angle, rand), t));
}

export function templateCaptions(topic: string, seed = 1): string[] {
  const rand = seeded(seed);
  const t = corePhrase(topic);
  return CAPTION_ANGLES.map((angle) => fill(pickOne(angle, rand), t));
}

export function templateIdeas(topic: string, seed = 1): string[] {
  const rand = seeded(seed);
  const t = corePhrase(topic);
  return IDEA_ANGLES.map((angle) => fill(pickOne(angle, rand), t));
}

export function templateTitles(topic: string, seed = 1): string[] {
  const rand = seeded(seed);
  const t = corePhrase(topic);
  const maxLen = 70;
  return shuffle(TITLE_FORMULAS, rand)
    .slice(0, 10)
    .map((formula) => fill(formula, t, true))
    .map((title) => (title.length > maxLen ? `${title.slice(0, maxLen - 1).trimEnd()}…` : title));
}

const PLATFORM_TAGS: Record<GenerateRequest["platform"], readonly string[]> = {
  tiktok: ["#tiktoktips", "#learnontiktok", "#tiktok"],
  reels: ["#reelsinstagram", "#reels", "#instagram"],
  shorts: ["#youtubeshorts", "#shorts", "#youtube"],
  youtube: ["#youtube", "#howto", "#tutorial"],
};

/** Words that make weak hashtag pairs ("#easyhigh", "#proteinideas"). */
const GENERIC = new Set("easy best quick simple good great top free cheap fast ultimate ideas tips way ways guide make made".split(" "));

export function templateHashtags(topic: string, platform: GenerateRequest["platform"]): string[] {
  const words = keywords(topic, 6);
  const singles = words.map((word) => `#${word}`);
  const pairs = words
    .slice(0, -1)
    .map((word, index) => [word, words[index + 1] ?? ""] as const)
    .filter(([first, second]) => !GENERIC.has(first) && !GENERIC.has(second))
    .map(([first, second]) => `#${first}${second}`);
  const head = words[0];
  const intents = head ? [`#${head}tips`, `#${head}ideas`, `#${head}hacks`, `#${head}tutorial`] : [];
  const all = [...pairs, ...singles, ...intents, ...(PLATFORM_TAGS[platform] ?? [])];
  return [...new Set(all)].slice(0, 20);
}

export function templateScript(topic: string, lengthSec: number, seed = 1): GenerateOutput {
  const t = corePhrase(topic);
  const hook = templateHooks(topic, seed)[2] ?? `Stop scrolling if you care about ${t}.`;
  const beatCount = lengthSec <= 15 ? 2 : lengthSec <= 30 ? 3 : 5;
  const beats = [
    { say: `Here is the problem with ${t}: [the one pain your viewer feels].`, show: "Close-up of the problem, or you pointing at on-screen text" },
    { say: `Do this instead: [your first concrete step for ${t}].`, show: "Screen recording or hands-on shot of step one" },
    { say: "Then [second step], which takes about [time].", show: "Quick cut to the result of step two" },
    { say: "Most people skip [the detail that makes it work]. Do not.", show: "Zoom on the detail with a text callout" },
    { say: "Here is the result: [the outcome, shown not told].", show: "Before and after side by side" },
  ].slice(0, beatCount);
  return {
    kind: "script",
    script: { hook, beats, cta: `Follow for more on ${t}, and save this so you can try it later.` },
  };
}

/** Offline result for any generator request. */
export function templateOutput(req: GenerateRequest, seed = 1): GenerateOutput {
  switch (req.kind) {
    case "hooks":
      return { kind: "list", items: templateHooks(req.topic, seed) };
    case "titles":
      return { kind: "list", items: templateTitles(req.topic, seed) };
    case "hashtags":
      return { kind: "list", items: templateHashtags(req.topic, req.platform) };
    case "script":
      return templateScript(req.topic, req.lengthSec, seed);
    case "captions":
      return { kind: "list", items: templateCaptions(req.topic, seed) };
    case "ideas":
      return { kind: "list", items: templateIdeas(req.topic, seed) };
  }
}
