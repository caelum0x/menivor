/** Route: /insights/winners/[batchId] — one project's winner loop. */
import { Redirect, Stack, useLocalSearchParams } from "expo-router";

import { LoopDetailScreen } from "@/src/features/winner-loop";

/** Batch ids are uuid hex (or short server ids); anything else never reaches the API. */
const BATCH_ID_PATTERN = /^[A-Za-z0-9_-]{6,64}$/;

export default function WinnerLoopRoute() {
  const { batchId } = useLocalSearchParams<{ batchId?: string }>();
  const id = typeof batchId === "string" ? batchId.trim() : "";
  if (!BATCH_ID_PATTERN.test(id)) return <Redirect href={"/insights/winners" as never} />;
  return (
    <>
      <Stack.Screen options={{ title: "Winner loop", presentation: "card" }} />
      <LoopDetailScreen key={id} batchId={id} />
    </>
  );
}
