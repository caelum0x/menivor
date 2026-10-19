/**
 * Route: /create/results?jobs=a,b,c — live progress and pick screen for a
 * one-flow run. Job ids are validated (at most three, safe characters only)
 * before any request is made.
 */
import { Stack, useLocalSearchParams } from "expo-router";

import { VariantResultsScreen, parseJobIds } from "@/src/features/one-flow";

export default function CreateResultsRoute() {
  const { jobs } = useLocalSearchParams<{ jobs?: string | string[] }>();
  return (
    <>
      <Stack.Screen options={{ title: "Your 3 reels", presentation: "card" }} />
      <VariantResultsScreen jobIds={parseJobIds(jobs)} />
    </>
  );
}
