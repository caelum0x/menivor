import type { Metadata } from "next";

import { SoundsPage } from "@/src/features/discover/SoundsPage";

export const metadata: Metadata = {
  title: "Trending Sounds — Discover",
  description:
    "Sounds with rising velocity and low saturation — ranked by opportunity so you attach the right audio before the wave peaks.",
};

/**
 * Discover — Trending Sounds sub-page.
 * Wired to GET /trends/recommended filtered to kind=sound.
 */
export default function DiscoverSoundsRoute() {
  return <SoundsPage />;
}
