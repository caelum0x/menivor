import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AskVideo } from "./AskVideo";
import { SearchBox } from "./SearchBox";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function stub(data: unknown, ok = true) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return { ok, status: ok ? 200 : 429, json: async () => (ok ? { data } : { message: "Slow down a little." }) } as Response;
  }));
  return calls;
}

describe("SearchBox", () => {
  it("searches this channel after a short pause", async () => {
    const calls = stub({ results: [{ id: "t1", title: "Sourdough basics", channel: "maya", artwork_url: "", score: 0.8 }] });
    render(<SearchBox handle="maya" />);
    fireEvent.change(screen.getByPlaceholderText("Search this channel"), { target: { value: "bread" } });
    await waitFor(() => screen.getByText("Sourdough basics"));
    expect(calls[0]?.url).toContain("/ott/search?q=bread&channel=maya");
    expect(screen.getByText("Sourdough basics").getAttribute("href")).toBe("/c/maya/t1");
  });
});

describe("AskVideo", () => {
  it("shows the answer with the time it came from", async () => {
    stub({ answer: "Rest the dough for an hour [01:10].", citations: [{ start_s: 70, text: "Let the dough rest for an hour." }] });
    render(<AskVideo titleId="t1" />);
    fireEvent.change(screen.getByPlaceholderText("Ask this video"), { target: { value: "How long does it rest?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => screen.getByText("Rest the dough for an hour [01:10]."));
    expect(screen.getByText(/At 1:10: "Let the dough rest for an hour."/)).toBeTruthy();
  });

  it("says plainly when it cannot answer", async () => {
    stub(null, false);
    render(<AskVideo titleId="t1" />);
    fireEvent.change(screen.getByPlaceholderText("Ask this video"), { target: { value: "Anything?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => screen.getByRole("alert"));
    expect(screen.getByRole("alert").textContent).toBe("Slow down a little.");
  });
});
