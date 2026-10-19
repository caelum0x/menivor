/** Route: /wallet-destinations — alias of the canonical receive-identities screen (/wallet/destinations). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/wallet/destinations" />;
}
