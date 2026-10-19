import { describe, expect, it, vi } from "vitest";
import {
  buildDownstreamHeaders,
  buildUpstreamHeaders,
  buildUpstreamUrl,
  clientIp,
  isClerkProxyPath,
  proxyClerkRequest,
  resolveProxyUrl,
} from "@/lib/clerk-proxy";

const SECRET = "sk_test_unit_only";
const PROXY = "https://menivor.com/__clerk";

describe("clerk proxy path + URL mapping", () => {
  it("matches only the /__clerk prefix", () => {
    expect(isClerkProxyPath("/__clerk")).toBe(true);
    expect(isClerkProxyPath("/__clerk/v1/client")).toBe(true);
    expect(isClerkProxyPath("/__clerkish")).toBe(false);
    expect(isClerkProxyPath("/sign-up")).toBe(false);
  });

  it("forwards path and query to frontend-api.clerk.dev", () => {
    expect(
      buildUpstreamUrl("https://menivor.com/__clerk/v1/client?_clerk_js_version=5&a=b"),
    ).toBe("https://frontend-api.clerk.dev/v1/client?_clerk_js_version=5&a=b");
    expect(
      buildUpstreamUrl("https://menivor.com/__clerk/npm/@clerk/clerk-js@5/dist/clerk.browser.js"),
    ).toBe("https://frontend-api.clerk.dev/npm/@clerk/clerk-js@5/dist/clerk.browser.js");
    expect(buildUpstreamUrl("https://menivor.com/__clerk")).toBe(
      "https://frontend-api.clerk.dev/",
    );
  });

  it("uses the configured proxy URL, else the request origin", () => {
    expect(resolveProxyUrl("https://menivor.com/__clerk/v1/x", `${PROXY}/`)).toBe(PROXY);
    expect(resolveProxyUrl("https://www.menivor.com/__clerk/v1/x", undefined)).toBe(
      "https://www.menivor.com/__clerk",
    );
  });
});

describe("upstream request headers", () => {
  it("sets the three Clerk proxy headers", () => {
    const h = buildUpstreamHeaders(
      new Headers({ "cf-connecting-ip": "203.0.113.7", cookie: "__client=abc" }),
      { proxyUrl: PROXY, secretKey: SECRET },
    );
    expect(h.get("Clerk-Proxy-Url")).toBe(PROXY);
    expect(h.get("Clerk-Secret-Key")).toBe(SECRET);
    expect(h.get("X-Forwarded-For")).toBe("203.0.113.7");
    expect(h.get("cookie")).toBe("__client=abc");
  });

  it("strips hop-by-hop headers and client-forged Clerk headers", () => {
    const h = buildUpstreamHeaders(
      new Headers({
        connection: "keep-alive",
        "keep-alive": "timeout=5",
        upgrade: "websocket",
        te: "trailers",
        "proxy-authorization": "Basic x",
        host: "menivor.com",
        "content-length": "12",
        "clerk-secret-key": "sk_live_forged",
        "clerk-proxy-url": "https://evil.example",
        "content-type": "application/x-www-form-urlencoded",
      }),
      { proxyUrl: PROXY, secretKey: SECRET },
    );
    for (const k of ["connection", "keep-alive", "upgrade", "te", "proxy-authorization", "host", "content-length"]) {
      expect(h.has(k)).toBe(false);
    }
    expect(h.get("clerk-secret-key")).toBe(SECRET);
    expect(h.get("clerk-proxy-url")).toBe(PROXY);
    expect(h.get("content-type")).toBe("application/x-www-form-urlencoded");
  });

  it("derives the client IP from CF, then the first XFF hop, then x-real-ip", () => {
    expect(clientIp(new Headers({ "x-forwarded-for": "198.51.100.1, 10.0.0.1" }))).toBe(
      "198.51.100.1",
    );
    expect(clientIp(new Headers({ "x-real-ip": "198.51.100.9" }))).toBe("198.51.100.9");
    expect(clientIp(new Headers())).toBe("");
    const none = buildUpstreamHeaders(new Headers(), { proxyUrl: PROXY, secretKey: SECRET });
    expect(none.has("x-forwarded-for")).toBe(false);
  });
});

describe("downstream response headers", () => {
  it("keeps every Set-Cookie and drops encoding/hop-by-hop headers", () => {
    const up = new Headers();
    up.append("set-cookie", "__client=1; Path=/; HttpOnly; Secure");
    up.append("set-cookie", "__client_uat=2; Path=/; Expires=Wed, 01 Oct 2026 00:00:00 GMT");
    up.set("content-type", "application/json");
    up.set("content-encoding", "br");
    up.set("content-length", "99");
    up.set("transfer-encoding", "chunked");
    up.set("location", "https://accounts.google.com/o/oauth2");
    const out = buildDownstreamHeaders(up);
    expect(out.getSetCookie()).toEqual([
      "__client=1; Path=/; HttpOnly; Secure",
      "__client_uat=2; Path=/; Expires=Wed, 01 Oct 2026 00:00:00 GMT",
    ]);
    expect(out.has("content-encoding")).toBe(false);
    expect(out.has("content-length")).toBe(false);
    expect(out.has("transfer-encoding")).toBe(false);
    expect(out.get("content-type")).toBe("application/json");
    expect(out.get("location")).toBe("https://accounts.google.com/o/oauth2");
  });
});

describe("proxyClerkRequest", () => {
  it("forwards method, body and headers and streams the response back", async () => {
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const body = await new Response(init?.body ?? null).text();
      const headers = new Headers({ "content-type": "application/json" });
      headers.append("set-cookie", "__client=1; Path=/");
      headers.append("set-cookie", "__session=2; Path=/");
      return new Response(JSON.stringify({ echoed: body }), { status: 200, headers });
    });
    const req = new Request("https://menivor.com/__clerk/v1/client/sign_ups?_clerk_js_version=5", {
      method: "POST",
      headers: {
        "content-type": "application/x-www-form-urlencoded",
        "cf-connecting-ip": "203.0.113.7",
        connection: "keep-alive",
      },
      body: "email_address=a%40b.co",
    });
    const res = await proxyClerkRequest(req, {
      secretKey: SECRET,
      proxyUrl: PROXY,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe(
      "https://frontend-api.clerk.dev/v1/client/sign_ups?_clerk_js_version=5",
    );
    expect(init?.method).toBe("POST");
    expect(init?.redirect).toBe("manual");
    const sent = new Headers(init?.headers);
    expect(sent.get("clerk-proxy-url")).toBe(PROXY);
    expect(sent.get("clerk-secret-key")).toBe(SECRET);
    expect(sent.get("x-forwarded-for")).toBe("203.0.113.7");
    expect(sent.has("connection")).toBe(false);

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ echoed: "email_address=a%40b.co" });
    expect(res.headers.getSetCookie()).toHaveLength(2);
  });

  it("sends no body on GET and passes redirects through untouched", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(null, { status: 307, headers: { location: "https://accounts.google.com/x" } }),
    );
    const res = await proxyClerkRequest(
      new Request("https://menivor.com/__clerk/v1/oauth_callback?code=1"),
      { secretKey: SECRET, fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.body).toBeUndefined();
    expect(new Headers(init.headers).get("clerk-proxy-url")).toBe(
      "https://menivor.com/__clerk",
    );
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("https://accounts.google.com/x");
  });

  it("handles 204 upstream responses without a body", async () => {
    const fetchImpl = vi.fn(async () => new Response(null, { status: 204 }));
    const res = await proxyClerkRequest(
      new Request("https://menivor.com/__clerk/v1/x", { method: "DELETE" }),
      { secretKey: SECRET, fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(res.status).toBe(204);
  });

  it("returns 503 without a secret key and never calls upstream", async () => {
    const fetchImpl = vi.fn();
    const res = await proxyClerkRequest(new Request("https://menivor.com/__clerk/v1/client"), {
      secretKey: "",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(res.status).toBe(503);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("returns 502 when upstream is unreachable", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const fetchImpl = vi.fn(async () => {
      throw new Error("network down");
    });
    const res = await proxyClerkRequest(new Request("https://menivor.com/__clerk/v1/client"), {
      secretKey: SECRET,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(res.status).toBe(502);
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });
});
