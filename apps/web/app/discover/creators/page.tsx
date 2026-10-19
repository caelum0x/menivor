import type { Metadata } from "next";

import { FormatsPage } from "@/src/features/discover/FormatsPage";

export const metadata: Metadata = {
  title: "Rising Formats — Discover",
  description:
    "Viral format patterns and shot-templates gaining momentum — the closest rising-creator signal the API exposes, surfaced honestly.",
};

/**
 * Discover — Rising Formats sub-page (/discover/creators).
 *
 * Named /creators for navigation consistency, but rendered as "Rising Formats"
 * because the API exposes no per-creator analytics endpoint. The page combines
 * format-kind trends (GET /trends/recommended, kind=format) with viral
 * shot-templates (GET /templates) and explains the signal clearly.
 */
export default function DiscoverCreatorsRoute() {
  return <FormatsPage />;
}
