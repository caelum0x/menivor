/** Route: /api-keys — alias of the canonical Developer & API Keys hub (/account/developer-keys). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/account/developer-keys" />;
}
