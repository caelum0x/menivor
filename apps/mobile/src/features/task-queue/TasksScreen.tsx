/**
 * Global async-task queue — a live list of every background task the backend is
 * running for the caller (`GET /api/v1/tasks`). Auto-refreshes on focus, offers
 * pull-to-refresh, filters by lifecycle status, polls while any task is still
 * active, and taps through to the per-task detail screen.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useFocusEffect, useRouter } from "expo-router";

import { ApiError, isAbortError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, kicker, radius, spacing, typeScale } from "@/src/shared/theme";
import {
  TASK_STATUS_FILTERS,
  isActiveTaskStatus,
  listTasks,
  summarizeTasksByStatus,
  taskMatchesFilter,
  taskPercentage,
  taskProgressCounter,
  taskStatusColor,
  taskStatusLabel,
  taskTypeLabel,
  type Task,
  type TaskStatusFilterId,
} from "@/lib/tasks";

const POLL_INTERVAL_MS = 3000;

function describe(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Failed to load the task queue.";
}

export function TasksScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<TaskStatusFilterId>("all");
  const inFlight = useRef(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const next = await listTasks({ limit: 200 }, { token, signal });
        setTasks(next);
        setError(null);
      } catch (err) {
        if (isAbortError(err)) return;
        setError(describe(err));
      }
    },
    [token],
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

  // Poll while at least one task is still active; stop once the queue settles.
  const hasActive = useMemo(
    () => tasks.some((task) => isActiveTaskStatus(task.status)),
    [tasks],
  );

  useFocusEffect(
    useCallback(() => {
      if (!hasActive) return undefined;
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
    }, [hasActive, load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const counts = useMemo(() => summarizeTasksByStatus(tasks), [tasks]);
  const visible = useMemo(
    () => tasks.filter((task) => taskMatchesFilter(task, filter)),
    [tasks, filter],
  );

  if (loading) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.accent} size="large" />
        <Text style={styles.meta}>Loading the task queue…</Text>
      </View>
    );
  }

  const header = (
    <View style={styles.headerBlock}>
      <Text style={styles.kicker}>BACKGROUND / TASK QUEUE</Text>
      <Text style={styles.title}>Tasks</Text>
      <Text style={styles.subtitle}>
        {counts.active > 0
          ? `${counts.active} running now · ${counts.all} total`
          : `${counts.all} task${counts.all === 1 ? "" : "s"} · all settled`}
      </Text>
      <View style={styles.filterRow}>
        {TASK_STATUS_FILTERS.map((chip) => {
          const active = chip.id === filter;
          const count = counts[chip.id];
          return (
            <Pressable
              key={chip.id}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => setFilter(chip.id)}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>
                {chip.label}
                {count > 0 ? ` ${count}` : ""}
              </Text>
            </Pressable>
          );
        })}
      </View>
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );

  return (
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      data={visible}
      keyExtractor={(item) => item.task_id}
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
            {error
              ? error
              : filter === "all"
                ? "No background tasks yet. Tasks appear here while a generation runs."
                : "No tasks match this filter."}
          </Text>
        </View>
      }
      renderItem={({ item }) => (
        <TaskRow
          task={item}
          onPress={() => router.push(`/jobs/reels/tasks/${item.task_id}`)}
        />
      )}
    />
  );
}

interface TaskRowProps {
  task: Task;
  onPress: () => void;
}

function TaskRow({ task, onPress }: TaskRowProps) {
  const color = taskStatusColor(task.status);
  const pct = taskPercentage(task);
  const counter = taskProgressCounter(task);
  return (
    <Pressable
      style={styles.card}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`Task ${task.task_id}, ${taskStatusLabel(task.status)}`}
    >
      <View style={styles.cardHeader}>
        <Text style={styles.cardTitle} numberOfLines={1}>
          {taskTypeLabel(task.task_type)}
        </Text>
        <Text style={[styles.badge, { color }]}>
          {taskStatusLabel(task.status)}
        </Text>
      </View>
      <Text style={styles.taskId} numberOfLines={1}>
        {task.task_id}
      </Text>
      <View style={styles.progressTrack}>
        <View
          style={[
            styles.progressFill,
            { width: `${pct}%`, backgroundColor: color },
          ]}
        />
      </View>
      <View style={styles.cardFooter}>
        <Text style={styles.meta}>{pct}%</Text>
        {counter ? <Text style={styles.meta}>{counter}</Text> : null}
        {task.progress?.message ? (
          <Text style={styles.metaMessage} numberOfLines={1}>
            {task.progress.message}
          </Text>
        ) : null}
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
  subtitle: { color: colors.textSecondary, fontSize: typeScale.body },
  filterRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  chip: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  chipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { color: colors.textSecondary, fontSize: typeScale.caption },
  chipTextActive: { color: colors.onAccent, fontWeight: "700" },
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.sm,
  },
  cardHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  cardTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.body,
    fontWeight: "700",
    flex: 1,
  },
  badge: { fontSize: typeScale.caption, fontWeight: "700" },
  taskId: { color: colors.textFaint, fontSize: typeScale.micro },
  progressTrack: {
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.surfaceMuted,
    overflow: "hidden",
  },
  progressFill: { height: 6 },
  cardFooter: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  meta: { color: colors.textFaint, fontSize: typeScale.micro },
  metaMessage: { color: colors.textSecondary, fontSize: typeScale.micro, flex: 1 },
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
