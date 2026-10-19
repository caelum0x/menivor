import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MotionStudio } from "./MotionStudio";

const getToken = async () => "tok";
const auth = { getToken, isLoaded: true };
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => auth,
  UserButton: () => null,
}));

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

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const CATALOG = {
  status: 200,
  data: {
    motions: [
      {
        id: "orbit",
        name: "Orbit",
        category: "orbit",
        render_class: "model",
        description: "Orbit around subject",
        intensity: 50,
        tags: ["orbit"],
        requires_provider: true,
      },
    ],
  },
};

const EMPTY_HISTORY = { status: 200, data: { history: [] } };

const DETAIL = {
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
};

const PLAN = {
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
      intensity: 50,
    },
  },
};

/** Route each fetch by URL so ordering of the parallel loads doesn't matter. */
function routedFetch() {
  return vi.fn((url: string, init?: { method?: string; body?: string }) => {
    const method = init?.method ?? "GET";
    if (url.includes("/motion/history")) return Promise.resolve(jsonResponse(EMPTY_HISTORY));
    if (url.includes("/motion/orbit/compile") && method === "POST")
      return Promise.resolve(jsonResponse(PLAN));
    if (url.includes("/motion/orbit")) return Promise.resolve(jsonResponse(DETAIL));
    if (url.endsWith("/motion")) return Promise.resolve(jsonResponse(CATALOG));
    return Promise.resolve(jsonResponse({ status: 200, data: {} }));
  });
}

describe("MotionStudio", () => {
  it("loads the catalog from GET /motion and renders presets", async () => {
    const fetchMock = routedFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<MotionStudio />);

    await waitFor(() => expect(screen.getByText("Orbit")).toBeInTheDocument());
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).endsWith("/motion")),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes("/motion/history")),
    ).toBe(true);
  });

  it("opens a preset detail then compiles it via POST /motion/{id}/compile", async () => {
    const fetchMock = routedFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<MotionStudio />);
    await waitFor(() => expect(screen.getByText("Orbit")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Orbit" }));

    await waitFor(() =>
      expect(screen.getByText(/camera orbits clockwise/i)).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: /compile motion plan/i }));

    await waitFor(() => expect(screen.getByText(/81 frames/i)).toBeInTheDocument());

    const compileCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/motion/orbit/compile"),
    );
    expect(compileCall).toBeTruthy();
    expect(compileCall?.[1]?.method).toBe("POST");
    expect(JSON.parse(compileCall?.[1]?.body as string)).toEqual({ intensity: 50 });
  });
});
