import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";

const token = vi.hoisted(() => async () => "session");
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => token }));
const apiRequest = vi.fn();
vi.mock("@/src/shared/api", () => ({ apiRequest: (...args: unknown[]) => apiRequest(...args) }));

import { StudioAds } from "./StudioAds";

const VIEW = { settings: { ads_on_free: true, ads_on_paid: false, house_ads: true, skip_after_s: 5 }, ads: [] };

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("StudioAds", () => {
  it("offers only free titles for sponsor slots and saves one", async () => {
    apiRequest.mockResolvedValueOnce(VIEW).mockResolvedValueOnce({ id: "a1" }).mockResolvedValueOnce({
      ...VIEW, ads: [{ id: "a1", name: "Coffee week", sponsor: "Bean Co", title_id: "t1", click_url: "", active: true,
        stats: { impressions: 3, completes: 2, skips: 1, clicks: 0 } }] });
    render(<StudioAds titles={[{ id: "t1", title: "Spot", access_tier: "free" }, { id: "t2", title: "Film", access_tier: "paid" }]} />);
    const select = (await screen.findByLabelText("Sponsor video")) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["", "t1"]);
    fireEvent.change(select, { target: { value: "t1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Coffee week" } });
    fireEvent.click(screen.getByRole("button", { name: "Add sponsor slot" }));
    await waitFor(() => screen.getByText(/Coffee week \(Bean Co\): 3 views, 2 watched to the end/));
    expect(apiRequest.mock.calls[1]?.[0]).toBe("/ott/studio/ads");
    expect((screen.getByLabelText("Show ads to paying members too") as HTMLInputElement).checked).toBe(false);
  });

  it("passes the copy denylist", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const rel = "src/features/ott-ads/StudioAds.tsx";
    const units = sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units;
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});
