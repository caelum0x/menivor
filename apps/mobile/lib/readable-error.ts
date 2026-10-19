/**
 * Readable copy for errors thrown by the shared API client. The mobile port of
 * the web's `readableApiError` (apps/web/src/shared/launch-gate/gate.ts):
 * launch-gate refusals become an honest reason, transport and server failures
 * become short actionable sentences, and any other message loses its request-id
 * prefix and correlation suffix. Never returns an empty string.
 *
 * Pure: no React Native imports, so it runs under the node vitest configs.
 */

const REQUEST_ID_PREFIX = /^[0-9a-f]{32}:\s*/i;
const CORRELATION_SUFFIX = /\s*\(correlation [^)]*\)\s*$/i;
const LAUNCH_PHASE_TEXT = /not enabled for this launch phase/i;

const PUBLISHING_CLOSED_CODE = "publishing_closed";
const CHECKOUT_CLOSED_CODE = "checkout_closed";

const CLOSED_REASON = {
  publishing:
    "Publishing is not open yet during the private beta. Nothing was posted.",
  checkout:
    "Checkout is not open yet during the private beta. Nothing was charged.",
} as const;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

/** Strip the request-id prefix and correlation suffix from an API message. */
export function cleanApiMessage(message: string): string {
  const text = message
    .replace(CORRELATION_SUFFIX, "")
    .replace(REQUEST_ID_PREFIX, "")
    .trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

export function readableApiError(err: unknown, fallback: string): string {
  const e = asRecord(err) ?? {};
  const status = typeof e.status === "number" ? e.status : null;
  const rawMessage = typeof e.message === "string" ? e.message : "";
  const data = asRecord(asRecord(e.detail)?.data);
  const code = typeof data?.code === "string" ? data.code : "";
  const serverReason =
    typeof data?.reason === "string" ? data.reason.trim() : "";

  if (code === PUBLISHING_CLOSED_CODE || code === CHECKOUT_CLOSED_CODE) {
    return (
      serverReason ||
      (code === CHECKOUT_CLOSED_CODE
        ? CLOSED_REASON.checkout
        : CLOSED_REASON.publishing)
    );
  }
  if (LAUNCH_PHASE_TEXT.test(rawMessage)) {
    return /checkout/i.test(rawMessage)
      ? CLOSED_REASON.checkout
      : CLOSED_REASON.publishing;
  }
  if (status === 0) {
    return "Could not reach Menivor. Check your connection and try again.";
  }
  if (status === 401) return "Your session has expired. Sign in again to continue.";
  if (status === 429) {
    return "Too many requests in a short time. Wait a minute and try again.";
  }
  if (status !== null && status >= 500) {
    return "Something went wrong on our side. Nothing was posted or charged; try again in a minute.";
  }
  return cleanApiMessage(rawMessage) || fallback;
}
