/**
 * Tiny dependency-free `fetch` wrapper (timeout + bounded retry + JSON), matching
 * the sdk-ts style. Used by the platform clients; no token storage — the caller
 * passes the bearer token in per request.
 */

export interface HttpOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: unknown;
  /** bearer token injected per call (never persisted) */
  token?: string;
  timeoutMs?: number;
  retries?: number;
  fetchImpl?: typeof fetch;
}

export class HttpError extends Error {
  constructor(readonly status: number, message: string, readonly detail?: unknown) {
    super(message);
    this.name = "HttpError";
  }
}

export async function httpJson<T>(url: string, opts: HttpOptions = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const retries = opts.retries ?? 2;
  const timeoutMs = opts.timeoutMs ?? 30_000;
  const doFetch = opts.fetchImpl ?? fetch;
  const hasBody = opts.body !== undefined;
  const headers: Record<string, string> = { Accept: "application/json", ...opts.headers };
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`;
  if (hasBody && !headers["Content-Type"]) headers["Content-Type"] = "application/json";

  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      const resp = await doFetch(url, {
        method,
        headers,
        body: hasBody ? JSON.stringify(opts.body) : undefined,
        signal: ctl.signal,
      });
      const text = await resp.text();
      const json = text ? safeParse(text) : undefined;
      if (!resp.ok) {
        // Retry only transient 429/5xx.
        if ((resp.status === 429 || resp.status >= 500) && attempt < retries) {
          lastErr = new HttpError(resp.status, `HTTP ${resp.status}`, json);
          await sleep(Math.min(8000, 2 ** attempt * 500));
          continue;
        }
        throw new HttpError(resp.status, `HTTP ${resp.status}`, json ?? text);
      }
      return json as T;
    } catch (err) {
      lastErr = err;
      if (err instanceof HttpError) throw err;
      if (attempt < retries) {
        await sleep(Math.min(8000, 2 ** attempt * 500));
        continue;
      }
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error("request failed");
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
