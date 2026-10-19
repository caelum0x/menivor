/**
 * Launch-gate helpers for publish, schedule and checkout surfaces.
 *
 * `GET /launch/status` reports, for the calling principal, whether direct
 * publishing and checkout are open. During the private beta both are closed
 * for everyone except operator-listed pilot staff. These helpers turn that
 * document into a per-feature `{ open, reason }` and turn raw API errors
 * (which carry a request-id prefix) into copy a person can act on.
 *
 * Everything here is pure so it can be unit-tested without a network.
 */

import { isHumanReadable } from "@/src/shared/errors/friendly";

export type LaunchFeature = "publishing" | "checkout";

export interface FeatureGate {
  /** True when the server will accept this action for the current caller. */
  readonly open: boolean;
  /** Human copy for why the action is unavailable ("" when open). */
  readonly reason: string;
}

export interface LaunchGate {
  readonly phase: "public" | "private_beta";
  /** The caller is on the pilot staff allow-list (sees closed features open). */
  readonly staffOverride: boolean;
  readonly publishing: FeatureGate;
  readonly checkout: FeatureGate;
}

export const PUBLISHING_CLOSED_CODE = "publishing_closed";
export const CHECKOUT_CLOSED_CODE = "checkout_closed";

const CLOSED_COPY: Record<LaunchFeature, Record<LaunchGate["phase"], string>> = {
  publishing: {
    private_beta:
      "Posting to social platforms opens at public launch. Menivor is in private beta, so you can make, preview and download reels, but publishing and scheduling posts are paused.",
    public:
      "Publishing to social platforms is not available yet. You can make, preview and download reels and post them yourself.",
  },
  checkout: {
    private_beta:
      "Purchases open at public launch. Menivor is in private beta, so checkout is paused and you will not be charged.",
    public: "Paid credit packs are not on sale yet. You have not been charged.",
  },
};

/** Copy for a closed feature in a given phase. */
export function closedReason(feature: LaunchFeature, phase: LaunchGate["phase"]): string {
  return CLOSED_COPY[feature][phase];
}

/** Gate used when the status read failed: the server still enforces, so stay usable. */
export const OPEN_GATE: LaunchGate = {
  phase: "public",
  staffOverride: false,
  publishing: { open: true, reason: "" },
  checkout: { open: true, reason: "" },
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Normalize a raw `GET /launch/status` document (defensive: network input). */
export function gateFromStatus(raw: unknown): LaunchGate {
  const rec = asRecord(raw) ?? {};
  const publicAccess = rec.public_access === true;
  const phase: LaunchGate["phase"] =
    rec.phase === "public" || rec.phase === "private_beta"
      ? rec.phase
      : publicAccess
        ? "public"
        : "private_beta";
  const features = asRecord(rec.features) ?? {};
  const feature = (name: LaunchFeature): FeatureGate => {
    // Only an explicit `true` opens a gate; anything else reads as closed.
    const open = features[name] === true;
    return { open, reason: open ? "" : closedReason(name, phase) };
  };
  return {
    phase,
    staffOverride: rec.staff_override === true,
    publishing: feature("publishing"),
    checkout: feature("checkout"),
  };
}

// ---------------------------------------------------------------------------
// Error copy
// ---------------------------------------------------------------------------

/** The API prefixes messages with a 32-hex request id: `"<id>: message"`. */
const REQUEST_ID_PREFIX = /^[0-9a-f]{32}:\s*/i;
const CORRELATION_SUFFIX = /\s*\(correlation [^)]*\)\s*$/i;
const LAUNCH_PHASE_TEXT = /not enabled for this launch phase/i;

interface ErrorLike {
  message?: unknown;
  status?: unknown;
  detail?: unknown;
}

function envelopeData(detail: unknown): Record<string, unknown> | null {
  const envelope = asRecord(detail);
  return envelope ? asRecord(envelope.data) : null;
}

/** Strip the request-id prefix and correlation suffix from an API message. */
export function cleanApiMessage(message: string): string {
  const text = message.replace(CORRELATION_SUFFIX, "").replace(REQUEST_ID_PREFIX, "").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

/**
 * Readable copy for any error thrown by the API client. Launch-gate refusals
 * become the same honest reason the page shows up front; transport and server
 * failures become short, actionable sentences; other messages lose their
 * request-id prefix. Never returns an empty string.
 */
export function readableApiError(err: unknown, fallback: string): string {
  const e = (asRecord(err) ?? {}) as ErrorLike;
  const status = typeof e.status === "number" ? e.status : null;
  const rawMessage = typeof e.message === "string" ? e.message : "";
  const data = envelopeData(e.detail);
  const code = typeof data?.code === "string" ? data.code : "";
  const serverReason = typeof data?.reason === "string" ? data.reason.trim() : "";

  if (code === PUBLISHING_CLOSED_CODE || code === CHECKOUT_CLOSED_CODE) {
    const feature: LaunchFeature = code === CHECKOUT_CLOSED_CODE ? "checkout" : "publishing";
    return serverReason || closedReason(feature, "private_beta");
  }
  if (LAUNCH_PHASE_TEXT.test(rawMessage)) {
    return closedReason(/checkout/i.test(rawMessage) ? "checkout" : "publishing", "private_beta");
  }
  if (status === 0) return "Could not reach Menivor. Check your connection and try again.";
  if (status === 401) return "Your session has expired. Sign in again to continue.";
  if (status === 429) return "Too many requests in a short time. Wait a minute and try again.";
  if (status !== null && status >= 500) {
    return "Something went wrong on our side. Nothing was posted or charged; try again in a minute.";
  }
  const cleaned = cleanApiMessage(rawMessage);
  return cleaned && isHumanReadable(cleaned) ? cleaned : fallback;
}
