/** Route: /wallet-topup — alias of the canonical wallet top-up screen (/wallet/top-up). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/wallet/top-up" />;
}
