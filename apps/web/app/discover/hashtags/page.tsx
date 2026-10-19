import type { Metadata } from "next";

import { HashtagsPage } from "@/src/features/discover/HashtagsPage";

export const metadata: Metadata = {
  title: "Rising Hashtags — Discover",
  description:
    "Hashtags gaining momentum right now — ranked by opportunity so you use them before they saturate the feed.",
};

/**
 * Discover — Rising Hashtags sub-page.
 * Wired to GET /trends/recommended filtered to kind=hashtag.
 */
export default function DiscoverHashtagsRoute() {
  return <HashtagsPage />;
}
