import type { PilotCapabilities } from "./generated/reelforge-v1.js";

export type GenerationFeature = "reels" | "broll";

export function canGenerate(
  capabilities: PilotCapabilities,
  feature: GenerationFeature,
): boolean {
  return capabilities.generation[feature];
}

export function canonicalGenerationRoute(
  capabilities: PilotCapabilities,
  feature: GenerationFeature,
): string {
  return capabilities.canonical_routes[feature];
}
