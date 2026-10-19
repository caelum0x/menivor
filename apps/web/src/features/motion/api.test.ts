import { afterEach, describe, expect, it, vi } from "vitest";

import { compileMotion, getMotion, getMotionHistory, listMotions } from "./api";

function jsonResponse(
  body: unknown,
  init: { ok?: boolean; status?: number } = {},
): Response {
  const ok = init.ok ?? true;
  return {
    ok,
    status: init.status ?? (ok ? 200 : 400),
    statusText: ok ? "OK" : "Error",
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  } as unknown as Response;
}

function mockFetch() {
  const fn = vi.fn();
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("listMotions", () => {
  it("calls GET /motion and returns the catalog", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          motions: [
            {
              id: "zoom_in",
              name: "Zoom In",
              category: "push",
              render_class: "filter",
              description: "Slow push in",
              intensity: 50,
              tags: ["push"],
              requires_provider: false,
            },
          ],
        },
      }),
    );

    const res = await listMotions({ token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/motion");
    expect(init.method).toBe("GET");
    expect(init.headers["x-api-key"]).toBe("tok");
    expect(res.motions).toHaveLength(1);
    expect(res.motions[0]!.id).toBe("zoom_in");
    expect(res.motions[0]!.requires_provider).toBe(false);
  });
});

describe("getMotionHistory", () => {
  it("calls GET /motion/history with a limit and returns rows", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          history: [
            {
              id: "h1",
              preset_id: "zoom_in",
              motion_class: "filter",
              intensity: 60,
              provider_key: "",
              output_ref: null,
            },
          ],
        },
      }),
    );

    const res = await getMotionHistory({ limit: 25 }, { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/motion/history?limit=25");
    expect(init.method).toBe("GET");
    expect(res.history[0]!.preset_id).toBe("zoom_in");
  });

  it("defaults the limit to 50 when omitted", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ status: 200, data: { history: [] } }),
    );

    await getMotionHistory({}, { token: "tok" });

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/motion/history?limit=50");
  });
});

describe("getMotion", () => {
  it("calls GET /motion/{preset_id} and returns the detail", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          id: "orbit",
          name: "Orbit",
          category: "orbit",
          render_class: "model",
          description: "Orbit around subject",
          intensity: 50,
          tags: ["orbit"],
          requires_provider: true,
          model: {
            capability: "image_to_video",
            camera_pose: "ClockWise",
            prompt_fragment: "camera orbits clockwise",
            speed: 1.0,
            supports_intensity: true,
            license_class: "open_weights",
          },
        },
      }),
    );

    const res = await getMotion("orbit", { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/motion/orbit");
    expect(init.method).toBe("GET");
    expect(res.model?.camera_pose).toBe("ClockWise");
  });
});

describe("compileMotion", () => {
  it("POSTs /motion/{preset_id}/compile with the intensity body", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          preset_id: "orbit",
          motion_class: "model",
          filter: null,
          model: {
            preset_id: "orbit",
            capability: "image_to_video",
            camera_pose: "ClockWise",
            prompt_fragment: "camera orbits clockwise",
            speed: 1.0,
            width: 832,
            height: 480,
            length: 81,
            provider_hints: ["wan_camera"],
            param_map: [],
            license_class: "open_weights",
            intensity: 70,
          },
        },
      }),
    );

    const res = await compileMotion("orbit", { intensity: 70 }, { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/motion/orbit/compile");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ intensity: 70 });
    expect(res.motion_class).toBe("model");
    expect(res.model?.length).toBe(81);
  });
});
