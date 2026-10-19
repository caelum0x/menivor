/**
 * Private-beta client helpers for the marketing surface and /beta.
 *
 * Reads the public, non-sensitive `GET /launch/status` document (phase,
 * readiness, keyless formats) and posts `POST /beta/request`. Both calls are
 * anonymous: no Clerk token, no device key, nothing a visitor has to own.
 * Everything is parsed defensively because the payload comes from the network.
 */

import { ApiError, apiRequest } from "@/src/shared/api";

export type LaunchPhase = "public" | "private_beta";

/** One reel format and whether it renders today with zero paid provider keys. */
export interface LaunchFormat {
  readonly id: string;
  readonly label: string;
  readonly available: boolean;
  readonly paidKeys: readonly string[];
  readonly notes: string;
}

export interface BetaLaunchStatus {
  readonly phase: LaunchPhase;
  /** Formats that need no paid key AND whose runtime deps are present now. */
  readonly availableFormats: readonly LaunchFormat[];
  /** Every format the server reported, including ones that are not ready. */
  readonly formats: readonly LaunchFormat[];
  /** Server-owned: approved emails can create an account while signup is closed. */
  readonly approvedEmailsCanSignIn: boolean;
}

/** Formats a private-beta user can make without any paid key. */
export const FREE_FORMAT_IDS: readonly string[] = [
  "captions_only_byov",
  "faceless_tts_free_voice",
];

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function parseFormat(raw: unknown): LaunchFormat | null {
  const rec = asRecord(raw);
  if (!rec || typeof rec.id !== "string" || !rec.id) return null;
  const paidKeys = Array.isArray(rec.paid_keys)
    ? rec.paid_keys.filter((k): k is string => typeof k === "string")
    : [];
  return {
    id: rec.id,
    label: typeof rec.label === "string" && rec.label ? rec.label : rec.id,
    available: rec.available === true,
    paidKeys,
    notes: typeof rec.notes === "string" ? rec.notes : "",
  };
}

/** Normalize the raw `GET /launch/status` data into what the UI renders. */
export function parseBetaLaunchStatus(raw: unknown): BetaLaunchStatus {
  const rec = asRecord(raw) ?? {};
  const publicAccess = rec.public_access === true;
  const phase: LaunchPhase =
    rec.phase === "public" || rec.phase === "private_beta"
      ? rec.phase
      : publicAccess
        ? "public"
        : "private_beta";
  const readiness = asRecord(rec.readiness);
  const formats = (Array.isArray(readiness?.free_paths) ? readiness.free_paths : [])
    .map(parseFormat)
    .filter((f): f is LaunchFormat => f !== null);
  const availableFormats = formats.filter(
    (f) => f.available && f.paidKeys.length === 0 && FREE_FORMAT_IDS.includes(f.id),
  );
  const beta = asRecord(rec.beta);
  return {
    phase,
    formats,
    availableFormats,
    approvedEmailsCanSignIn: beta?.signup_for_approved_emails === true,
  };
}

export async function fetchBetaLaunchStatus(signal?: AbortSignal): Promise<BetaLaunchStatus> {
  const raw = await apiRequest<unknown>("/launch/status", {
    anonymous: true,
    options: { signal },
  });
  return parseBetaLaunchStatus(raw);
}

export const BETA_EMAIL_MAX = 254;
export const BETA_USE_CASE_MAX = 2000;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export type BetaFieldCheck =
  | { readonly ok: true; readonly email: string; readonly useCase: string }
  | { readonly ok: false; readonly error: string };

/** Mirror of the server's field limits so obvious mistakes never hit the API. */
export function checkBetaFields(email: string, useCase: string): BetaFieldCheck {
  const normalized = email.trim().toLowerCase();
  if (!normalized) return { ok: false, error: "Enter your email address." };
  if (normalized.length > BETA_EMAIL_MAX || !EMAIL_PATTERN.test(normalized)) {
    return { ok: false, error: "Enter a valid email address." };
  }
  const trimmedUseCase = useCase.trim();
  if (!trimmedUseCase) {
    return { ok: false, error: "Tell us briefly what you want to make." };
  }
  if (trimmedUseCase.length > BETA_USE_CASE_MAX) {
    return { ok: false, error: `Keep the use case under ${BETA_USE_CASE_MAX} characters.` };
  }
  return { ok: true, email: normalized, useCase: trimmedUseCase };
}

export type BetaRequestOutcome =
  | { readonly status: "received"; readonly message: string }
  | { readonly status: "rate_limited"; readonly message: string }
  | { readonly status: "unavailable"; readonly message: string }
  | { readonly status: "error"; readonly message: string };

const DEFAULT_RECEIVED_MESSAGE =
  "Thanks, your request is in. We review requests by hand and will email you if your access is approved.";

/** POST /beta/request. Never throws; maps every failure to a user message. */
export async function submitBetaRequest(
  email: string,
  useCase: string,
  source: string,
): Promise<BetaRequestOutcome> {
  try {
    const data = await apiRequest<unknown>("/beta/request", {
      method: "POST",
      anonymous: true,
      body: { email, use_case: useCase, source: source.slice(0, 40) },
    });
    const rec = asRecord(data);
    const message =
      typeof rec?.message === "string" && rec.message ? rec.message : DEFAULT_RECEIVED_MESSAGE;
    return { status: "received", message };
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 429) {
        return {
          status: "rate_limited",
          message: "Too many requests from here. Please try again in an hour.",
        };
      }
      if (err.status === 503 || err.status === 0) {
        return {
          status: "unavailable",
          message: "The beta list is not reachable right now.",
        };
      }
      if (err.status >= 400 && err.status < 500) {
        return { status: "error", message: "Check your email address and try again." };
      }
    }
    return { status: "error", message: "Something went wrong. Please try again." };
  }
}
