import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const token = vi.hoisted(() => async () => "session");
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => token }));
const apiRequest = vi.fn();
vi.mock("@/src/shared/api", () => ({ API_BASE: "https://api.example/api/v1", apiRequest: (...a: unknown[]) => apiRequest(...a) }));

import { AiPanel } from "./AiPanel";
import { clock } from "./api";

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("AI panel", () => {
  it("queues the chosen outputs and applies a metadata suggestion", async () => {
    const done = { outputs: [
      { kind: "chapters", language: "en", status: "done", error: "", chapters: [{ start_s: 0, end_s: 60, title: "Start" }] },
      { kind: "metadata", language: "", status: "done", error: "", suggestion: { title: "Bake bread at home", synopsis: "A short lesson." } },
    ] };
    apiRequest.mockImplementation(async (route: string, init?: { method?: string }) => {
      if (init?.method === "POST" && route.endsWith("/ai")) return { outputs: [{ kind: "subtitles", language: "es", status: "queued", error: "" }] };
      if (init?.method === "PATCH") return {};
      return done;
    });
    render(<AiPanel titles={[{ id: "t1", title: "Bread" }]} />);
    await waitFor(() => screen.getByText("Bake bread at home"));
    fireEvent.click(screen.getByLabelText("Spanish"));
    fireEvent.click(screen.getByRole("button", { name: "Make them" }));
    await waitFor(() => expect(apiRequest.mock.calls.some(([r, i]) => r === "/ott/studio/titles/t1/ai" && i?.method === "POST")).toBe(true));
    const post = apiRequest.mock.calls.find(([r, i]) => r === "/ott/studio/titles/t1/ai" && i?.method === "POST");
    expect(post?.[1]).toMatchObject({ body: { kinds: ["subtitles", "chapters"], languages: ["es"], source_language: "en" } });
  });

  it("formats chapter times", () => {
    expect(clock(70)).toBe("1:10");
    expect(clock(3725)).toBe("1:02:05");
  });
});
