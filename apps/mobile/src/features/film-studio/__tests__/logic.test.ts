/**
 * Unit tests for the pure Film Studio logic: form → CreateProjectBody
 * translation, per-shot render-spec construction, and render-progress
 * aggregation. No network, no renderer — deterministic pure functions only.
 */

import { describe, expect, it } from "vitest";
import type { FilmProjectShot } from "@/lib/film";
import type { RenderJob, RenderState } from "@/lib/render";

import {
  allShotsTerminal,
  buildCreateProjectBody,
  buildShotRenderBody,
  isPollableState,
  missingProjectFields,
  overallRenderProgress,
  parseDescriptors,
  shotRenderPhase,
  type FilmStudioFormInput,
} from "../logic";

function form(overrides: Partial<FilmStudioFormInput> = {}): FilmStudioFormInput {
  return {
    title: "Neon Heist",
    characterId: "lead_01",
    characterName: "Mara",
    descriptors: "red coat, silver hair",
    style: "cinematic",
    beatsText: "s1 | Break in\ns2 | Escape",
    totalShots: 8,
    ...overrides,
  };
}

function job(state: RenderState, progress: number): RenderJob {
  return {
    id: "r1",
    backend: "runpod",
    state,
    progress,
    output_refs: [],
    cost_micros: 0,
  };
}

function shot(id: string): FilmProjectShot {
  return {
    shot_id: id,
    order: 0,
    role: "establishing",
    camera_motion: "static",
    duration_ms: 3000,
    prompt: `prompt ${id}`,
    seed: 1,
    status: "locked",
  };
}

describe("parseDescriptors", () => {
  it("splits on commas and newlines and trims, dropping empties", () => {
    expect(parseDescriptors("a, b\n c ,,\n")).toEqual(["a", "b", "c"]);
  });
});

describe("missingProjectFields", () => {
  it("returns [] when the form is complete", () => {
    expect(missingProjectFields(form())).toEqual([]);
  });

  it("flags each empty required field, including missing beats", () => {
    const missing = missingProjectFields(
      form({ title: "  ", characterId: "", characterName: "", beatsText: "" }),
    );
    expect(missing).toContain("title");
    expect(missing).toContain("characterId");
    expect(missing).toContain("characterName");
    expect(missing).toContain("beats");
  });
});

describe("buildCreateProjectBody", () => {
  it("maps the form into a POST /film/projects body", () => {
    const body = buildCreateProjectBody(form({ targetRuntimeS: 30 }));
    expect(body.title).toBe("Neon Heist");
    expect(body.total_shots).toBe(8);
    expect(body.target_runtime_s).toBe(30);
    expect(body.character).toEqual({
      character_id: "lead_01",
      name: "Mara",
      descriptors: ["red coat", "silver hair"],
      style: "cinematic",
    });
    expect(body.beats).toHaveLength(2);
    expect(body.beats[0]).toEqual({ scene_id: "s1", summary: "Break in" });
  });

  it("omits optional fields when empty", () => {
    const body = buildCreateProjectBody(
      form({ descriptors: "", style: "", targetRuntimeS: undefined }),
    );
    expect((body.character as unknown as Record<string, unknown>).descriptors).toBeUndefined();
    expect((body.character as unknown as Record<string, unknown>).style).toBeUndefined();
    expect(body.target_runtime_s).toBeUndefined();
  });
});

describe("buildShotRenderBody", () => {
  it("builds a runpod render spec from the shot prompt with a cost cap", () => {
    const body = buildShotRenderBody(shot("shot_1"), 50000);
    expect(body.backend).toBe("runpod");
    expect(body.spec.prompt).toBe("prompt shot_1");
    expect(body.max_cost_micros).toBe(50000);
  });
});

describe("shotRenderPhase", () => {
  it("classifies each render state", () => {
    expect(shotRenderPhase(undefined)).toBe("idle");
    expect(shotRenderPhase(job("QUEUED", 0))).toBe("queued");
    expect(shotRenderPhase(job("RUNNING", 0.4))).toBe("running");
    expect(shotRenderPhase(job("COMPLETED", 1))).toBe("completed");
    expect(shotRenderPhase(job("FAILED", 0.2))).toBe("failed");
  });
});

describe("overallRenderProgress", () => {
  it("averages per-shot progress, counting COMPLETED as 1", () => {
    const shots = [shot("a"), shot("b")];
    const jobs = { a: job("COMPLETED", 0.5), b: job("RUNNING", 0.5) };
    expect(overallRenderProgress(shots, jobs)).toBeCloseTo(0.75, 5);
  });

  it("treats shots with no job as 0 and returns 0 for an empty film", () => {
    expect(overallRenderProgress([shot("a"), shot("b")], { a: job("RUNNING", 1) })).toBeCloseTo(0.5, 5);
    expect(overallRenderProgress([], {})).toBe(0);
  });
});

describe("allShotsTerminal", () => {
  it("is true only when every shot has a terminal render job", () => {
    const shots = [shot("a"), shot("b")];
    expect(allShotsTerminal(shots, { a: job("COMPLETED", 1), b: job("FAILED", 0) })).toBe(true);
    expect(allShotsTerminal(shots, { a: job("COMPLETED", 1) })).toBe(false);
    expect(allShotsTerminal([], {})).toBe(false);
  });
});

describe("isPollableState", () => {
  it("is true for non-terminal render states", () => {
    expect(isPollableState("RUNNING")).toBe(true);
    expect(isPollableState("COMPLETED")).toBe(false);
    expect(isPollableState("CANCELLED")).toBe(false);
  });
});
