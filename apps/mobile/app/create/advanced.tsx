/**
 * Route: /create/advanced — the full reel wizard (screen recording, custom
 * script, music, caption style, variants, workspaces). The Create tab opens
 * the one-flow by default; deep links that carry wizard params (Spark
 * prefill, drafts, imported footage, B-roll) open this screen's content
 * directly from the tab.
 */
import { Stack } from "expo-router";

import { CreateScreen } from "@/src/features/reel-create";

export default function AdvancedCreateRoute() {
  return (
    <>
      <Stack.Screen options={{ title: "Full editor", presentation: "card" }} />
      <CreateScreen />
    </>
  );
}
