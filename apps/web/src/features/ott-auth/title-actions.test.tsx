import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { parseCredits, formatCredits } from "@/src/features/ott-cms/api";
import { writeSession } from "./session-store";
import { TitleActions } from "./TitleActions";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

function stub() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    let data: unknown = {};
    if (url.endsWith("/watchlist")) data = { items: [] };
    else if (url.includes("/ratings/")) {
      const stars = init?.body ? JSON.parse(String(init.body)).stars : null;
      data = { title_id: "t1", mine: stars, count: stars ? 1 : 0, average: stars };
    } else if (url.includes("/watchlist/")) data = { title_id: "t1" };
    return { ok: true, status: 200, json: async () => ({ data }) } as Response;
  }));
  return calls;
}

describe("my list and ratings", () => {
  it("saves to my list and rates, as the signed-in channel viewer", async () => {
    writeSession("maya", { session: "vs-1", expiresAt: 4102444800, name: "ana" });
    const calls = stub();
    render(<TitleActions handle="maya" titleId="t1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Save to my list" }));
    await screen.findByRole("button", { name: "On my list" });
    fireEvent.click(screen.getByRole("button", { name: "4 of 5" }));
    await waitFor(() => expect(screen.getByText("4.0 from 1")).toBeTruthy());
    const put = calls.find((c) => c.url.endsWith("/watchlist/t1"));
    expect(put?.init?.method).toBe("PUT");
    expect((put?.init?.headers as Record<string, string>)["X-OTT-Viewer"]).toBe("vs-1");
  });

  it("shows nothing to a visitor who is not signed in", () => {
    stub();
    const { container } = render(<TitleActions handle="maya" titleId="t1" />);
    expect(container.innerHTML).toBe("");
  });
});

describe("cast and crew", () => {
  it("reads one name and role per line", () => {
    expect(parseCredits("Ana Lee, Director\nno role here\nSam, Jr., Host\n")).toEqual([
      { name: "Ana Lee", role: "Director" }, { name: "Sam, Jr.", role: "Host" }]);
    expect(formatCredits([{ name: "Ana Lee", role: "Director" }])).toBe("Ana Lee, Director");
    expect(parseCredits(Array.from({ length: 40 }, (_, n) => `P${n}, Crew`).join("\n"))).toHaveLength(30);
  });
});
