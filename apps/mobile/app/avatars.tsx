/** Route: /avatars — alias of the canonical Avatar Library: create, list, detail (/account/avatars). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/account/avatars" />;
}
