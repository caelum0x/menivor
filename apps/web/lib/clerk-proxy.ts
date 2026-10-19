/**
 * Clerk Frontend API (FAPI) proxy.
 *
 * Clerk's documented fallback for when the FAPI custom domain
 * (clerk.menivor.com) cannot be verified: serve FAPI from a path on the app's
 * own domain (https://menivor.com/__clerk/*) and forward every request to
 * https://frontend-api.clerk.dev/*. Per Clerk's proxy guide the forwarded
 * request must carry:
 *   - `Clerk-Proxy-Url`  the full public proxy URL
 *   - `Clerk-Secret-Key` the instance secret key (server-side only)
 *   - `X-Forwarded-For`  the original client IP
 * https://clerk.com/docs/guides/dashboard/dns-domains/proxy-fapi
 *
 * The browser only talks to this path once `NEXT_PUBLIC_CLERK_PROXY_URL` is
 * set (see lib/clerk.ts `clerkProxyUrl`); until then the forwarder exists but
 * nothing points at it, so behaviour is unchanged.
 */

export const CLERK_PROXY_PATH = "/__clerk";
export const CLERK_FAPI_UPSTREAM = "https://frontend-api.clerk.dev";

/** Hop-by-hop headers (RFC 7230 6.1) plus ones the upstream must not see. */
const STRIPPED_REQUEST_HEADERS: ReadonlySet<string> = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
  // Set explicitly below; never trust a client-supplied value.
  "clerk-proxy-url",
  "clerk-secret-key",
  "x-forwarded-for",
]);

/**
 * Response headers dropped on the way back. `content-encoding` and
 * `content-length` go because the runtime fetch has already decoded the body;
 * passing them through would make the browser try to decode it a second time.
 */
const STRIPPED_RESPONSE_HEADERS: ReadonlySet<string> = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "content-encoding",
  "content-length",
  "set-cookie",
]);

const NULL_BODY_STATUSES: ReadonlySet<number> = new Set([101, 204, 205, 304]);

export function isClerkProxyPath(pathname: string): boolean {
  return (
    pathname === CLERK_PROXY_PATH || pathname.startsWith(`${CLERK_PROXY_PATH}/`)
  );
}

/** Map `/__clerk/v1/client?x=1` to `https://frontend-api.clerk.dev/v1/client?x=1`. */
export function buildUpstreamUrl(requestUrl: string): string {
  const url = new URL(requestUrl);
  const rest = url.pathname.slice(CLERK_PROXY_PATH.length) || "/";
  return `${CLERK_FAPI_UPSTREAM}${rest.startsWith("/") ? rest : `/${rest}`}${url.search}`;
}

/** Original client IP: Cloudflare's header first, then the first XFF hop. */
export function clientIp(headers: Headers): string {
  const cf = headers.get("cf-connecting-ip")?.trim();
  if (cf) return cf;
  const xff = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  if (xff) return xff;
  return headers.get("x-real-ip")?.trim() ?? "";
}

/** Public proxy URL: the configured value, else `<origin>/__clerk`. */
export function resolveProxyUrl(
  requestUrl: string,
  configured: string | undefined,
): string {
  const trimmed = configured?.trim().replace(/\/+$/, "");
  if (trimmed) return trimmed;
  return `${new URL(requestUrl).origin}${CLERK_PROXY_PATH}`;
}

export function buildUpstreamHeaders(
  incoming: Headers,
  opts: { readonly proxyUrl: string; readonly secretKey: string },
): Headers {
  const out = new Headers();
  incoming.forEach((value, key) => {
    if (!STRIPPED_REQUEST_HEADERS.has(key.toLowerCase())) out.set(key, value);
  });
  out.set("Clerk-Proxy-Url", opts.proxyUrl);
  out.set("Clerk-Secret-Key", opts.secretKey);
  const ip = clientIp(incoming);
  if (ip) out.set("X-Forwarded-For", ip);
  return out;
}

/** Copy upstream response headers, keeping every Set-Cookie separately. */
export function buildDownstreamHeaders(upstream: Headers): Headers {
  const out = new Headers();
  upstream.forEach((value, key) => {
    if (!STRIPPED_RESPONSE_HEADERS.has(key.toLowerCase())) out.set(key, value);
  });
  const cookies =
    typeof upstream.getSetCookie === "function"
      ? upstream.getSetCookie()
      : (upstream.get("set-cookie") ?? "")
          .split(/,(?=\s*[^;,=\s]+=)/)
          .map((c) => c.trim())
          .filter(Boolean);
  for (const cookie of cookies) out.append("Set-Cookie", cookie);
  return out;
}

export interface ClerkProxyOptions {
  readonly secretKey: string;
  /** Public proxy URL; defaults to `<request origin>/__clerk`. */
  readonly proxyUrl?: string;
  readonly fetchImpl?: typeof fetch;
}

/** Forward one request to Clerk FAPI and stream the response back. */
export async function proxyClerkRequest(
  req: Request,
  opts: ClerkProxyOptions,
): Promise<Response> {
  if (!opts.secretKey) {
    return new Response("Clerk proxy is not configured.", { status: 503 });
  }
  const doFetch = opts.fetchImpl ?? fetch;
  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const init: RequestInit & { duplex?: "half" } = {
    method: req.method,
    headers: buildUpstreamHeaders(req.headers, {
      proxyUrl: resolveProxyUrl(req.url, opts.proxyUrl),
      secretKey: opts.secretKey,
    }),
    body: hasBody ? req.body : undefined,
    // Pass Clerk redirects (OAuth, handshake) straight to the browser.
    redirect: "manual",
  };
  if (hasBody && req.body) init.duplex = "half";

  let upstream: Response;
  try {
    upstream = await doFetch(buildUpstreamUrl(req.url), init);
  } catch (err) {
    console.error("[clerk-proxy] upstream fetch failed", {
      method: req.method,
      path: new URL(req.url).pathname,
      error: err instanceof Error ? err.message : String(err),
    });
    return new Response("Sign-in service is temporarily unreachable.", {
      status: 502,
    });
  }

  const nullBody = NULL_BODY_STATUSES.has(upstream.status);
  return new Response(nullBody ? null : upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: buildDownstreamHeaders(upstream.headers),
  });
}
