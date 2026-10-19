import type { Metadata } from "next";

import { HooksBreakdown } from "@/src/features/analytics-deep/HooksBreakdown";

export const metadata: Metadata = {
  title: "Top hooks — Analytics",
  description:
    "Your most-used opening hook lines and templates, all-time. Sourced from GET /me/analytics top_content (strictly caller-scoped).",
};

/**
 * Top hooks sub-page — real data from GET /me/analytics:
 *   top_content.hooks     → most-used opening lines (all-time)
 *   top_content.templates → most-used shot-template slugs (all-time)
 */
export default function AnalyticsHooksRoute() {
  return <HooksBreakdown />;
}
