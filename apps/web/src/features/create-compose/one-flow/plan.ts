/**
 * One-flow create: the pure planning layer behind the default `/create` page.
 *
 * A new user types a topic OR pastes a product/page link and gets three reel
 * variants with different opening hooks. Everything here is pure (no network,
 * no React) so the request shapes are unit-tested; the component layer only
 * wires these builders to the existing `POST /ingest/url` + `POST /jobs` paths.
 *
 * - Topic in: ONE `POST /jobs` with `variants: 3`. The backend fans it out
 *   into three jobs under one batch and gives each variant its own opening
 *   hook angle (`hook_style`: POV, question, what-nobody-tells-you), so the
 *   three reels are guaranteed to open differently. The batch is registered
 *   as an experiment server-side.
 * - Link in: `POST /ingest/url` extracts the page (title, description,
 *   features). We then write three scripts that share the same body (the
 *   page's real content) and differ ONLY in the opening hook, one
 *   `POST /jobs` each, then `POST /experiments/runs` links them into one
 *   1-body/N-hooks experiment so the remake-winner loop tracks the run.
 *
 * Every preset except the faceless story renders an AI presenter. The
 * faceless story is `captions_only` with a TTS voice and no upload: the
 * pipeline narrates the script over the curated background footage.
 */

import type {
  Job,
  JobCreateRequest,
  JobStage,
  Language,
  Layout,
} from "@/lib/types";
import { JobState } from "@/lib/types";
import { REEL_STYLES, type StyleHookId, type StyleId } from "@/lib/styles/catalog";

/** Three variants per run: the backend's `MAX_REEL_JOB_VARIANTS`. */
export const VARIANT_COUNT = 3;
/** Reel length requested from the pipeline (seconds). */
export const TARGET_DURATION_S = 30;
/** Default karaoke caption style (the pipeline default). */
export const DEFAULT_CAPTION_STYLE = "karaoke_yellow";

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
export function parseSource(raw: string): ParsedSource | null {
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

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

export type ClassicPresetId = "talking" | "product" | "story" | "faceless";
/** A classic format or a one-click style (`lib/styles/catalog`). */
export type PresetId = ClassicPresetId | StyleId;

export interface CreatePreset {
  readonly id: PresetId;
  readonly title: string;
  readonly blurb: string;
  readonly layout: Layout;
  /** Curated background clip preferred for this preset, when available. */
  readonly preferredBackground: string;
  /** False for the faceless story: narration only, no AI presenter. */
  readonly needsPresenter: boolean;
  /** The API style id (`params.style`) for one-click styles. */
  readonly style?: StyleId;
  /** The style's opening-hook formats (link runs write one per variant). */
  readonly hookFamily?: readonly StyleHookId[];
  /** Story styles: the API writes the whole script (link runs too). */
  readonly scriptMode?: "page" | "story";
}

export const CLASSIC_PRESETS: readonly CreatePreset[] = [
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

/** One-click styles as create presets (the API applies the style itself). */
export const STYLE_PRESETS: readonly CreatePreset[] = REEL_STYLES.map(
  (style): CreatePreset => ({
    id: style.id,
    title: style.label,
    blurb: style.blurb,
    layout: style.layout,
    preferredBackground: style.backgroundId,
    needsPresenter: style.needsPresenter,
    style: style.id,
    hookFamily: style.hookFamily,
    scriptMode: style.scriptMode,
  }),
);

export const CREATE_PRESETS: readonly CreatePreset[] = [...STYLE_PRESETS, ...CLASSIC_PRESETS];

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
export type HookStyleId = StyleHookId;
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
  met_me_at: "Met-me-at hook",
  nobody_me: "Nobody / me hook",
  wish_i_knew: "Wish-I-knew hook",
  before_after: "Before / after hook",
  tell_me_without: "Tell-me-without hook",
  day_in_life: "Day-in-the-life hook",
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
  readonly angle: HookStyleId;
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

export interface WrittenHook {
  readonly hook_style: string;
  readonly hook: string;
}

/**
 * Scripts for a style run: the SAME page body under each hook the API wrote
 * in the style's formats (`POST /styles/hooks`). Hooks with an unknown format
 * or empty text are skipped; at most three variants.
 */
export function planStyleVariants(
  content: PageContent,
  language: Language,
  hooks: readonly WrittenHook[],
): LinkVariantPlan[] {
  const body = buildLinkBody(content, language);
  const plans: LinkVariantPlan[] = [];
  for (const item of hooks) {
    const hook = String(item?.hook ?? "").replace(/\s+/g, " ").trim().slice(0, 200);
    if (!hook || !isHookStyle(item?.hook_style)) continue;
    plans.push({ angle: item.hook_style, hook, script: [hook, ...body].join("\n\n") });
    if (plans.length === VARIANT_COUNT) break;
  }
  return plans;
}

/** The generation subject for a story run from a pasted page. */
export function storySubject(content: PageContent, fallback: string): string {
  const title = (content.title || fallback).replace(/\s+/g, " ").trim();
  const description = (content.description ?? "").replace(/\s+/g, " ").trim();
  return clamp(description ? `${title}: ${description}` : title, MAX_SUBJECT_LENGTH);
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
  /** One-click style id (`params.style`); the API applies its recipe. */
  readonly style?: StyleId;
  /** The pasted page (link runs): the style uses its preview image. */
  readonly sourceUrl?: string;
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
 * Build a `POST /jobs` body with the same field set the reel wizard sends:
 * no screen recording, so `background_id` supplies the footage the presenter
 * sits over.
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
  // `hook_style`, `style` and `source_url` are newer ReelForge params than the
  // shared request contract.
  const params: JobCreateRequest["params"] & {
    hook_style?: HookStyleId;
    style?: StyleId;
    source_url?: string;
  } = {
    ...base,
    ...(script ? { video_script: script } : {}),
    ...(input.hookStyle ? { hook_style: input.hookStyle } : {}),
    ...(input.style ? { style: input.style } : {}),
    ...(input.sourceUrl ? { source_url: input.sourceUrl.slice(0, 2048) } : {}),
  };
  return {
    params,
    ...(avatarId ? { avatar_id: avatarId } : {}),
    voice_id: voice,
    caption_style: DEFAULT_CAPTION_STYLE,
    variants,
  };
}

/** The per-variant hook angles the API assigned to a topic batch. */
export function topicRunVariants(result: {
  readonly job_id: string;
  readonly job_ids?: readonly string[];
  readonly hook_styles?: readonly unknown[];
}): { jobId: string; angle?: HookStyleId }[] {
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
  variants: readonly { jobId: string; angle?: HookStyleId }[],
): RunRegistrationBody | null {
  if (variants.length < 2) return null;
  return {
    variants: variants.slice(0, VARIANT_COUNT).map((variant) => ({
      job_id: variant.jobId,
      hook_style: variant.angle ?? "",
    })),
  };
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

// ---------------------------------------------------------------------------
// Results URL + progress
// ---------------------------------------------------------------------------

/** Parse `?jobs=a,b,c` into at most three safe, unique job ids. */
export function parseJobIds(raw: string | string[] | undefined | null): string[] {
  const joined = Array.isArray(raw) ? raw.join(",") : (raw ?? "");
  const ids: string[] = [];
  for (const part of joined.split(",")) {
    const id = part.trim();
    if (JOB_ID_PATTERN.test(id) && !ids.includes(id)) ids.push(id);
    if (ids.length === VARIANT_COUNT) break;
  }
  return ids;
}

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

/** "about 4 min" from measured seconds; "" when there is no estimate. */
export function formatEta(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "";
  if (seconds < 60) return "less than a minute";
  const minutes = Math.round(seconds / 60);
  return minutes === 1 ? "about 1 min" : `about ${minutes} min`;
}

/** Queue line for a variant that has not started: position, then measured ETA. */
export function queueLabel(queue: Job["queue"] | undefined): string {
  if (!queue) return "Starting soon";
  const eta = formatEta(queue.eta_s);
  const ahead = Math.max(0, Math.floor(Number(queue.ahead) || 0));
  const position = ahead === 0 ? "Next in line" : ahead === 1 ? "1 reel ahead of yours" : `${ahead} reels ahead of yours`;
  return eta ? `${position}. Ready in ${eta}.` : `${position}.`;
}

/** Human label for what a variant is doing right now. */
export function currentStageLabel(
  job: Pick<Job, "state" | "stages" | "progress" | "queue"> | undefined,
): string {
  const phase = variantPhase(job);
  if (phase === "ready") return "Ready";
  if (phase === "failed") return "Failed";
  const stages = job?.stages ?? {};
  const running = STAGE_ORDER.find((stage) => stages[stage] === "running");
  if (running) return STAGE_LABELS[running];
  const next = STAGE_ORDER.find((stage) => stages[stage] !== "complete");
  if (phase === "rendering" && next) return STAGE_LABELS[next];
  return queueLabel(job?.queue);
}

/** Measured "ready in" hint for a variant that is already rendering; "" if unknown. */
export function renderingEtaLabel(job: Pick<Job, "state" | "progress" | "queue"> | undefined): string {
  if (variantPhase(job) !== "rendering") return "";
  const eta = formatEta(job?.queue?.eta_s);
  return eta ? `Ready in ${eta}` : "";
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
