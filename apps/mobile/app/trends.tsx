/** Route: /trends — alias of the canonical Trends Feed: recommended, rank your own series, observe (/trends-feed). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/trends-feed" />;
}
