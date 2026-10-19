/** Route: /publish-schedule — alias of the canonical Scheduled publishes screen (/scheduled). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/scheduled" />;
}
