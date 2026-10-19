/** Route: /studio/my-voices — alias of the canonical Brand Voices screen (/account/voices). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/account/voices" />;
}
