import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { TemplateComposeForm } from "./TemplateComposeForm";
import type { TemplateDetail } from "@/src/features/templates/api";

vi.mock("@clerk/nextjs", () => {
  const getToken = async () => "test-token";
  return { useAuth: () => ({ getToken }) };
});

function jsonResponse(data: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    headers: { get: () => null },
    text: async () => JSON.stringify({ status, data }),
  } as unknown as Response;
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const TEMPLATE: TemplateDetail = {
  slug: "minecraft-reddit",
  name: "Minecraft × Reddit",
  genre: "split",
  version: "1.0",
  description: "Split-screen story reel.",
  aspect: "9:16",
  layout: "split",
  default_duration_s: 30,
  min_duration_s: 10,
  max_duration_s: 60,
  caption_style: "karaoke",
  camera_motion: "none",
  effects: [],
  loopable: false,
  tags: [],
  slot_count: 1,
  vfx_intensity: 0,
  audio: { foreground: "", bgm_prompt: "", duck: false, trend_relink: false },
  slots: [],
  inputs: [
    {
      key: "story_url",
      kind: "text",
      label: "Reddit story URL",
      required: true,
      help: "Paste a thread link",
      choices: [],
      default: "",
    },
  ],
};

/** Route the mocked fetch by URL + method. */
function routeFetch() {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    if (u.includes("/instantiate") && method === "POST") {
      return Promise.resolve(
        jsonResponse({
          template: "minecraft-reddit",
          version: "1.0",
          render_spec: { fps: 30 },
          reel_draft: {
            video_subject: "story",
            video_script: "",
            layout: "split",
            caption_style: "karaoke",
            camera_motion: "none",
          },
        }),
      );
    }
    if (u.match(/\/jobs$/) && method === "POST") {
      return Promise.resolve(jsonResponse({ job_id: "job_42", state: 4, progress: 0 }));
    }
    if (u.includes("/jobs/job_42")) {
      return Promise.resolve(
        jsonResponse({ job_id: "job_42", state: 1, result_url: "reel.mp4" }),
      );
    }
    return Promise.reject(new Error(`unexpected fetch: ${method} ${u}`));
  });
}

describe("TemplateComposeForm", () => {
  it("blocks compile until required inputs are filled", () => {
    routeFetch();
    render(<TemplateComposeForm template={TEMPLATE} />);
    const button = screen.getByRole("button", { name: /compile reel/i });
    expect(button).toBeDisabled();
  });

  it("instantiates, compiles, polls, and renders the result video", async () => {
    routeFetch();
    render(<TemplateComposeForm template={TEMPLATE} />);

    fireEvent.change(screen.getByLabelText(/reddit story url/i), {
      target: { value: "https://reddit.com/r/x/1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /compile reel/i }));

    const video = await screen.findByTestId("compose-result-video");
    expect(video).toHaveAttribute("src", "reel.mp4");

    const calls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calls.some((u) => u.match(/\/instantiate$/))).toBe(true);
    expect(calls.some((u) => u.match(/\/jobs$/))).toBe(true);
    expect(calls.some((u) => u.match(/\/jobs\/job_42$/))).toBe(true);
  });

  it("surfaces a failed render as an error alert", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      const u = String(url);
      const method = init?.method ?? "GET";
      if (u.includes("/instantiate") && method === "POST") {
        return Promise.resolve(
          jsonResponse({
            template: "t",
            version: "1",
            render_spec: {},
            reel_draft: {
              video_subject: "s",
              video_script: "",
              layout: "split",
              caption_style: "karaoke",
              camera_motion: "none",
            },
          }),
        );
      }
      if (u.match(/\/jobs$/) && method === "POST") {
        return Promise.resolve(jsonResponse({ job_id: "job_err" }));
      }
      if (u.includes("/jobs/job_err")) {
        return Promise.resolve(
          jsonResponse({ job_id: "job_err", state: -1, error: "gpu oom" }),
        );
      }
      return Promise.reject(new Error(`unexpected: ${u}`));
    });

    render(<TemplateComposeForm template={TEMPLATE} />);
    fireEvent.change(screen.getByLabelText(/reddit story url/i), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: /compile reel/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/gpu oom/i),
    );
  });
});
