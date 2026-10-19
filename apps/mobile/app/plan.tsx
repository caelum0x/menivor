/** Route: /plan — alias of the canonical Plans & Usage screen (/wallet/plans). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/wallet/plans" />;
}
