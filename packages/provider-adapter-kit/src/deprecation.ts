/** Model lifecycle + sunset registry + migration hints (mirror of `deprecation.py`). */

export interface DeprecationEntry {
  sunset: string; // ISO date
  replacement: string;
}

export const DEPRECATION_REGISTRY: Record<string, DeprecationEntry> = {
  "openai/sora-2": { sunset: "2026-09-24", replacement: "google/veo-3.1" },
  "runwayml/gen-3a": { sunset: "2026-07-30", replacement: "runwayml/gen-4" },
  "kwaivgi/kling-v1.6": { sunset: "2027-01-01", replacement: "kwaivgi/kling-v2-master" },
};

export type Lifecycle = "active" | "deprecating" | "sunset";

/** ISO dates compare lexicographically = chronologically → `today` is a param. */
export function lifecycle(modelId: string, today: string): Lifecycle {
  const entry = DEPRECATION_REGISTRY[modelId];
  if (!entry) return "active";
  return today >= entry.sunset ? "sunset" : "deprecating";
}

export function replacementFor(modelId: string): string | null {
  return DEPRECATION_REGISTRY[modelId]?.replacement ?? null;
}

export interface MigrationHint {
  model: string;
  status: Lifecycle;
  should_migrate: boolean;
  replacement: string | null;
}

export function migrate(modelId: string, today: string): MigrationHint {
  const status = lifecycle(modelId, today);
  return {
    model: modelId,
    status,
    should_migrate: status === "deprecating" || status === "sunset",
    replacement: replacementFor(modelId),
  };
}
