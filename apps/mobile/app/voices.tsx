/** Route: /voices — alias of the canonical Brand Voices screen: clone, list, detail, delete (/account/voices). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/account/voices" />;
}
