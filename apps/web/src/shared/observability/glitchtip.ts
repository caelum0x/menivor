/**
 * Minimal browser error reporting to GlitchTip (errors.ereboslab.com), which
 * speaks the Sentry store protocol. Zero dependencies: uncaught errors and
 * unhandled promise rejections are posted as Sentry events.
 *
 * Privacy: no user id, email, IP, cookies, headers or request bodies are sent.
 * URLs lose their query string and hash (they can carry tokens or checkout
 * ids), and stack/message text is truncated. The DSN is a public browser key
 * baked in at build time via NEXT_PUBLIC_GLITCHTIP_DSN; unset means off.
 */

export interface ParsedDsn {
  readonly storeUrl: string;
}

/** Events per page load; a crash loop must not flood the collector. */
export const MAX_EVENTS_PER_PAGE = 5;
const MAX_TEXT = 2000;

/** Pure: `https://<key>@host/<project>` to the store endpoint, or null. */
export function parseDsn(dsn: string | undefined | null): ParsedDsn | null {
  if (!dsn) return null;
  let url: URL;
  try {
    url = new URL(dsn.trim());
  } catch {
    return null;
  }
  const key = url.username;
  const project = url.pathname.replace(/^\/+|\/+$/g, "");
  if (!key || !/^\d+$/.test(project) || !/^https?:$/.test(url.protocol)) return null;
  const query = new URLSearchParams({ sentry_key: key, sentry_version: "7" });
  return { storeUrl: `${url.protocol}//${url.host}/api/${project}/store/?${query.toString()}` };
}

/** Pure: drop query string and fragment. */
export function scrubUrl(raw: string | undefined | null): string {
  if (!raw) return "";
  const cut = raw.search(/[?#]/);
  return cut === -1 ? raw : raw.slice(0, cut);
}

function truncate(text: string): string {
  return text.length > MAX_TEXT ? `${text.slice(0, MAX_TEXT)}...` : text;
}

/** Pure: strip query strings from any URL inside a stack or message. */
export function scrubText(text: string): string {
  return truncate(text.replace(/(https?:\/\/[^\s?#)]+)[?#][^\s)]*/g, "$1"));
}

export interface ErrorInput {
  readonly name: string;
  readonly message: string;
  readonly stack?: string;
}

export function toErrorInput(reason: unknown): ErrorInput {
  if (reason instanceof Error) {
    return { name: reason.name || "Error", message: reason.message, stack: reason.stack };
  }
  const message = typeof reason === "string" ? reason : "Non-error rejection";
  return { name: "Error", message };
}

function eventId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Pure-ish: the Sentry event body. No user, request headers or cookies. */
export function buildEvent(
  error: ErrorInput,
  context: { readonly url: string; readonly release?: string; readonly environment?: string },
): Record<string, unknown> {
  return {
    event_id: eventId(),
    timestamp: new Date().toISOString(),
    platform: "javascript",
    level: "error",
    logger: "browser",
    ...(context.release ? { release: context.release } : {}),
    environment: context.environment || "production",
    exception: {
      values: [
        {
          type: truncate(error.name),
          value: scrubText(error.message),
        },
      ],
    },
    extra: error.stack ? { stack: scrubText(error.stack) } : {},
    request: { url: scrubUrl(context.url) },
    tags: { surface: "menivor-web" },
  };
}

let installed = false;

/** Install global handlers once. No-op on the server or without a valid DSN. */
export function initGlitchTip(dsn: string | undefined, release?: string): boolean {
  if (installed || typeof window === "undefined") return false;
  const parsed = parseDsn(dsn);
  if (!parsed) return false;
  installed = true;
  let sent = 0;
  const seen = new Set<string>();

  const report = (error: ErrorInput) => {
    const fingerprint = `${error.name}:${error.message}`;
    if (sent >= MAX_EVENTS_PER_PAGE || seen.has(fingerprint)) return;
    seen.add(fingerprint);
    sent += 1;
    const body = JSON.stringify(
      buildEvent(error, {
        url: window.location.href,
        release,
        environment: window.location.hostname === "menivor.com" ? "production" : "preview",
      }),
    );
    try {
      void fetch(parsed.storeUrl, {
        method: "POST",
        body,
        keepalive: true,
        credentials: "omit",
        headers: { "Content-Type": "text/plain;charset=UTF-8" },
      }).catch(() => undefined);
    } catch {
      // Reporting must never break the page.
    }
  };

  window.addEventListener("error", (event) => {
    report(toErrorInput(event.error ?? event.message));
  });
  window.addEventListener("unhandledrejection", (event) => {
    report(toErrorInput(event.reason));
  });
  return true;
}

/** Test hook. */
export function resetGlitchTipForTests(): void {
  installed = false;
}
