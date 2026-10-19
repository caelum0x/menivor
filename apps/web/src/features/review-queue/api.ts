/** Review queue client: `/api/v1/review/...` (creatives waiting for a swipe). */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import { apiPath } from "@/src/shared/api/path";

export type ReviewDecision = "approve" | "reject" | "regenerate";

export interface ReasonChip {
  id: string;
  label: string;
}

export interface ReviewItem {
  id: string;
  source: string;
  external_ref: string;
  title: string;
  summary: string;
  status: string;
  payload: {
    library_item_id?: string;
    space_id?: string;
    kind?: "image" | "video" | string;
    media_url?: string;
    regenerate_credits?: number;
  };
}

export interface ReviewStats {
  by_status: Record<string, number>;
  top_reasons: { id: string; label: string; count: number }[];
}

export interface ReviewQueue {
  items: ReviewItem[];
  pending: number;
  reasons: { approve: ReasonChip[]; fix: ReasonChip[] };
  stats: ReviewStats;
}

export interface DecideResult {
  item: ReviewItem;
  idempotent: boolean;
  review: { status: string; reason: string; reason_label: string } | null;
  regenerate_action: { id: string; status: string; credits_estimate: number } | null;
}

export function getQueue(options?: RequestOptions): Promise<ReviewQueue> {
  return apiRequest<ReviewQueue>("/review/queue", { options });
}

export function decide(
  itemId: string,
  body: { decision: ReviewDecision; reason?: string; note?: string; confirm_spend?: boolean },
  options?: RequestOptions,
): Promise<DecideResult> {
  return apiRequest<DecideResult>(apiPath`/review/${itemId}/decide`, {
    method: "POST",
    body,
    options,
  });
}
