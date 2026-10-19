/** Pure state and copy for the "Very ___ Time" flow. No React, no network. */

import type {
  VeryTimeBrand,
  VeryTimeDelivery,
  VeryTimeDuration,
  VeryTimeEngine,
  VeryTimeInput,
  VeryTimeLook,
  VeryTimePayoff,
  VeryTimePlan,
  VeryTimePrice,
  VeryTimeSound,
  VeryTimeVoice,
} from "./api";

export const PLACE_MAX = 24;
export const RITUAL_MAX = 120;
export const GARMENT_MAX = 200;
export const CHEST_MAX = 40;
export const REPLY_MAX = 140;
export const LINE_MAX = 140;
export const CTA_MAX = 60;
export const LOGO_FILE_MAX_BYTES = 5 * 1024 * 1024;
export const DEFAULT_DURATION: VeryTimeDuration = 15;
export const CTA_PLACEHOLDER = "Get yours at yourshop.com";
export const GARMENT_FILE_MAX_BYTES = 10 * 1024 * 1024;
export const GARMENT_FILE_TYPES: readonly string[] = ["image/png", "image/jpeg", "image/webp"];

/** Letters in any script, spaces and hyphens. */
const PLACE_PATTERN = /^[\p{L}\p{M}\s-]+$/u;

/** Same default as the server preset (very-time@v1 brand.garment); never 480's own garment. */
export const DEFAULT_GARMENT =
  "an oversized oxblood (#4A0E17) button-up shirt with ivory serif embroidery on the chest";
export const RITUAL_PLACEHOLDER = "tea poured into a tulip glass at midnight";

export interface LookOption {
  readonly id: VeryTimeLook;
  readonly title: string;
  readonly description: string;
}

export const LOOKS: readonly LookOption[] = [
  {
    id: "console",
    title: "Console cutscene",
    description: "An early-2000s game scene with soft low-poly faces and a yellow subtitle.",
  },
  {
    id: "flash",
    title: "Flash lookbook",
    description: "A deadpan fashion shoot with hard on-camera flash on grey paper.",
  },
  {
    id: "atelier",
    title: "Atelier film",
    description: "Warm, grainy film frames inside a quiet workshop.",
  },
];

export interface DurationOption {
  readonly seconds: VeryTimeDuration;
  readonly title: string;
  readonly description: string;
}

export const DURATIONS: readonly DurationOption[] = [
  { seconds: 10, title: "10 seconds", description: "Quick: a short build-up, then the line." },
  { seconds: 15, title: "15 seconds", description: "The classic length for this format." },
  { seconds: 30, title: "30 seconds", description: "Slower, with more of the place and the ritual." },
];

/** The built-in Oxhan Atelier brand, as summarised on the brand step. The server holds the real values. */
export const OXHAN_SUMMARY = {
  name: "Oxhan Atelier",
  garment: "Oxblood Oxhan Atelier shirt with \"very turkish time\" on the chest",
  host: "The Oxhan host, deadpan",
  line: "You met me at a very Turkish time in my life.",
  cta: "Get yours at oxhanatelier.com",
} as const;

export interface DeliveryOption {
  readonly id: VeryTimeDelivery;
  readonly title: string;
}

export const DELIVERIES: readonly DeliveryOption[] = [
  { id: "deadpan", title: "Deadpan" },
  { id: "quiet", title: "Quiet" },
  { id: "tired", title: "Tired" },
  { id: "warm", title: "Warm" },
];

export interface PayoffOption {
  readonly id: VeryTimePayoff;
  readonly title: string;
  readonly note: string;
}

export const PAYOFFS: readonly PayoffOption[] = [
  { id: "native", title: "The video says the line", note: "The host speaks in the last shot." },
  { id: "lipsync", title: "Match the mouth to the voice", note: "Your chosen take, with the mouth moving to it." },
  { id: "voiceover", title: "Voice-over only", note: "The take plays over the last shot." },
];

/** What the voice step holds. A take is only valid for the settings it was made with. */
export interface VoiceChoice {
  readonly engine: VeryTimeEngine;
  readonly delivery: VeryTimeDelivery;
  readonly reply: string;
  readonly takeKey: string | null;
}

export const DEFAULT_VOICE: VoiceChoice = { engine: "free", delivery: "deadpan", reply: "", takeKey: null };

export interface SoundChoice {
  readonly sfx: boolean;
  readonly roomTone: boolean;
  readonly payoff: VeryTimePayoff;
}

export const DEFAULT_SOUND: SoundChoice = { sfx: false, roomTone: false, payoff: "native" };

export interface VeryTimeForm {
  readonly place: string;
  readonly ritual: string;
  readonly look: VeryTimeLook | null;
  /** null means the brand step was skipped. */
  readonly brand: VeryTimeBrand | null;
  readonly voice?: VoiceChoice;
  readonly sound?: SoundChoice;
  readonly duration?: VeryTimeDuration;
  /** The closing line (custom brand only); sent only when it differs from the default line. */
  readonly line?: string;
}

export const EMPTY_FORM: VeryTimeForm = { place: "", ritual: "", look: null, brand: null };

interface FileLike {
  readonly type: string;
  readonly size: number;
}

function imageFileProblem(file: FileLike, maxBytes: number, what: string): string {
  if (!GARMENT_FILE_TYPES.includes(file.type)) return `Use a PNG, JPEG or WebP ${what}.`;
  if (file.size > maxBytes) return `Keep the ${what} under ${Math.round(maxBytes / (1024 * 1024))} MB.`;
  if (file.size <= 0) return "This file is empty.";
  return "";
}

/** Plain sentence describing what is wrong with a garment photo, or "". */
export function garmentFileProblem(file: FileLike): string {
  return imageFileProblem(file, GARMENT_FILE_MAX_BYTES, "photo");
}

/** Plain sentence describing what is wrong with a logo file, or "". */
export function logoFileProblem(file: FileLike): string {
  return imageFileProblem(file, LOGO_FILE_MAX_BYTES, "logo");
}

/** "Ends with: Get yours at ...", or "" when the end card has no call to action. */
export function endCardLabel(plan: VeryTimePlan | null): string {
  const cta = plan?.end_card?.cta?.trim() ?? "";
  return cta ? `Ends with: ${cta}` : "";
}

/** Changing engine, delivery or the reply makes any made takes stale. */
export function changeVoice(current: VoiceChoice, change: Partial<Omit<VoiceChoice, "takeKey">>): VoiceChoice {
  const next = { ...current, ...change };
  const stale = next.engine !== current.engine || next.delivery !== current.delivery || next.reply !== current.reply;
  return stale ? { ...next, takeKey: null } : next;
}

/** The voice part of the request, or undefined when everything is the default. */
export function voiceBody(voice: VoiceChoice | undefined): VeryTimeVoice | undefined {
  if (!voice) return undefined;
  const reply = voice.reply.trim().replace(/\s+/g, " ");
  const isDefault = voice.engine === "free" && voice.delivery === "deadpan" && !reply && !voice.takeKey;
  if (isDefault) return undefined;
  return {
    engine: voice.engine,
    delivery: voice.delivery,
    ...(voice.takeKey ? { take_key: voice.takeKey } : {}),
    ...(reply ? { reply_line: reply.slice(0, REPLY_MAX) } : {}),
  };
}

/** The sound part of the request, or undefined when both are off. */
export function soundBody(sound: SoundChoice | undefined): VeryTimeSound | undefined {
  if (!sound || (!sound.sfx && !sound.roomTone)) return undefined;
  return { sfx: sound.sfx, room_tone: sound.roomTone };
}

export function takesCount(engine: VeryTimeEngine): 2 | 3 {
  return engine === "eleven_v3" ? 3 : 2;
}

/** "Includes premium voice (+1) and sound effects (+1)", or "" when there are no extras. */
export function extrasLabel(plan: VeryTimePlan): string {
  const extras = plan.quote.extras;
  if (!extras) return "";
  const parts: string[] = [];
  if (extras.voice_credits > 0) parts.push(`premium voice (+${extras.voice_credits})`);
  if (extras.sfx_credits > 0) parts.push(`sound effects (+${extras.sfx_credits})`);
  return parts.length ? `Includes ${parts.join(" and ")}.` : "";
}

export function cleanPlace(place: string): string {
  return place.trim().replace(/\s+/g, " ");
}

/** The spoken line, with a blank while the word is empty. */
export function previewLine(place: string): string {
  const word = cleanPlace(place);
  return `You met me at a very ${word || "___"} time in my life.`;
}

export function defaultChestText(place: string): string {
  const word = cleanPlace(place);
  return (word ? `very ${word} time` : "very good time").slice(0, CHEST_MAX);
}

/** Plain sentence describing what is wrong with the place word, or "". */
export function placeProblem(place: string): string {
  const word = cleanPlace(place);
  if (!word) return "";
  if (word.length > PLACE_MAX) return `Keep it to ${PLACE_MAX} characters.`;
  if (!PLACE_PATTERN.test(word)) return "Use letters, spaces or a hyphen only.";
  return "";
}

export function placeReady(form: VeryTimeForm): boolean {
  return cleanPlace(form.place) !== "" && placeProblem(form.place) === "" && form.ritual.trim() !== "";
}

function trimmedBrand(brand: VeryTimeBrand | null): VeryTimeBrand | undefined {
  if (!brand) return undefined;
  if (brand.preset === "oxhan") return { preset: "oxhan" };
  const garment = brand.garment?.trim() ?? "";
  const chest = brand.chest_text?.trim() ?? "";
  const ref = brand.garment_ref?.trim() ?? "";
  const cta = brand.cta?.trim().replace(/\s+/g, " ").slice(0, CTA_MAX) ?? "";
  const logo = brand.logo_ref?.trim() ?? "";
  if (!garment && !chest && !ref && !cta && !logo) return undefined;
  return {
    ...(garment ? { garment } : {}),
    ...(chest ? { chest_text: chest } : {}),
    ...(ref ? { garment_ref: ref } : {}),
    ...(cta ? { cta } : {}),
    ...(logo ? { logo_ref: logo } : {}),
  };
}

/** The custom closing line, or undefined when it is empty, the default, or the Oxhan preset is chosen. */
function closingLine(form: VeryTimeForm): string | undefined {
  if (!form.brand || form.brand.preset === "oxhan") return undefined;
  const line = (form.line ?? "").trim().replace(/\s+/g, " ").slice(0, LINE_MAX);
  if (!line || line === previewLine(form.place)) return undefined;
  return line;
}

/** The request body both plan and start share. */
export function buildInput(form: VeryTimeForm): VeryTimeInput {
  const brand = trimmedBrand(form.brand);
  const voice = voiceBody(form.voice);
  const sound = soundBody(form.sound);
  const payoff = form.sound?.payoff;
  const line = closingLine(form);
  const duration = form.duration ?? DEFAULT_DURATION;
  return {
    place_word: cleanPlace(form.place),
    ritual: form.ritual.trim(),
    look: form.look ?? "console",
    ...(brand ? { brand } : {}),
    ...(voice ? { voice } : {}),
    ...(sound ? { sound } : {}),
    ...(payoff && payoff !== "native" ? { payoff } : {}),
    ...(line ? { line } : {}),
    ...(duration !== DEFAULT_DURATION ? { duration_s: duration } : {}),
  };
}

export function priceLabel(price: VeryTimePrice): string {
  const standard = `${price.standard_credits} credit${price.standard_credits === 1 ? "" : "s"}`;
  return price.ai_video_credits > 0 ? `${standard} + ${price.ai_video_credits} AI-video credits` : standard;
}

/** Which blocked terms appear in a piece of text (case-insensitive). */
export function termsIn(text: string, terms: readonly string[]): string[] {
  const lower = text.toLocaleLowerCase();
  return terms.filter((term) => lower.includes(term.toLocaleLowerCase()));
}

export interface TextPart {
  readonly text: string;
  readonly blocked: boolean;
}

/** Split text into parts so blocked terms can be marked in place. */
export function splitByTerms(text: string, terms: readonly string[]): TextPart[] {
  const words = terms.filter((t) => t.trim() !== "");
  if (words.length === 0 || !text) return text ? [{ text, blocked: false }] : [];
  const escaped = words.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const pattern = new RegExp(`(${escaped.join("|")})`, "giu");
  return text
    .split(pattern)
    .filter((part) => part !== "")
    .map((part) => ({ text: part, blocked: words.some((w) => w.toLocaleLowerCase() === part.toLocaleLowerCase()) }));
}
