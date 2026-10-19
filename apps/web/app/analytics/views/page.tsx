import type { Metadata } from "next";

import { ViewsBreakdown } from "@/src/features/analytics-deep/ViewsBreakdown";

export const metadata: Metadata = {
  title: "Views breakdown — Analytics",
  description:
    "Job counts broken down by composition layout and language. Sourced from GET /me/analytics (strictly caller-scoped).",
};

/**
 * Views breakdown sub-page — real data from GET /me/analytics:
 *   by_layout  → counts per composition layout (pip / split / captions_only…)
 *   by_language → counts per language code (en / tr…)
 */
export default function AnalyticsViewsRoute() {
  return <ViewsBreakdown />;
}
