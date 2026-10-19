/**
 * Route: /reels — legacy alias. The canonical reel library is the Jobs tab
 * (status filters, drafts, archive and per-reel management), so this route
 * forwards there instead of rendering a second copy of the same GET /jobs data.
 */
import { Redirect } from "expo-router";

export default function ReelsRedirect() {
  return <Redirect href="/(tabs)/jobs" />;
}
