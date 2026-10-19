/**
 * Batch progress — the N variant reels a single "Create N variants" request
 * fanned out (`GET /api/v1/batches/{batch_id}`). Every variant shares one
 * `batch_id`; this screen watches them together, polling until all settle, and
 * taps through to each variant's full reel/job detail.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  Stack,
  useFocusEffect,
  useLocalSearchParams,
  useRouter,
} from "expo-router";

import { ApiError, isAbortError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, kicker, radius, spacing, typeScale } from "@/src/shared/theme";
import {
  batchJobPosterUrl,
  batchJobResultUrl,
  getBatch,
  summarizeBatch,
  type BatchJobData,
} from "@/lib/tasks";
import {
  JobState,
  isFailedState,
  isTerminalState,
  type JobStateValue,
} from "@/lib/types";

const POLL_INTERVAL_MS = 3000;

function isCompleteState(state: JobStateValue): boolean {
  return state === JobState.Complete;
}

const BATCH_PREDICATES = {
  isComplete: isCompleteState,
  isFailed: isFailedState,
  isTerminal: isTerminalState,
} as const;

function variantStatus(state: JobStateValue): { label: string; color: string } {
  if (isCompleteState(state)) return { label: "Complete", color: "#7CC39B" };
  if (isFailedState(state)) return { label: "Failed", color: "#E0847F" };
  return { label: "Processing", color: "#E6C76A" };
}

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

function clampProgress(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function BatchProgressScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;
  const params = useLocalSearchParams<{ batchId?: string | string[] }>();
  const batchId = firstParam(params.batchId).trim();

  const [jobs, setJobs] = useState<BatchJobData[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!batchId) {
        setError("Missing batch id.");
        return;
      }
      try {
        const data = await getBatch(batchId, { token, signal });
        setJobs(data.jobs ?? []);
        setError(null);
      } catch (err) {
        if (isAbortError(err)) return;
        setError(describe(err, "Failed to load this batch."));
      }
    },
    [batchId, token],
  );

  useFocusEffect(
    useCallback(() => {
      let active = true;
      const controller = new AbortController();
      setLoading(true);
      void load(controller.signal).finally(() => {
        if (active) setLoading(false);
      });
      return () => {
        active = false;
        controller.abort();
      };
    }, [load]),
  );

  const summary = useMemo(
    () => summarizeBatch(jobs, BATCH_PREDICATES),
    [jobs],
  );

  // Poll while any variant is still processing.
  useFocusEffect(
    useCallback(() => {
      if (summary.settled || jobs.length === 0) return undefined;
      const controller = new AbortController();
      const tick = () => {
        if (inFlight.current) return;
        inFlight.current = true;
        void load(controller.signal).finally(() => {
          inFlight.current = false;
        });
      };
      const timer = setInterval(tick, POLL_INTERVAL_MS);
      return () => {
        clearInterval(timer);
        controller.abort();
      };
    }, [summary.settled, jobs.length, load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  if (loading) {
    return (
      <View style={[styles.container, styles.center]}>
        <Stack.Screen options={{ title: "Batch" }} />
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  const header = (
    <View style={styles.headerBlock}>
      <Text style={styles.kicker}>REEL BATCH / VARIANTS</Text>
      <Text style={styles.title}>
        {summary.total} variant{summary.total === 1 ? "" : "s"}
      </Text>
      <Text style={styles.batchId} numberOfLines={1}>
        {batchId}
      </Text>

      <View style={styles.progressTrack}>
        <View
          style={[styles.progressFill, { width: `${summary.percentage}%` }]}
        />
      </View>

      <View style={styles.statRow}>
        <Stat label="Complete" value={summary.complete} color="#7CC39B" />
        <Stat label="Processing" value={summary.processing} color="#E6C76A" />
        <Stat label="Failed" value={summary.failed} color="#E0847F" />
      </View>

      <Text style={styles.subtitle}>
        {summary.settled
          ? "All variants finished."
          : `${summary.percentage}% · watching for updates…`}
      </Text>

      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );

  return (
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      data={jobs}
      keyExtractor={(item) => item.job_id}
      ListHeaderComponent={header}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.accent}
        />
      }
      ListEmptyComponent={
        <View style={styles.emptyBlock}>
          <Text style={styles.empty}>
            {error ?? "This batch has no variants."}
          </Text>
        </View>
      }
      renderItem={({ item, index }) => (
        <VariantRow
          job={item}
          index={index}
          onPress={() => router.push(`/job/${item.job_id}`)}
        />
      )}
    />
  );
}

interface StatProps {
  label: string;
  value: number;
  color: string;
}

function Stat({ label, value, color }: StatProps) {
  return (
    <View style={styles.stat}>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

interface VariantRowProps {
  job: BatchJobData;
  index: number;
  onPress: () => void;
}

function VariantRow({ job, index, onPress }: VariantRowProps) {
  const status = variantStatus(job.state);
  const pct = clampProgress(job.progress);
  const poster = batchJobPosterUrl(job);
  const done = !!batchJobResultUrl(job);
  return (
    <Pressable
      style={styles.card}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`Variant ${index + 1}, ${status.label}`}
    >
      {poster ? (
        <Image
          source={{ uri: poster }}
          style={styles.thumb}
          accessibilityLabel={`Poster for variant ${index + 1}`}
        />
      ) : (
        <View style={[styles.thumb, styles.thumbPlaceholder]}>
          <Text style={styles.thumbIndex}>{index + 1}</Text>
        </View>
      )}
      <View style={styles.cardBody}>
        <View style={styles.cardHeader}>
          <Text style={styles.variantLabel}>Variant {index + 1}</Text>
          <Text style={[styles.badge, { color: status.color }]}>
            {status.label}
          </Text>
        </View>
        <Text style={styles.jobId} numberOfLines={1}>
          {job.job_id}
        </Text>
        <View style={styles.rowProgressTrack}>
          <View
            style={[
              styles.rowProgressFill,
              { width: `${pct}%`, backgroundColor: status.color },
            ]}
          />
        </View>
        <Text style={styles.meta}>
          {pct}%{done ? " · ready to review" : ""}
        </Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.xl, gap: spacing.md, flexGrow: 1 },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
  },
  headerBlock: { gap: spacing.sm, marginBottom: spacing.xs },
  kicker: { ...kicker },
  title: {
    color: colors.textPrimary,
    fontSize: typeScale.title,
    fontWeight: "800",
  },
  batchId: { color: colors.textFaint, fontSize: typeScale.micro },
  subtitle: { color: colors.textSecondary, fontSize: typeScale.body },
  progressTrack: {
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.surfaceMuted,
    overflow: "hidden",
    marginTop: spacing.sm,
  },
  progressFill: { height: 8, backgroundColor: colors.accent },
  statRow: {
    flexDirection: "row",
    gap: spacing.md,
    marginTop: spacing.sm,
  },
  stat: {
    flex: 1,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: "center",
    gap: 2,
  },
  statValue: { fontSize: typeScale.heading, fontWeight: "800" },
  statLabel: { color: colors.textFaint, fontSize: typeScale.micro },
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    flexDirection: "row",
    gap: spacing.md,
    alignItems: "center",
  },
  thumb: { width: 54, height: 96, borderRadius: radius.sm },
  thumbPlaceholder: {
    backgroundColor: colors.surfaceMuted,
    alignItems: "center",
    justifyContent: "center",
  },
  thumbIndex: {
    color: colors.textSecondary,
    fontSize: typeScale.heading,
    fontWeight: "800",
  },
  cardBody: { flex: 1, gap: spacing.sm },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: spacing.md,
  },
  variantLabel: {
    color: colors.textPrimary,
    fontSize: typeScale.body,
    fontWeight: "700",
  },
  badge: { fontSize: typeScale.caption, fontWeight: "700" },
  jobId: { color: colors.textFaint, fontSize: typeScale.micro },
  rowProgressTrack: {
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.surfaceMuted,
    overflow: "hidden",
  },
  rowProgressFill: { height: 6 },
  meta: { color: colors.textFaint, fontSize: typeScale.micro },
  emptyBlock: {
    alignItems: "center",
    justifyContent: "center",
    paddingTop: 60,
  },
  empty: {
    color: colors.textFaint,
    fontSize: typeScale.body,
    textAlign: "center",
    paddingHorizontal: spacing.xl,
  },
  error: { color: colors.danger, fontSize: typeScale.caption },
});
