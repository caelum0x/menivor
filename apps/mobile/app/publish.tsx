/** Route: /publish — alias of the canonical Publish a Reel screen (/connections/publish). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/connections/publish" />;
}
