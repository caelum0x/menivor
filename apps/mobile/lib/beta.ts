/**
 * Private-beta client: reads the launch phase + keyless formats from
 * GET /launch/status and posts access requests to POST /beta/request.
 *
 * Both endpoints are public. Payloads are parsed defensively (network data),
 * and `submitBetaRequest` never throws: every failure maps to a user message.
 */

import { ApiError, apiRequest, type RequestOptions } from "@/src/shared/api";

export type LaunchPhase = "public" | "private_beta";

export interface LaunchFormat {
  id: string;
  label: string;
  available: boolean;
  paidKeys: string[];
  notes: string;
}

export interface BetaLaunchStatus {
  phase: LaunchPhase;
  /** Keyless formats that render today (no paid provider key needed). */
  availableFormats: LaunchFormat[];
  /** Server-owned: approved emails can still create an account while signup is closed. */
  approvedEmailsCanSignIn: boolean;
}

/** The formats a beta user can make with zero paid keys. */
export const FREE_FORMAT_IDS: readonly string[] = [
  "captions_only_byov",
  "faceless_tts_free_voice",
];

/** Plain-language description per keyless format. */
export const FORMAT_DETAIL: Readonly<Record<string, string>> = {
  captions_only_byov:
    "Upload a video you recorded. Its own audio is transcribed and word-by-word captions are burned in. No AI provider is called.",
  faceless_tts_free_voice:
    "Type your script, pick a free neural voice and a background loop. You get a narrated, captioned 9:16 reel.",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function parseFormat(raw: unknown): LaunchFormat | null {
  const rec = asRecord(raw);
  if (!rec || typeof rec.id !== "string" || !rec.id) return null;
  return {
    id: rec.id,
    label: typeof rec.label === "string" && rec.label ? rec.label : rec.id,
    available: rec.available === true,
    paidKeys: Array.isArray(rec.paid_keys)
      ? rec.paid_keys.filter((k): k is string => typeof k === "string")
      : [],
    notes: typeof rec.notes === "string" ? rec.notes : "",
  };
}

export function parseBetaLaunchStatus(raw: unknown): BetaLaunchStatus {
  const rec = asRecord(raw) ?? {};
  const phase: LaunchPhase =
    rec.phase === "public" || rec.phase === "private_beta"
      ? rec.phase
      : rec.public_access === true
        ? "public"
        : "private_beta";
  const readiness = asRecord(rec.readiness);
  const formats = (Array.isArray(readiness?.free_paths) ? readiness.free_paths : [])
    .map(parseFormat)
    .filter((f): f is LaunchFormat => f !== null);
  const beta = asRecord(rec.beta);
  return {
    phase,
    availableFormats: formats.filter(
      (f) => f.available && f.paidKeys.length === 0 && FREE_FORMAT_IDS.includes(f.id),
    ),
    approvedEmailsCanSignIn: beta?.signup_for_approved_emails === true,
  };
}

export async function getBetaLaunchStatus(options?: RequestOptions): Promise<BetaLaunchStatus> {
  const raw = await apiRequest<unknown>("/launch/status", { options });
  return parseBetaLaunchStatus(raw);
}

export const BETA_EMAIL_MAX = 254;
export const BETA_USE_CASE_MAX = 2000;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export type BetaFieldCheck =
  | { ok: true; email: string; useCase: string }
  | { ok: false; error: string };

export function checkBetaFields(email: string, useCase: string): BetaFieldCheck {
  const normalized = email.trim().toLowerCase();
  if (!normalized) return { ok: false, error: "Enter your email address." };
  if (normalized.length > BETA_EMAIL_MAX || !EMAIL_PATTERN.test(normalized)) {
    return { ok: false, error: "Enter a valid email address." };
  }
  const trimmed = useCase.trim();
  if (!trimmed) return { ok: false, error: "Tell us briefly what you want to make." };
  if (trimmed.length > BETA_USE_CASE_MAX) {
    return { ok: false, error: `Keep the use case under ${BETA_USE_CASE_MAX} characters.` };
  }
  return { ok: true, email: normalized, useCase: trimmed };
}

export type BetaRequestOutcome =
  | { status: "received"; message: string }
  | { status: "error"; message: string };

const DEFAULT_RECEIVED_MESSAGE =
  "Thanks, your request is in. We review requests by hand and will email you if your access is approved.";

export async function submitBetaRequest(
  email: string,
  useCase: string,
  source = "mobile",
): Promise<BetaRequestOutcome> {
  try {
    const data = await apiRequest<unknown>("/beta/request", {
      method: "POST",
      body: { email, use_case: useCase, source: source.slice(0, 40) },
    });
    const rec = asRecord(data);
    return {
      status: "received",
      message:
        typeof rec?.message === "string" && rec.message ? rec.message : DEFAULT_RECEIVED_MESSAGE,
    };
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 429) {
        return { status: "error", message: "Too many requests from here. Please try again in an hour." };
      }
      if (err.status === 0 || err.status === 503) {
        return { status: "error", message: "The beta list is not reachable right now. Please try again later." };
      }
      if (err.status >= 400 && err.status < 500) {
        return { status: "error", message: "Check your email address and try again." };
      }
    }
    return { status: "error", message: "Something went wrong. Please try again." };
  }
}
