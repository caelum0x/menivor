import type { Metadata } from "next";

import { RetentionPanel } from "@/src/features/analytics-deep/RetentionPanel";

export const metadata: Metadata = {
  title: "Retention & funnel — Analytics",
  description:
    "Completion rate, fail rate, funnel progression, and render-time percentiles. Sourced from GET /me/analytics (strictly caller-scoped).",
};

/**
 * Retention and funnel sub-page — real data from GET /me/analytics:
 *   funnel       → created / completed / failed / published counts
 *   render_time  → p50 / p90 / avg render latency + sample count
 */
export default function AnalyticsRetentionRoute() {
  return <RetentionPanel />;
}
