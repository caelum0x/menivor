import { OFFER } from "@/lib/offer";

/**
 * Marketing launch posture, derived from the public `GET /launch/status`
 * document. Pure and network-free so it can be unit-tested; the server fetch
 * lives in `./server.ts`.
 *
 * - `waitlist`: the explicit NEXT_PUBLIC_WAITLIST_MODE override, or the safe
 *   fallback when the status cannot be read. Every CTA routes to the waitlist.
 * - `beta`: the API reports a private beta (or public access without open
 *   signup). CTAs route to the request-early-access form.
 * - `public`: public access with signup open. CTAs route to /sign-up.
 */

export type LaunchMode = "waitlist" | "beta" | "public";

export interface LaunchFormatLabel {
  readonly id: string;
  readonly label: string;
}

export interface LaunchPosture {
  readonly mode: LaunchMode;
  readonly signupOpen: boolean;
  readonly checkoutOpen: boolean;
  readonly publishingOpen: boolean;
  /** Formats the API says render on the current tier. */
  readonly availableFormats: readonly LaunchFormatLabel[];
  /** Formats the API says are locked on the current tier. */
  readonly lockedFormats: readonly LaunchFormatLabel[];
}

/** The pre-launch posture: used for the env override and when the API is unreachable. */
export const WAITLIST_POSTURE: LaunchPosture = {
  mode: "waitlist",
  signupOpen: false,
  checkoutOpen: false,
  publishingOpen: false,
  availableFormats: [],
  lockedFormats: [],
};

const MAX_FORMATS = 12;
const MAX_LABEL_LENGTH = 120;

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function parseFormats(value: unknown): readonly LaunchFormatLabel[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const out: LaunchFormatLabel[] = [];
  for (const item of value) {
    const rec = asRecord(item);
    const id = typeof rec?.id === "string" ? rec.id.trim() : "";
    const label = typeof rec?.label === "string" ? rec.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    out.push({ id, label: label.slice(0, MAX_LABEL_LENGTH) });
    if (out.length >= MAX_FORMATS) break;
  }
  return out;
}

/**
 * Normalize a raw status document (the API envelope `{ status, data }` or the
 * bare `data` object). Anything that is not recognisably a status document
 * yields `null` so the caller can fall back to the waitlist posture.
 */
export function parseLaunchPosture(raw: unknown): LaunchPosture | null {
  const outer = asRecord(raw);
  if (!outer) return null;
  const doc = asRecord(outer.data) ?? outer;
  if (typeof doc.public_access !== "boolean" && typeof doc.phase !== "string") return null;

  const features = asRecord(doc.features) ?? {};
  const signupOpen = features.signup === true;
  const publicAccess =
    doc.public_access === true || (doc.public_access === undefined && doc.phase === "public");
  return {
    mode: publicAccess && signupOpen ? "public" : "beta",
    signupOpen,
    checkoutOpen: features.checkout === true,
    publishingOpen: features.publishing === true,
    availableFormats: parseFormats(doc.available_formats),
    lockedFormats: parseFormats(doc.locked_formats),
  };
}

/** Resolve the posture, honouring the build-time waitlist override first. */
export function resolveLaunchPosture(raw: unknown, waitlistOverride: boolean): LaunchPosture {
  if (waitlistOverride) return WAITLIST_POSTURE;
  return parseLaunchPosture(raw) ?? WAITLIST_POSTURE;
}

/** Join labels as readable English: "a", "a and b", "a, b and c". */
export function joinLabels(formats: readonly LaunchFormatLabel[]): string {
  const labels = formats.map((f) => f.label);
  if (labels.length <= 1) return labels.join("");
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

/**
 * The honest "Is Menivor available now?" answer for the current posture.
 * Only states what the status document reports; no credit or reel counts.
 */
export function availabilityAnswer(posture: LaunchPosture): string {
  if (posture.mode === "waitlist") {
    return "Menivor is currently in a closed pilot while render capacity comes online. Join the waitlist to receive an email when a spot opens.";
  }
  if (posture.mode === "beta") {
    return "Menivor is in a private beta. Request early access with your email and what you want to make; approved emails sign in normally.";
  }
  const parts = [
    OFFER.faqFree,
  ];
  if (posture.availableFormats.length > 0) {
    parts.push(`Open now: ${joinLabels(posture.availableFormats)}.`);
  }
  // Locked formats are never listed publicly (claims rule 5: no unlaunched
  // features); they appear here once the API reports them available.
  if (!posture.checkoutOpen) {
    parts.push("Paid credit packs and paid formats are not on sale yet.");
  }
  if (!posture.publishingOpen) {
    parts.push(
      "Publishing directly to social platforms is not available yet; download your reels and post them yourself.",
    );
  }
  return parts.join(" ");
}
