/** Route: /templates — alias of the Studio template gallery, where every template opens and can be used. */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/studio/templates" />;
}
