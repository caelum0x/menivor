/**
 * Optional ReelForge editor transport seam.
 *
 * This Worker deliberately owns no identity, persistence, media, or generation
 * endpoints. Those remain on the authenticated FastAPI `/api/v1` contract.
 */

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
} as const;

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status, headers: JSON_HEADERS });
}

function handle(request: Request): Response {
  const url = new URL(request.url);

  if (request.method !== "GET") {
    return json({ error: "method_not_allowed" }, 405);
  }

  switch (url.pathname) {
    case "/":
      return json({
        service: "reelforge-editor-bff",
        role: "stateless-editor-transport",
        authoritativeApi: "/api/v1",
      });
    case "/healthz":
      return json({ status: "ok", timestamp: new Date().toISOString() });
    case "/capabilities":
      return json({
        persistence: false,
        authentication: false,
        productApi: "/api/v1",
        transports: [],
      });
    default:
      return json({ error: "not_found" }, 404);
  }
}

export default {
  fetch(request: Request): Response {
    return handle(request);
  },
};
