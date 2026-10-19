/** Route: /team-roles — alias of the canonical workspace roles & audit screen (/account/workspaces/roles). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/account/workspaces/roles" />;
}
