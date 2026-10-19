/** Route: /team — alias of the canonical workspace members & invites screen (/account/workspaces/members). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/account/workspaces/members" />;
}
