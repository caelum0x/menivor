import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const token = vi.hoisted(() => async () => "session");
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => token }));
const apiRequest = vi.fn();
vi.mock("@/src/shared/api", () => ({ API_BASE: "https://api.example/api/v1", apiRequest: (...a: unknown[]) => apiRequest(...a) }));

import { StudioLinear } from "./StudioLinear";

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("StudioLinear", () => {
  it("builds the loop from free published titles in the order ticked", async () => {
    apiRequest.mockResolvedValueOnce({ linear: [] }).mockResolvedValueOnce({ id: "l1", slug: "maya", name: "Maya",
      title_ids: ["t3", "t1"], ad_break_every: 2, watch_url: "https://fast.menivor.com/channels/maya/master.m3u8" });
    render(<StudioLinear titles={[
      { id: "t1", title: "One", access_tier: "free", status: "published" },
      { id: "t2", title: "Paid", access_tier: "paid", status: "published" },
      { id: "t3", title: "Three", access_tier: "free", status: "published" },
    ]} />);
    expect(screen.queryByText("Paid")).toBeNull();
    fireEvent.click(screen.getByLabelText("Three"));
    fireEvent.click(screen.getByLabelText("One"));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save channel" }));
    await waitFor(() => screen.getByText(/Plays at/));
    expect(apiRequest.mock.calls[1]?.[1]).toMatchObject({ method: "POST", body: { title_ids: ["t3", "t1"], ad_break_every: 2 } });
    expect(screen.getByRole("link", { name: "XMLTV" }).getAttribute("href")).toBe("https://api.example/api/v1/ott/linear/maya/epg.xml");
  });
});
