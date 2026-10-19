import type { Metadata } from "next";

import { DiscoverPage } from "@/src/features/discover/DiscoverPage";

export const metadata: Metadata = {
  title: "Discover",
  description:
    "Browse trending sounds, rising hashtags, viral formats, and recommended templates — ranked by opportunity so you build to the right trend before it peaks.",
};

/**
 * Discover hub — live trending sounds, hashtags, formats, and viral templates
 * aggregated from the real API (/trends/recommended + /templates).
 */
export default function DiscoverRoute() {
  return <DiscoverPage />;
}
