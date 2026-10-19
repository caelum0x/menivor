/**
 * One-flow create: the pure planning layer behind the default Create tab.
 *
 * The React Native port of apps/web/src/features/create-compose/one-flow/plan.ts.
 * Keep the two in step: the request shapes and hook templates must match so a
 * run started on the phone is indistinguishable server-side from one started
 * on the web.
 *
 * A creator types a topic OR pastes a product/page link and gets three reel
 * variants with different opening hooks. Everything here is pure (no network,
 * no React, no native modules) so it is unit-tested under plain Node.
 *
 * - Topic in: ONE `POST /jobs` with `variants: 3`. The backend fans it out
 *   into three jobs under one batch and gives each variant its own opening
 *   hook angle (`hook_style`), then registers the batch as an experiment.
 * - Link in: `POST /ingest/url` extracts the page (title, description,
 *   features). We write three scripts that share the page's real content and
 *   differ ONLY in the opening hook, one `POST /jobs` each, then
 *   `POST /experiments/runs` links them into one 1-body/N-hooks experiment so
 *   the remake-winner loop tracks the run.
 *
 * Every preset except the faceless story renders an AI presenter. The faceless
 * story is `captions_only` with a TTS voice: the pipeline narrates the script
 * over curated background footage.
 */

import {
  JobState,
  type Job,
  type JobCreateRequest,
  type JobStage,
  type Language,
  type Layout,
} from "@/lib/types";

/** Three variants per run: the backend's `MAX_REEL_JOB_VARIANTS`. */
export const VARIANT_COUNT = 3;
/** One finished reel costs one credit; a failed render refunds it. */
export const CREDITS_PER_REEL = 1;
/** Reel length requested from the pipeline (seconds). */
export const TARGET_DURATION_S = 30;
/** Default karaoke caption style (the pipeline default). */
export const DEFAULT_CAPTION_STYLE = "karaoke_yellow";
/** Longest input the one box accepts. */
export const MAX_INPUT_LENGTH = 600;

const MAX_TOPIC_LENGTH = 300;
const MAX_SUBJECT_LENGTH = 200;
const MAX_DESCRIPTION_BEAT = 220;
const MAX_FEATURE_BEAT = 140;
const MAX_FEATURE_BEATS = 3;
const JOB_ID_PATTERN = /^[A-Za-z0-9_-]{6,64}$/;
const BARE_DOMAIN_PATTERN = /^[a-z0-9-]+(\.[a-z0-9-]+)+(:\d+)?(\/\S*)?$/i;

// ---------------------------------------------------------------------------
// Source parsing
// ---------------------------------------------------------------------------

export type SourceKind = "topic" | "link";

export interface ParsedSource {
  readonly kind: SourceKind;
  /** The topic text (topic) or the normalized absolute URL (link). */
  readonly value: string;
}

function normalizeUrl(candidate: string): string | null {
  try {
    const url = new URL(candidate);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (!url.hostname.includes(".")) return null;
    return url.toString();
  } catch {
    return null;
  }
}

/**
 * Classify the single input box. A value with no whitespace that is an
 * http(s) URL, or looks like a bare domain (`shop.com/p/1`), is a link; any
 * other non-empty text is a topic. Returns `null` for empty input.
 */
export function parseSource(raw: string | null | undefined): ParsedSource | null {
  const text = (raw ?? "").trim();
  if (!text) return null;
  if (!/\s/.test(text)) {
    if (/^https?:\/\//i.test(text)) {
      const url = normalizeUrl(text);
      if (url) return { kind: "link", value: url };
    } else if (BARE_DOMAIN_PATTERN.test(text)) {
      const url = normalizeUrl(`https://${text}`);
      if (url) return { kind: "link", value: url };
    }
  }
  return { kind: "topic", value: text.slice(0, MAX_TOPIC_LENGTH) };
}

/** The bare host of a URL (`www.` stripped), or the input when unparsable. */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

export type PresetId = "talking" | "product" | "story" | "faceless";

export interface CreatePreset {
  readonly id: PresetId;
  readonly title: string;
  readonly blurb: string;
  readonly layout: Layout;
  /** Curated background clip preferred for this preset, when available. */
  readonly preferredBackground: string;
  /** False for the faceless story: narration only, no AI presenter. */
  readonly needsPresenter: boolean;
}

export const CREATE_PRESETS: readonly CreatePreset[] = [
  {
    id: "talking",
    title: "Talking presenter",
    blurb: "An AI presenter explains it in a corner bubble, with word-by-word captions.",
    layout: "pip",
    preferredBackground: "",
    needsPresenter: true,
  },
  {
    id: "product",
    title: "Product ad",
    blurb: "The presenter fills the screen for the hook, then drops into a bubble.",
    layout: "hook_intro",
    preferredBackground: "",
    needsPresenter: true,
  },
  {
    id: "story",
    title: "Story split-screen",
    blurb: "Presenter on top, looping background footage below. The classic story format.",
    layout: "split",
    preferredBackground: "block-runner",
    needsPresenter: true,
  },
  {
    id: "faceless",
    title: "Faceless story",
    blurb: "A narrator voice over looping background footage, with word-by-word captions. No presenter.",
    layout: "captions_only",
    preferredBackground: "block-runner",
    needsPresenter: false,
  },
];

export function findPreset(id: string | null | undefined): CreatePreset | undefined {
  return CREATE_PRESETS.find((preset) => preset.id === id);
}

const FALLBACK_PRESET: CreatePreset = {
  id: "talking",
  title: "Talking presenter",
  blurb: "",
  layout: "pip",
  preferredBackground: "",
  needsPresenter: true,
};

/** The preset for `id`, falling back to the talking presenter. */
export function resolvePreset(id: string | null | undefined): CreatePreset {
  return findPreset(id) ?? findPreset("talking") ?? FALLBACK_PRESET;
}

/** Link input defaults to the product-ad preset, a topic to the presenter. */
export function defaultPresetFor(kind: SourceKind): PresetId {
  return kind === "link" ? "product" : "talking";
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** Opening-hook angles; the same ids as the API's `hook_style`. */
export type HookStyleId = "pov" | "question" | "nobody_tells_you" | "stat" | "story";
/** Any angle a variant can open with (topic runs may use all five). */
export type HookAngleId = HookStyleId;
/** The angles link mode writes itself, one per variant. */
export type LinkAngleId = "pov" | "question" | "nobody_tells_you";

export interface HookAngle {
  readonly id: LinkAngleId;
  readonly label: string;
}

const HOOK_STYLE_LABELS: Record<HookStyleId, string> = {
  pov: "POV hook",
  question: "Question hook",
  nobody_tells_you: "What-nobody-tells-you hook",
  stat: "Number hook",
  story: "Story hook",
};

/** The three link-mode angles, in variant order. */
export const HOOK_ANGLES: readonly HookAngle[] = (
  ["pov", "question", "nobody_tells_you"] as const
).map((id): HookAngle => ({ id, label: HOOK_STYLE_LABELS[id] }));

export function isHookStyle(value: unknown): value is HookStyleId {
  return (
    typeof value === "string" && Object.prototype.hasOwnProperty.call(HOOK_STYLE_LABELS, value)
  );
}

/** Display label for a hook angle id ("" when unknown or absent). */
export function hookStyleLabel(id: string | undefined | null): string {
  return isHookStyle(id) ? HOOK_STYLE_LABELS[id] : "";
}

const HOOK_TEMPLATES: Record<"en" | "tr", Record<LinkAngleId, (t: string) => string>> = {
  en: {
    pov: (t) => `POV: you just found ${t}.`,
    question: (t) => `Is ${t} actually worth it? Here is the honest answer.`,
    nobody_tells_you: (t) => `Here is what nobody tells you about ${t}.`,
  },
  tr: {
    pov: (t) => `POV: ${t} ile yeni tanıştın.`,
    question: (t) => `${t} gerçekten değer mi? İşte dürüst cevap.`,
    nobody_tells_you: (t) => `${t} hakkında kimsenin söylemediği şey şu.`,
  },
};

const CTA: Record<"en" | "tr", string> = {
  en: "Check the link to try it.",
  tr: "Denemek için linke göz at.",
};

const FALLBACK_TITLE: Record<"en" | "tr", string> = {
  en: "this",
  tr: "bu ürün",
};

function scriptLanguage(language: Language): "en" | "tr" {
  return language === "tr" ? "tr" : "en";
}

function clamp(text: string, max: number): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut).replace(/[,;:\s]+$/, "")}.`;
}

function asSentence(text: string): string {
  const clean = text.trim();
  if (!clean) return "";
  return /[.!?…]$/.test(clean) ? clean : `${clean}.`;
}

/** The hook line for one angle, with the page title filled in. */
export function buildHook(angle: LinkAngleId, title: string, language: Language): string {
  const lang = scriptLanguage(language);
  const subject =
    clamp(title.replace(/[.!?]+$/, ""), 80).replace(/\.$/, "") || FALLBACK_TITLE[lang];
  return HOOK_TEMPLATES[lang][angle](subject);
}

export interface PageContent {
  readonly title: string;
  readonly description: string;
  readonly features: readonly string[];
}

/**
 * The shared body for every link variant: the page's own description and up
 * to three features, then a call to action. Built only from extracted page
 * content, so nothing is invented about the product.
 */
export function buildLinkBody(content: PageContent, language: Language): string[] {
  const lang = scriptLanguage(language);
  const beats: string[] = [];
  const description = asSentence(clamp(content.description ?? "", MAX_DESCRIPTION_BEAT));
  if (description) beats.push(description);
  for (const feature of (content.features ?? []).slice(0, MAX_FEATURE_BEATS)) {
    const beat = asSentence(clamp(String(feature ?? ""), MAX_FEATURE_BEAT));
    if (beat) beats.push(beat);
  }
  if (beats.length === 0) {
    const title = clamp(content.title ?? "", 80);
    beats.push(asSentence(title ? `${title} is worth a look` : "This is worth a look"));
  }
  beats.push(CTA[lang]);
  return beats;
}

export interface LinkVariantPlan {
  readonly angle: LinkAngleId;
  readonly hook: string;
  /** Hook on the first line (the API derives a job's hook from line one). */
  readonly script: string;
}

/** Three scripts with the SAME body and a DIFFERENT opening hook each. */
export function planLinkVariants(content: PageContent, language: Language): LinkVariantPlan[] {
  const body = buildLinkBody(content, language);
  return HOOK_ANGLES.map((angle) => {
    const hook = buildHook(angle.id, content.title ?? "", language);
    return { angle: angle.id, hook, script: [hook, ...body].join("\n\n") };
  });
}

// ---------------------------------------------------------------------------
// Catalog defaults
// ---------------------------------------------------------------------------

/** A voice row as returned by `GET /voices` (id under `voice_id` or `id`). */
export interface VoiceLike {
  readonly voice_id?: unknown;
  readonly id?: unknown;
  readonly name?: unknown;
}

/** The bare provider id of a voice row ("" when missing). */
export function voiceIdOf(voice: VoiceLike): string {
  const raw = voice.voice_id ?? voice.id;
  return typeof raw === "string" ? raw : "";
}

/** The avatar's paired voice when the catalog carries it, else the first voice. */
export function defaultVoiceFor(
  avatarVoiceName: string | undefined | null,
  voices: readonly VoiceLike[],
): string {
  const paired = (avatarVoiceName ?? "").replace(/^elevenlabs:/, "");
  if (paired && voices.some((voice) => voiceIdOf(voice) === paired)) return paired;
  return voices.map(voiceIdOf).find(Boolean) ?? "";
}

/** Pick a background: the preset's preferred clip, else the first available. */
export function pickBackground(
  clips: readonly { id: string; available: boolean }[],
  preferred: string,
): string {
  const available = clips.filter((clip) => clip.available);
  if (preferred) {
    const match = available.find((clip) => clip.id === preferred);
    if (match) return match.id;
  }
  return available[0]?.id ?? "";
}

/**
 * What the server is missing for this preset, as human phrases. Empty when the
 * flow can render. `avatarCount` counts usable avatars.
 */
export function missingCatalogParts(input: {
  readonly needsPresenter: boolean;
  readonly avatarCount: number;
  readonly voiceCount: number;
  readonly backgroundId: string;
}): string[] {
  const missing: string[] = [];
  if (input.needsPresenter && input.avatarCount === 0) missing.push("an AI presenter");
  if (input.voiceCount === 0) missing.push("a narration voice");
  if (!input.backgroundId) missing.push("background footage");
  return missing;
}

// ---------------------------------------------------------------------------
// Job requests
// ---------------------------------------------------------------------------

export interface JobRequestInput {
  readonly subject: string;
  /** Manual script (link mode). Empty lets the pipeline write it (topic mode). */
  readonly script?: string;
  readonly layout: Layout;
  readonly avatarId: string;
  readonly voiceId: string;
  readonly backgroundId: string;
  readonly language: Language;
  readonly variants?: number;
  /** Opening-hook angle; with `variants > 1` the API rotates from this one. */
  readonly hookStyle?: HookStyleId;
}

/** Faceless (avatar-less) layouts render narration over footage only. */
export function isFacelessLayout(layout: Layout): boolean {
  return layout === "captions_only";
}

/** Strip a provider prefix so `voice_id` carries the bare provider id. */
export function bareVoiceId(voiceId: string): string {
  const trimmed = voiceId.trim();
  return trimmed.startsWith("elevenlabs:") ? trimmed.slice("elevenlabs:".length) : trimmed;
}

/**
 * Build a `POST /jobs` body with the same field set the reel wizard sends: no
 * screen recording, so `background_id` supplies the footage the presenter sits
 * over.
 */
export function buildJobRequest(input: JobRequestInput): JobCreateRequest {
  const voice = bareVoiceId(input.voiceId);
  const script = (input.script ?? "").trim();
  const variants = Math.max(1, Math.min(VARIANT_COUNT, Math.floor(input.variants ?? 1)));
  // A faceless reel has no presenter: the API then narrates with TTS over
  // `background_id` instead of rendering an avatar.
  const faceless = isFacelessLayout(input.layout);
  const avatarId = faceless ? "" : input.avatarId;
  const base = {
    video_subject: clamp(input.subject, MAX_SUBJECT_LENGTH),
    voice_name: `elevenlabs:${voice}`,
    avatar_id: avatarId,
    avatar_provider: "heygen" as const,
    caption_style: DEFAULT_CAPTION_STYLE,
    layout: input.layout,
    aspect: "9:16" as const,
    language: input.language,
    target_duration_s: TARGET_DURATION_S,
    platforms: [],
    screen_recording_key: "",
    background_id: input.backgroundId,
  };
  // `hook_style` is a newer ReelForge param than the shared request contract.
  const params: JobCreateRequest["params"] & { hook_style?: HookStyleId } = {
    ...base,
    ...(script ? { video_script: script } : {}),
    ...(input.hookStyle ? { hook_style: input.hookStyle } : {}),
  };
  return {
    params,
    ...(avatarId ? { avatar_id: avatarId } : {}),
    voice_id: voice,
    caption_style: DEFAULT_CAPTION_STYLE,
    variants,
  };
}

export interface RunVariant {
  readonly jobId: string;
  readonly angle?: HookStyleId;
}

/** The per-variant hook angles the API assigned to a topic batch. */
export function topicRunVariants(result: {
  readonly job_id: string;
  readonly job_ids?: readonly string[];
  readonly hook_styles?: readonly unknown[];
}): RunVariant[] {
  const ids = result.job_ids?.length ? result.job_ids : [result.job_id];
  return ids.map((jobId, index) => {
    const style = result.hook_styles?.[index];
    return isHookStyle(style) ? { jobId, angle: style } : { jobId };
  });
}

export interface RunRegistrationBody {
  readonly variants: readonly { job_id: string; hook_style: string }[];
}

/**
 * The `POST /experiments/runs` body for a link run, or `null` when fewer than
 * two variants started (one reel is not an experiment).
 */
export function buildRunRegistration(
  variants: readonly RunVariant[],
): RunRegistrationBody | null {
  if (variants.length < 2) return null;
  return {
    variants: variants.slice(0, VARIANT_COUNT).map((variant) => ({
      job_id: variant.jobId,
      hook_style: variant.angle ?? "",
    })),
  };
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/**
 * A creator-facing message for a failed create call. `status` is the HTTP
 * status (0 for a network failure, undefined for a non-HTTP error).
 */
export function describeCreateError(status: number | undefined, message: string): string {
  if (status === 402) {
    return `You don't have enough credits for three reels. Each reel uses ${CREDITS_PER_REEL} credit.`;
  }
  if (status === 429) {
    return "You've started a lot of renders in the last hour. Wait a few minutes and try again.";
  }
  if (status === 422 || status === 400) {
    return message || "That input couldn't be used. Check it and try again.";
  }
  if (status === 503) {
    return "Rendering is temporarily unavailable. Please try again in a few minutes.";
  }
  if (status === 0) {
    return "You appear to be offline. Check your connection and try again.";
  }
  return message || "Something went wrong. Please try again.";
}

// ---------------------------------------------------------------------------
// Results route + progress
// ---------------------------------------------------------------------------

/** Parse `jobs=a,b,c` into at most three safe, unique job ids. */
export function parseJobIds(raw: string | readonly string[] | undefined | null): string[] {
  const joined = Array.isArray(raw) ? raw.join(",") : ((raw as string | null | undefined) ?? "");
  const ids: string[] = [];
  for (const part of joined.split(",")) {
    const id = part.trim();
    if (JOB_ID_PATTERN.test(id) && !ids.includes(id)) ids.push(id);
    if (ids.length === VARIANT_COUNT) break;
  }
  return ids;
}

/** The in-app results route for a run. */
export function resultsHref(jobIds: readonly string[]): string {
  return `/create/results?jobs=${jobIds.map(encodeURIComponent).join(",")}`;
}

export type VariantPhase = "queued" | "rendering" | "ready" | "failed";

export function variantPhase(job: Pick<Job, "state" | "progress"> | undefined): VariantPhase {
  if (!job) return "queued";
  if (job.state === JobState.Complete) return "ready";
  if (job.state === JobState.Failed) return "failed";
  return (job.progress ?? 0) > 0 ? "rendering" : "queued";
}

const STAGE_LABELS: Record<JobStage, string> = {
  script: "Writing the script",
  tts: "Recording the voiceover",
  avatar: "Rendering the presenter",
  captions: "Timing the captions",
  compose: "Composing the video",
  upload: "Finishing up",
};

const STAGE_ORDER: readonly JobStage[] = [
  "script",
  "tts",
  "avatar",
  "captions",
  "compose",
  "upload",
];

/** Human label for what a variant is doing right now. */
export function currentStageLabel(
  job: Pick<Job, "state" | "stages" | "progress"> | undefined,
): string {
  const phase = variantPhase(job);
  if (phase === "ready") return "Ready";
  if (phase === "failed") return "Failed";
  const stages = job?.stages ?? {};
  const running = STAGE_ORDER.find((stage) => stages[stage] === "running");
  if (running) return STAGE_LABELS[running];
  const next = STAGE_ORDER.find((stage) => stages[stage] !== "complete");
  if (phase === "rendering" && next) return STAGE_LABELS[next];
  return "Waiting for a render slot";
}

/** 0..100 progress, clamped. */
export function variantProgress(job: Pick<Job, "state" | "progress"> | undefined): number {
  if (!job) return 0;
  if (job.state === JobState.Complete) return 100;
  const value = Number(job.progress ?? 0);
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

/** mm:ss for the elapsed-time readout. */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export interface RunCost {
  /** Credits held or spent: every variant that did not fail. */
  readonly charged: number;
  /** Credits returned automatically for failed variants. */
  readonly refunded: number;
  /** Credits still held by renders that have not finished yet. */
  readonly pending: number;
}

/**
 * What a run actually cost, from each variant's phase: finished reels are
 * charged, failed ones were refunded, and in-flight ones are held until they
 * finish (and refunded if they fail).
 */
export function runCost(phases: readonly VariantPhase[]): RunCost {
  let charged = 0;
  let refunded = 0;
  let pending = 0;
  for (const phase of phases) {
    if (phase === "failed") refunded += CREDITS_PER_REEL;
    else charged += CREDITS_PER_REEL;
    if (phase === "queued" || phase === "rendering") pending += CREDITS_PER_REEL;
  }
  return { charged, refunded, pending };
}

/** One-line summary of `runCost` for the results header. */
export function describeRunCost(cost: RunCost): string {
  const credits = (n: number) => `${n} credit${n === 1 ? "" : "s"}`;
  const parts = [`${credits(cost.charged)} charged`];
  if (cost.pending > 0) {
    parts.push(`${credits(cost.pending)} of that still rendering and refunded if it fails`);
  }
  if (cost.refunded > 0) parts.push(`${credits(cost.refunded)} refunded for failed renders`);
  return `${parts.join("; ")}.`;
}
