import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const signed = { isLoaded: true, isSignedIn: true };
vi.mock("@/lib/auth-state", () => ({ useSignedInState: () => signed }));
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => async () => "session" }));
const uploads: string[] = [];
vi.mock("@/lib/api", () => ({
  presignAndUpload: async (file: File) => {
    uploads.push(file.name);
    return { key: `uploads/u/${file.name}`, get_url: "" };
  },
}));

import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { MyCharacters } from "./MyCharacters";
import { PresetInputs } from "./PresetInputs";
import { RealFaceForm } from "./RealFaceForm";

type Route = (url: string, method: string, body: unknown) => { status: number; data: unknown };

function stubApi(route: Route) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      const { status, data } = route(url, method, body);
      const payload = { status, data, message: status === 200 ? "" : "refused" };
      return { ok: status === 200, status, statusText: "", headers: new Headers(),
        json: async () => payload, text: async () => JSON.stringify(payload) };
    }),
  );
  return calls;
}

function photos(n: number): File[] {
  return Array.from({ length: n }, (_, i) => new File(["x"], `face-${i}.jpg`, { type: "image/jpeg" }));
}

beforeEach(() => {
  signed.isSignedIn = true;
  uploads.length = 0;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("create yourself", () => {
  it("needs 10-20 photos, the spoken phrase, a locked identity and the declaration", async () => {
    const calls = stubApi((url) => {
      if (url.endsWith("/media/identities")) return { status: 200, data: [{ passport_id: "pp_1", version: 2, kind: "identity" }] };
      if (url.endsWith("/my/characters/consent-phrase")) return { status: 200, data: { token: "tok", phrase: "amber river quiet lamp north seven", expires_at: 1 } };
      if (url.endsWith("/my/characters/real-face")) return { status: 200, data: { id: "c1", name: "Me", kind: "real_face", reference_count: 12, trained: false } };
      return { status: 404, data: {} };
    });
    const created = vi.fn();
    const record = vi.fn(async () => new File(["a"], "consent.webm", { type: "audio/webm" }));
    render(<RealFaceForm onCreated={created} record={record} />);
    const create = screen.getByRole("button", { name: /Create my character/ }) as HTMLButtonElement;
    fireEvent.change(screen.getByLabelText("Photos of yourself"), { target: { files: photos(9) } });
    expect(create.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Photos of yourself"), { target: { files: photos(12) } });
    fireEvent.click(screen.getByRole("button", { name: /Get my consent phrase/ }));
    expect((await screen.findByTestId("consent-phrase")).textContent).toContain("amber river quiet lamp north seven");
    fireEvent.click(screen.getByRole("button", { name: /Record the phrase/ }));
    await screen.findByText("Recorded");
    fireEvent.change(await screen.findByRole("combobox"), { target: { value: "pp_1@2" } });
    expect(create.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(create.disabled).toBe(false);
    fireEvent.click(create);
    await waitFor(() => expect(created).toHaveBeenCalled());
    const post = calls.find((c) => c.url.endsWith("/my/characters/real-face"));
    expect(post?.body).toMatchObject({ consent_token: "tok", recording_key: "uploads/u/consent.webm", passport_id: "pp_1",
      passport_version: 2, self_declared: true });
    expect((post?.body as { reference_keys: string[] }).reference_keys).toHaveLength(12);
  });

  it("says plainly when the identity is not locked", async () => {
    stubApi((url) => (url.endsWith("/media/identities") ? { status: 200, data: [] } : { status: 404, data: {} }));
    render(<RealFaceForm onCreated={() => undefined} record={async () => new File([], "a.webm")} />);
    expect(await screen.findByTestId("no-identity-lock")).toBeTruthy();
  });
});

describe("my characters", () => {
  it("prices training in AI-video credits before it starts", async () => {
    const calls = stubApi((url, method) => {
      if (url.endsWith("/my/characters") && method === "GET") {
        return { status: 200, data: { characters: [{ id: "c1", name: "Me", kind: "real_face", reference_count: 12, trained: false,
          consent: { verified: true, words_heard: 6, words_total: 6 } }] } };
      }
      if (url.endsWith("/characters/narrators")) return { status: 200, data: { available: false, narrators: [] } };
      if (url.endsWith("/my/brands")) return { status: 200, data: { brands: [] } };
      if (url.endsWith("/train/quote")) return { status: 200, data: { character_id: "c1", credit_kind: "ai_video", credits: 300, references: 12 } };
      if (url.endsWith("/my/characters/c1/train")) return { status: 200, data: { job_id: "j1" } };
      return { status: 404, data: {} };
    });
    render(<MyCharacters />);
    fireEvent.click(await screen.findByRole("button", { name: /See the training price/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Train for 300 AI-video credits/ }));
    expect(await screen.findByText("Training started")).toBeTruthy();
    expect(calls.find((c) => c.url.endsWith("/my/characters/c1/train"))?.body).toEqual({ quoted_credits: 300 });
    expect(screen.getByText(/Original characters arrive after their art review/)).toBeTruthy();
  });

  it("uploads product shots to a brand kit", async () => {
    const calls = stubApi((url, method) => {
      if (url.endsWith("/my/characters") && method === "GET") return { status: 200, data: { characters: [] } };
      if (url.endsWith("/characters/narrators")) return { status: 200, data: { available: true, narrators: [] } };
      if (url.endsWith("/my/brands")) {
        return { status: 200, data: { brands: [{ id: "k1", name: "Cafe", logo: "", colors: ["#6b3fa0"], voice_name: "",
          caption_style: "", product_shots: [] }] } };
      }
      if (url.endsWith("/my/brands/k1/product-shots")) return { status: 200, data: {} };
      return { status: 404, data: {} };
    });
    render(<MyCharacters />);
    const input = await screen.findByLabelText("Product shots for Cafe");
    fireEvent.change(input, { target: { files: [new File(["p"], "p1.jpg", { type: "image/jpeg" })] } });
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/my/brands/k1/product-shots"))).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ keys: ["uploads/u/p1.jpg"] });
  });

  it("passes the copy denylist", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const units = ["MyCharacters.tsx", "RealFaceForm.tsx", "PresetInputs.tsx"].flatMap(
      (rel) => sourceUnits(fs.readFileSync(path.join(__dirname, rel), "utf8"), `src/features/my-characters/${rel}`).units,
    );
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});

describe("preset inputs", () => {
  it("offers only consented characters and the user's brand kits", async () => {
    stubApi((url) => {
      if (url.endsWith("/my/brands")) return { status: 200, data: { brands: [{ id: "k1", name: "Cafe", logo: "", colors: [], voice_name: "", caption_style: "", product_shots: [] }] } };
      if (url.endsWith("/my/characters")) {
        return { status: 200, data: { characters: [
          { id: "ok", name: "Me", kind: "real_face", reference_count: 12, trained: true, consent: { verified: true, words_heard: 6, words_total: 6 } },
          { id: "no", name: "Unverified", kind: "real_face", reference_count: 12, trained: false, consent: { verified: false, words_heard: 0, words_total: 6 } },
        ] } };
      }
      return { status: 404, data: {} };
    });
    const onChange = vi.fn();
    render(<PresetInputs allowCharacter value={{ brandKitId: "", characterId: "" }} onChange={onChange} />);
    const selects = await screen.findAllByRole("combobox");
    expect(selects).toHaveLength(2);
    expect(screen.queryByText("Unverified")).toBeNull();
    fireEvent.change(selects[1]!, { target: { value: "ok" } });
    expect(onChange).toHaveBeenCalledWith({ brandKitId: "", characterId: "ok" });
  });
});
