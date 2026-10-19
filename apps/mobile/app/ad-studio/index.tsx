/** Route: /ad-studio — product URL -> ad angles -> rendered ad variants. */
import { Stack } from "expo-router";

import { AdStudioHomeScreen } from "@/src/features/ad-studio";

export default function AdStudioRoute() {
  return (
    <>
      <Stack.Screen options={{ title: "Ad Studio", presentation: "card" }} />
      <AdStudioHomeScreen />
    </>
  );
}
