/** Route: /wallet-send — alias of the canonical wallet transfer screen (/wallet/transfer). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/wallet/transfer" />;
}
