/** Route: /account/privacy — alias of the canonical /privacy screen (same PrivacyManager). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/privacy" />;
}
