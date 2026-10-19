import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { CreateCompose } from "./CreateCompose";

vi.mock("@clerk/nextjs", () => {
  // Stable reference — real Clerk `getToken` is stable across renders, and the
  // feature effects depend on it, so a fresh fn each render would loop.
  const getToken = async () => "test-token";
  return { useAuth: () => ({ getToken }) };
});

const searchParams = { get: vi.fn() };
vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams,
}));

function jsonResponse(data: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    headers: { get: () => null },
    text: async () => JSON.stringify({ status: 200, data }),
  } as unknown as Response;
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  searchParams.get.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CreateCompose", () => {
  it("lists templates from GET /templates when no slug is present", async () => {
    searchParams.get.mockReturnValue(null);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        templates: [
          {
            slug: "asmr-loop",
            name: "ASMR Loop",
            genre: "asmr",
            version: "1",
            description: "Loopable ASMR.",
            aspect: "9:16",
            layout: "full",
            default_duration_s: 20,
            min_duration_s: 10,
            max_duration_s: 30,
            caption_style: "none",
            camera_motion: "none",
            effects: [],
            loopable: true,
            tags: [],
            slot_count: 0,
          },
        ],
      }),
    );

    render(<CreateCompose />);

    expect(await screen.findByText("ASMR Loop")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /use template/i });
    expect(link).toHaveAttribute("href", "/create/templates?template=asmr-loop");
    const [url] = fetchMock.mock.calls[0]!;
    expect(String(url)).toMatch(/\/templates$/);
  });

  it("loads the template detail from GET /templates/{slug} when a slug is present", async () => {
    searchParams.get.mockReturnValue("asmr-loop");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        slug: "asmr-loop",
        name: "ASMR Loop",
        genre: "asmr",
        version: "1",
        description: "Loopable ASMR.",
        aspect: "9:16",
        layout: "full",
        default_duration_s: 20,
        min_duration_s: 10,
        max_duration_s: 30,
        caption_style: "none",
        camera_motion: "none",
        effects: [],
        loopable: true,
        tags: [],
        slot_count: 0,
        vfx_intensity: 0,
        audio: { foreground: "", bgm_prompt: "", duck: false, trend_relink: false },
        slots: [],
        inputs: [],
      }),
    );

    render(<CreateCompose />);

    expect(
      await screen.findByRole("button", { name: /compile reel/i }),
    ).toBeInTheDocument();
    const [url] = fetchMock.mock.calls[0]!;
    expect(String(url)).toMatch(/\/templates\/asmr-loop$/);
  });
});
