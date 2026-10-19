import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const token = vi.hoisted(() => async () => "session");
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => token }));
const apiRequest = vi.fn();
vi.mock("@/src/shared/api", () => ({ apiRequest: (...args: unknown[]) => apiRequest(...args) }));

import { PlanUsage } from "./PlanUsage";

const VIEW = (optedIn: boolean) => ({
  plan: "creator",
  month: "2026-10",
  meters: [
    { meter: "encode_minutes", unit: "minutes", used: 300, included: 300, cap_is_target: true, at_cap: true },
    { meter: "minutes_delivered", unit: "minutes", used: 1200, included: 20000, cap_is_target: true, at_cap: false },
  ],
  overage: { opted_in: optedIn, terms_version: "ott-overage-2026-10" },
  ott_plans_sellable: false,
});

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("PlanUsage", () => {
  it("shows usage against caps and turns overage on only when asked", async () => {
    apiRequest.mockResolvedValueOnce(VIEW(false)).mockResolvedValueOnce(VIEW(true));
    render(<PlanUsage />);
    await waitFor(() => screen.getByText(/Encoding: 300 of 300 minutes \(limit reached\)/));
    const box = screen.getByRole("checkbox") as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    await waitFor(() => expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true));
    expect(apiRequest.mock.calls[1]).toEqual(["/ott/studio/plan/overage", expect.objectContaining({ method: "POST", body: { opt_in: true } })]);
  });
});
