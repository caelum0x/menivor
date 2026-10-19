import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => async () => "session" }));
vi.mock("@/lib/api", () => ({
  presignAndUpload: async (file: File) => ({ key: `uploads/u/${file.name}`, get_url: "" }),
  listMusic: async () => [{ id: "output000", name: "Track one", filename: "output000.mp3" }],
}));

import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { AppsShelf } from "./AppsShelf";
import { ScenePanel } from "./ScenePanel";
import { priceText } from "./api";

type Route = (url: string, method: string, body: unknown) => { status: number; data: unknown };

function stubApi(route: Route) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const { status, data } = route(url, method, body);
    const payload = { status, data, message: status === 200 ? "" : "refused" };
    return { ok: status === 200, status, statusText: "", headers: new Headers(),
      json: async () => payload, text: async () => JSON.stringify(payload) };
  }));
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TRANSITION = {
  id: "transition", name: "Transition", blurb: "A smooth moving transition between two photos, ready to post.",
  input: { kind: "two_images", label: "First photo", second_label: "Second photo" },
  preview_url: "https://media/presets/apps/transition.mp4", price: { credit_kind: "standard", credits: 1 },
};

describe("apps shelf", () => {
  it("shows the price on each tile and runs an app with the quoted price", async () => {
    const calls = stubApi((url, method) => {
      if (url.endsWith("/apps")) return { status: 200, data: { apps: [TRANSITION] } };
      if (url.endsWith("/apps/transition/quote")) return { status: 200, data: { app_id: "transition", credit_kind: "standard", credits: 1 } };
      if (url.endsWith("/apps/transition/runs") && method === "POST") return { status: 200, data: { job_id: "r1", state: 4 } };
      if (url.endsWith("/apps/runs/r1")) {
        return { status: 200, data: { job_id: "r1", app_id: "transition", state: 1, outputs: ["https://m/t.mp4"], result: null, error: "", refunded: false } };
      }
      return { status: 404, data: {} };
    });
    render(<AppsShelf />);
    fireEvent.click(await screen.findByRole("button", { name: /Transition/ }));
    const files = screen.getAllByLabelText(/photo/i) as HTMLInputElement[];
    fireEvent.change(files[0]!, { target: { files: [new File(["a"], "a.png", { type: "image/png" })] } });
    fireEvent.change(files[1]!, { target: { files: [new File(["b"], "b.png", { type: "image/png" })] } });
    await new Promise((r) => setTimeout(r, 0));
    fireEvent.click(screen.getByRole("button", { name: "See the price" }));
    expect(await screen.findByText("1 credit")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Make it" }));
    expect(await screen.findByRole("link", { name: "Download" })).toBeTruthy();
    expect(calls.find((c) => c.url.endsWith("/apps/transition/runs"))?.body).toEqual({
      inputs: { image_key: "uploads/u/a.png", image_key_2: "uploads/u/b.png" }, quoted_credits: 1 });
  });

  it("says apps arrive later when none has a preview yet", async () => {
    stubApi(() => ({ status: 200, data: { apps: [] } }));
    render(<AppsShelf />);
    expect(await screen.findByText(/once their previews are ready/)).toBeTruthy();
  });

  it("renders no scene screen while presenters are off", () => {
    const { container } = render(<ScenePanel characterId="c1" live={false} />);
    expect(container.innerHTML).toBe("");
  });

  it("labels prices plainly", () => {
    expect(priceText({ credit_kind: "standard", credits: 0 })).toBe("Free");
    expect(priceText({ credit_kind: "ai_video", credits: 12 })).toBe("12 AI-video credits");
    expect(priceText({ credit_kind: "standard", credits: null, priced_by: "create" })).toBe("Priced before it starts");
  });

  it("passes the copy denylist", () => {
    const web = process.cwd();
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const files = ["src/features/apps-shelf/AppsShelf.tsx", "src/features/apps-shelf/AppUse.tsx", "src/features/apps-shelf/ScenePanel.tsx", "app/apps/page.tsx"];
    const units = files.flatMap((rel) => sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});
