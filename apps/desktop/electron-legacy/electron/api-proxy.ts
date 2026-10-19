import { isAllowedApiHost } from "./config-store";
import { ALLOWED_METHODS } from "./ipc";
import type { ApiRequestInput, HttpMethod } from "./ipc";
import type { ConfigStore } from "./config-store";

/**
 * Main-process HTTP proxy for authenticated backend calls.
 *
 * The renderer never holds the API token or constructs full URLs: it hands main
 * a `{ method, path, body }` envelope, and this module attaches the stored token
 * as the `x-api-key` header, prefixes the configured API base, and unwraps the
 * backend's `{ status, data, message }` envelope (mirroring the web client's
 * `request<T>()`). All inputs are validated here — this is the trust boundary.
 */

/** Backend response envelope, per the ReelForge v1 contract. */
interface ApiEnvelope<T> {
  status?: string;
  data?: T;
  message?: string;
}

/** Validate the renderer-supplied request envelope, throwing on any bad input. */
function validateInput(raw: unknown): { method: HttpMethod; path: string; body?: unknown } {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("Invalid API request: expected an object.");
  }
  const input = raw as ApiRequestInput;

  const method = (input.method ?? "GET") as HttpMethod;
  if (!ALLOWED_METHODS.includes(method)) {
    throw new Error(`Invalid API request: method "${String(input.method)}" is not allowed.`);
  }

  const path = input.path;
  if (typeof path !== "string" || !path.startsWith("/")) {
    throw new Error('Invalid API request: "path" must be a string beginning with "/".');
  }
  // Reject attempts to escape the configured base (absolute URLs / schema).
  if (path.includes("://") || path.startsWith("//")) {
    throw new Error("Invalid API request: absolute URLs are not permitted.");
  }

  return { method, path, body: input.body };
}

/**
 * Perform one authenticated request and return the unwrapped `data` payload.
 * Throws a plain `Error` carrying the backend's message on any non-2xx result,
 * so the renderer sees a clean, serialisable failure.
 */
export async function apiRequest<T>(store: ConfigStore, raw: unknown): Promise<T> {
  const { method, path, body } = validateInput(raw);
  const { apiBase } = store.getPublic();
  const token = store.getToken();

  const hasBody = body !== undefined && method !== "GET";
  const headers: Record<string, string> = {};
  // Only attach the secret token when the configured base points at an approved
  // host — never hand it to a renderer-chosen destination.
  if (token && isAllowedApiHost(apiBase)) headers["x-api-key"] = token;
  if (hasBody) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(`${apiBase}${path}`, {
      method,
      headers,
      body: hasBody ? JSON.stringify(body) : undefined,
      // Do not follow redirects: undici keeps the custom `x-api-key` header on
      // cross-origin 3xx hops, so a redirect could leak the token. We refuse to
      // follow any redirect instead.
      redirect: "manual",
    });
  } catch (err) {
    throw new Error(
      `Network error contacting the API: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  if (res.type === "opaqueredirect" || (res.status >= 300 && res.status < 400)) {
    throw new Error("Refusing to follow a redirect from the API (possible token-leak vector).");
  }

  const rawText = await res.text();
  let envelope: ApiEnvelope<T> | null = null;
  if (rawText) {
    try {
      envelope = JSON.parse(rawText) as ApiEnvelope<T>;
    } catch {
      envelope = null;
    }
  }

  if (!res.ok) {
    const message =
      envelope?.message ?? `Request failed with status ${res.status} ${res.statusText}`.trim();
    throw new Error(message);
  }

  if (envelope === null) {
    throw new Error("Malformed response: expected a JSON envelope from the API.");
  }

  return (envelope.data ?? (envelope as unknown as T)) as T;
}
