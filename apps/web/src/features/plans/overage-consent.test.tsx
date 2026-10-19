import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: false, getToken: async () => null }),
  UserButton: () => null,
}));

import {
  OverageToggle,
  formatRate,
  overageDisclosure,
  overageTermsFrom,
  type OverageTerms,
} from "./OverageConsent";

const RAW = {
  available: true,
  default_on: false,
  cap: 100,
  consent_kind: "plan_overage",
  version: "plan-rate-v1-cap100",
  per_reel_usd: {
    creator: { month: "0.4285", year: "0.3571" },
    pro: { month: "0.3900", year: "0.3250" },
    agency: { month: "0.3300", year: "bad" },
  },
};

const TERMS = overageTermsFrom(RAW) as OverageTerms;

function jsonResponse(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ status: 200, data: body }),
    text: async () => JSON.stringify({ status: 200, data: body }),
    headers: new Headers(),
  } as unknown as Response;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("overage terms", () => {
  it("parses the catalog block and drops malformed prices", () => {
    expect(TERMS.available).toBe(true);
    expect(TERMS.perReelUsd.agency).toEqual({ month: "0.3300" });
    expect(overageTermsFrom(null)).toBeNull();
    expect(overageTermsFrom({ cap: 5 })).toBeNull();
    expect(overageTermsFrom({ ...RAW, cap: 0 })?.available).toBe(false);
  });

  it("formats the exact meter rate", () => {
    expect(formatRate("0.4285")).toBe("$0.4285");
    expect(formatRate("0.3900")).toBe("$0.39");
    expect(formatRate("1")).toBe("$1.00");
  });

  it("discloses the price and the cap, or says nothing is charged", () => {
    const line = overageDisclosure(TERMS, "month");
    expect(line).toContain("off until you turn them on");
    expect(line).toContain("Creator $0.4285");
    expect(line).toContain("Pro $0.39");
    expect(line).toContain("up to 100 a period");
    expect(overageDisclosure(null, "month")).toContain("never charged automatically");
  });
});

describe("OverageToggle", () => {
  it("starts off and records an opt-in with the shown terms version", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        if (init?.method === "PUT") return jsonResponse({ granted: true });
        return jsonResponse(null);
      }),
    );
    render(
      <OverageToggle
        terms={TERMS}
        planKey="creator"
        planName="Creator"
        interval="month"
        getToken={async () => "tok"}
      />,
    );
    const toggle = await screen.findByRole("switch");
    await waitFor(() => expect(toggle).not.toBeDisabled());
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText(/costs \$0\.4285, up to 100 a period/)).toBeInTheDocument();
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    const put = calls.find((c) => c.init?.method === "PUT");
    expect(put?.url).toContain("/me/consent");
    expect(JSON.parse(String(put?.init?.body))).toEqual({
      kind: "plan_overage",
      granted: true,
      version: "plan-rate-v1-cap100",
    });
  });

  it("treats an opt-in to older terms as off", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ granted: true, version: "plan-rate-v1-cap50" })),
    );
    render(
      <OverageToggle
        terms={TERMS}
        planKey="pro"
        planName="Pro"
        interval="month"
        getToken={async () => "tok"}
      />,
    );
    const toggle = await screen.findByRole("switch");
    await waitFor(() => expect(toggle).not.toBeDisabled());
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });
});
