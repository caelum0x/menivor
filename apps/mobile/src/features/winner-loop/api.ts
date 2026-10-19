/**
 * Remake-winner loop API: wraps /insights/loops/*.
 *
 *   GET  /insights/loops                   winners board + loops + candidates
 *   GET  /insights/loops/{batch_id}        ranking, why it won, lineage, timeline
 *   PUT  /insights/loops/{batch_id}        mode, auto-publish platforms, spend cap
 *   POST /insights/loops/{batch_id}/check  read the numbers now (early read)
 *   POST /insights/loops/{batch_id}/remake one-click "Remake winner"
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

import type { LoopBoard, LoopConfigInput, LoopDetail, RemakeResult } from "./types";

const base = (batchId: string) => `/insights/loops/${encodeURIComponent(batchId)}`;

/** Winners board, loop-enabled projects and recent projects that could join. */
export function getLoopBoard(options?: RequestOptions): Promise<LoopBoard> {
  return apiRequest<LoopBoard>("/insights/loops", { options });
}

/** One project's ranking, explanation, lineage and timeline. */
export function getLoop(batchId: string, options?: RequestOptions): Promise<LoopDetail> {
  return apiRequest<LoopDetail>(base(batchId), { options });
}

/** Set the loop mode (off/manual/auto), auto-publish platforms and spend cap. */
export function configureLoop(
  batchId: string,
  body: LoopConfigInput,
  options?: RequestOptions,
): Promise<LoopDetail> {
  return apiRequest<LoopDetail>(base(batchId), { method: "PUT", body, options });
}

/** Pull the variants' platform numbers now (an early read before the window closes). */
export function checkLoopNow(batchId: string, options?: RequestOptions): Promise<LoopDetail> {
  return apiRequest<LoopDetail>(`${base(batchId)}/check`, { method: "POST", options });
}

/** One-click "Remake winner": renders 3 new variants from the winning hook. */
export function remakeWinner(
  batchId: string,
  acceptLowConfidence: boolean,
  options?: RequestOptions,
): Promise<RemakeResult> {
  return apiRequest<RemakeResult>(`${base(batchId)}/remake`, {
    method: "POST",
    body: { accept_low_confidence: acceptLowConfidence },
    // The server dedupes remakes per batch (a replay returns `replayed: true`).
    options,
  });
}
