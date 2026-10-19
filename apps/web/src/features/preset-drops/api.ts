/**
 * Weekly preset drop (MH9). Public read of the latest released drop; its tiles
 * are ordinary shelf tiles (same preview loops, same one-tap Create).
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import type { PresetTile } from "@/src/features/presets-shelf/api";

export interface PresetDrop {
  readonly week: string | null;
  readonly published_at?: string | null;
  readonly presets: readonly PresetTile[];
}

export function latestDrop(options?: RequestOptions): Promise<PresetDrop> {
  return apiRequest<PresetDrop>("/presets/drops/latest", { anonymous: true, options });
}
