import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => async () => "session" }));

import { ApiError } from "@/src/shared/api";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { classifyAdCloneFailure, type AdCloneBrief, type AdCloneResult } from "./api";
import { AdCloneWizard } from "./AdCloneWizard";
import { BriefPanel } from "./BriefPanel";
import { beatLabel, briefSummary, linkProblem, sortedEstimates, usd } from "./model";

const web = process.cwd();
const BRIEF = JSON.parse(
  fs.readFileSync(path.resolve(web, "../../tests/fixtures/adclone/brief-tiktok-price-shock.json"), "utf8"),
) as AdCloneBrief;

const PRODUCT = {
  id: "oxhan",
  product: "Very Turkish Time Shirt, Drop 01",
  brand_name: "Oxhan Atelier",
  domain: "oxhanatelier.com",
  cta: "You met me at a very Turkish time in my life. Get yours at oxhanatelier.com.",
  end_card: "Get yours at oxhanatelier.com",
  characters: [
    { key: "H", name: "HERO", role: "hero", persona: "", voice_locked: false },
    { key: "O", name: "OXHAN", role: "oxhan", persona: "", voice_locked: false },
  ],
};

const RESULT: AdCloneResult = {
  brief: BRIEF,
  product: PRODUCT,
  voice: { engine: "kokoro", label: "Kokoro-82M local (Apache-2.0)" },
  paid_render: true,
  variations: [
    {
      plan: {
        episode: 80,
        slug: "clone-x-a",
        aspect: "9:16",
        language: "en",
        lines: [
          { id: "l1", speaker: "H", text: "Simit is twenty-five lira now." },
          { id: "cta", speaker: "H", text: PRODUCT.cta },
        ],
        shots: [{ id: "vP", kind: "payoff", dur: 5, lines: ["cta"] }],
        stills: [{ id: "s0" }],
        edit: [],
        clone: { variation: "a", writer: "bank", hook_pattern: "price_shock",
          writer_note: "writer: template lines (Relay is not configured)" },
      },
      estimates: [
        { engine: "kling", label: "Kling (official API) + lip-sync", configured: true, usd: 1.96, source: "x", keys: [],
          price_basis: "estimate" },
        { engine: "runpod_wan", label: "Wan 2.2 + InfiniteTalk on RunPod", configured: false, usd: 0.9, source: "x", keys: [] },
      ],
      engine: { engine: "kling", label: "Kling (official API) + lip-sync", configured: true, usd: 1.96, source: "x", keys: [],
        dry_run_only: false, reason: "Kling keys are set (default pipeline)", price_basis: "estimate" },
      ai_video_credits: 588,
      midjourney: [{ still: "s0", save_as: "s0.png", prompt_v7: "balcony at golden hour --ar 9:16 --v 7" }],
    },
  ],
};

const DONE_RENDER = {
  job_id: "job-1", state: 1, stage: "finished", engine: "kling", quoted_usd: 1.96, spent_usd: 1.68, project_id: "p1",
  video_url: "https://media.example/final.mp4", poster_url: "", error: "",
};

type Route = (url: string, method: string, body: unknown) => { status: number; data: unknown; message?: string };
interface Call { url: string; method: string; body: unknown; headers: Record<string, string> }

function stubApi(route: Route) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body, headers: (init?.headers ?? {}) as Record<string, string> });
      const { status, data, message } = route(url, method, body);
      const payload = { status, data, message: message ?? (status === 200 ? "" : "refused") };
      return { ok: status === 200, status, statusText: "", headers: new Headers(),
        json: async () => payload, text: async () => JSON.stringify(payload) };
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ad clone model", () => {
  it("checks links", () => {
    expect(linkProblem("")).toMatch(/Paste/);
    expect(linkProblem("https://example.com/a.mp4")).toMatch(/TikTok/);
    expect(linkProblem("https://vt.tiktok.com/ZSbXtdskk/")).toBe("");
    expect(linkProblem("youtu.be/abc")).toBe("");
  });

  it("summarises the brief", () => {
    const s = briefSummary(BRIEF);
    expect(s.hook).toContain("Price shock in the first 2.0 s");
    expect(s.beats).toBe(`${BRIEF.pacing.beat_count} beats over ${BRIEF.pacing.shot_count} shots`);
    expect(s.pacing).toContain("BPM");
    expect(beatLabel({ role: "hook", framing: "close", camera_move: "push_in", shot_type: "talking" })).toBe(
      "hook: close talking, push in",
    );
  });

  it("sorts prices and formats dollars", () => {
    expect(sortedEstimates(RESULT.variations[0]!.estimates).map((e) => e.engine)).toEqual(["runpod_wan", "kling"]);
    expect(usd(1.955)).toBe("$1.96");
  });

  it("classifies failures", () => {
    expect(classifyAdCloneFailure(new ApiError("x", 422, { data: { code: "ip_guard", problems: ["a", 3] } }))).toEqual({
      kind: "ip_guard",
      problems: ["a"],
    });
    expect(classifyAdCloneFailure(new ApiError("x", 403, {})).kind).toBe("off");
    expect(classifyAdCloneFailure(new ApiError("x", 422, { message: "rid: use a TikTok link" }))).toEqual({
      kind: "link",
      message: "use a TikTok link",
    });
    expect(classifyAdCloneFailure(new Error("boom")).kind).toBe("other");
  });
});

describe("clone brief panel", () => {
  it("states what is kept and what is swapped", () => {
    render(<BriefPanel brief={BRIEF} productName="Very Turkish Time Shirt, Drop 01" count={3} />);
    const panel = screen.getByRole("region", { name: "Clone brief" });
    expect(panel.textContent).toContain("Keeps the hook");
    expect(panel.textContent).toContain("Keeps the shot structure");
    expect(panel.textContent).toContain("Keeps the pacing");
    expect(panel.textContent).toContain("Swaps in: Very Turkish Time Shirt, Drop 01");
    expect(panel.textContent).toContain("Makes 3 videos");
  });
});

describe("ad clone wizard", () => {
  it("goes link -> product -> clone and shows prices per engine", async () => {
    let approvals = 0;
    const calls = stubApi((url) => {
      if (url.endsWith("/ad-clone/brief")) return { status: 200, data: { brief: BRIEF } };
      if (url.endsWith("/ad-clone/products")) return { status: 200, data: { products: [PRODUCT] } };
      if (url.endsWith("/ad-clone/plan")) return { status: 200, data: RESULT };
      if (url.endsWith("/ad-clone/render/approve")) {
        approvals += 1;
        if (approvals === 1) return { status: 502, data: { code: "enqueue_failed" } };
        return { status: 200, data: { job_id: "job-1", state: 4, project_id: "p1", ai_video_credits: 588 } };
      }
      if (url.endsWith("/ad-clone/render/job-1")) return { status: 200, data: DONE_RENDER };
      return { status: 404, data: null };
    });
    render(<AdCloneWizard />);
    fireEvent.click(screen.getByRole("button", { name: "Read the ad" }));
    expect(screen.getByText(/Paste the link/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Link to the winning ad"), { target: { value: "https://vt.tiktok.com/ZSbXtdskk/" } });
    fireEvent.click(screen.getByRole("button", { name: "Read the ad" }));
    await screen.findByText("Your product");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Clone brief");
    fireEvent.click(screen.getByRole("button", { name: "16:9 wide" }));
    fireEvent.click(screen.getByRole("button", { name: "3" }));
    fireEvent.click(screen.getByRole("button", { name: "Turkish" }));
    fireEvent.click(screen.getByRole("button", { name: "Clone" }));
    await screen.findByText("Your clones");
    const plan = calls.find((c) => c.url.endsWith("/ad-clone/plan"))!;
    expect(plan.body).toMatchObject({ product: "oxhan", aspect: "16:9", variations: 3, language: "tr" });
    expect((plan.body as { brief: AdCloneBrief }).brief.hook.pattern).toBe("price_shock");
    expect(screen.getByText(/Kling \(official API\) \+ lip-sync \(chosen\)/)).toBeTruthy();
    expect(screen.getByText("$0.90")).toBeTruthy();
    expect(screen.getByText("$1.96 (estimate)")).toBeTruthy();
    expect(screen.getByText(/Relay is not configured/)).toBeTruthy();
    const approveButton = screen.getByRole("button", { name: "Approve and render (588 credits)" });
    fireEvent.click(approveButton);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/Nothing was charged/));
    fireEvent.click(screen.getByRole("button", { name: "Approve and render (588 credits)" }));
    await screen.findByText("Done");
    const approvals_ = calls.filter((c) => c.url.endsWith("/ad-clone/render/approve"));
    expect(approvals_).toHaveLength(2);
    const k1 = approvals_[0]!.headers["Idempotency-Key"];
    expect(k1).toBeTruthy();
    expect(approvals_[1]!.headers["Idempotency-Key"]).toBe(k1);
    expect(approvals_[1]!.body).toMatchObject({ engine: "kling", quoted_credits: 588 });
    expect(screen.getByRole("link", { name: "Open in My reels" }).getAttribute("href")).toBe("/reels");
  });

  it("explains an IP-guard stop", async () => {
    stubApi((url) => {
      if (url.endsWith("/ad-clone/brief")) return { status: 200, data: { brief: BRIEF } };
      if (url.endsWith("/ad-clone/products")) return { status: 200, data: { products: [PRODUCT] } };
      return { status: 422, data: { code: "ip_guard", problems: ["still s1: uses the source's design/brand term 'goggles'"] } };
    });
    render(<AdCloneWizard />);
    fireEvent.change(screen.getByLabelText("Link to the winning ad"), { target: { value: "https://vt.tiktok.com/x/" } });
    fireEvent.click(screen.getByRole("button", { name: "Read the ad" }));
    await screen.findByText("Your product");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(await screen.findByRole("button", { name: "Clone" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/reuse something from the original ad/));
    expect(screen.getByText(/goggles/)).toBeTruthy();
  });
});

const NEW_FILES = [
  "app/ad-clone/page.tsx",
  "src/features/ad-clone/api.ts",
  "src/features/ad-clone/model.ts",
  "src/features/ad-clone/index.ts",
  "src/features/ad-clone/AdCloneWizard.tsx",
  "src/features/ad-clone/BriefPanel.tsx",
  "src/features/ad-clone/ResultView.tsx",
  "src/features/ad-clone/RenderStatus.tsx",
  "src/features/ad-clone/ad-clone.test.tsx",
];

describe("ad clone copy", () => {
  const read = (rel: string) => fs.readFileSync(path.join(web, rel), "utf8");

  it("has no emoji in any new file", () => {
    const emoji = /[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{FE0F}]/u;
    for (const rel of NEW_FILES) expect([rel, emoji.test(read(rel))]).toEqual([rel, false]);
  });

  it("passes the copy denylist", () => {
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const units = NEW_FILES.filter((f) => !f.endsWith(".test.tsx")).flatMap((rel) => sourceUnits(read(rel), rel).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});
