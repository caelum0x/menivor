/**
 * Route: /reels/[id] — legacy alias for the canonical reel detail at
 * /job/[id], which carries every panel (export, rerun, dub, schedule, cover,
 * b-roll, captions), rename / archive / cancel / delete, and, for a reel that
 * was one of a one-flow run's hook variants, the "Which hook won?" link to
 * its winner loop (/insights/winners/[batchId]).
 */
import { Redirect, useLocalSearchParams } from "expo-router";

export default function ReelDetailRedirect() {
  const { id } = useLocalSearchParams<{ id: string }>();
  if (!id) return <Redirect href="/(tabs)/jobs" />;
  return <Redirect href={`/job/${encodeURIComponent(id)}`} />;
}
