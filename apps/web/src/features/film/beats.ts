/** Shared parsing helpers for the Film Studio forms. */

import type { Beat } from "./api";

/** Parse a beats textarea (one per line "scene_id | summary") into Beat[]. */
export function parseBeats(raw: string): Beat[] {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line, i) => {
      const [sceneId = "", ...rest] = line.split("|");
      const summary = rest.join("|").trim();
      return {
        scene_id: sceneId.trim() || `scene_${i + 1}`,
        summary: summary || sceneId.trim(),
      };
    });
}

/** Parse a comma-separated descriptor list, dropping blanks. */
export function parseDescriptors(raw: string): string[] {
  return raw
    .split(",")
    .map((d) => d.trim())
    .filter((d) => d.length > 0);
}

/** Slugify a character name into a stable character_id (falls back to "lead"). */
export function characterId(name: string): string {
  return name.trim().toLowerCase().replace(/\s+/g, "_") || "lead";
}
