/** Route: /connections — alias of the canonical Connected Accounts manager (/connections/manage). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/connections/manage" />;
}
