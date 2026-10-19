/** Test helper: a fetch mock routed by "METHOD /path" (path after /api/v1, query kept). */

import { vi } from "vitest";

export type Route = (body: unknown) => { status?: number; body: unknown };

export function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: status < 400 ? "OK" : "Error",
    text: async () => JSON.stringify(body),
    json: async () => body,
    headers: { get: () => null },
  } as unknown as Response;
}

export function mockApi(routes: Record<string, Route | unknown>) {
  const calls: { key: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace(/^.*\/api\/v1/, "");
    const key = `${init?.method ?? "GET"} ${path}`;
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ key, body });
    const route = routes[key] ?? routes[key.split("?")[0] ?? key];
    if (route === undefined) return jsonResponse({ status: 404, message: `no mock for ${key}` }, 404);
    const out: { status?: number; body: unknown } =
      typeof route === "function" ? (route as Route)(body) : { body: route };
    const status = out.status ?? 200;
    return jsonResponse(status < 400 ? { status, data: out.body } : { status, message: out.body }, status);
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;

export function hasEmoji(text: string): boolean {
  return EMOJI.test(text);
}
