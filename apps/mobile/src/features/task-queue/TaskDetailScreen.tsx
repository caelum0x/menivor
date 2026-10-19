/**
 * Per-task detail — the full lifecycle of one async task
 * (`GET /api/v1/tasks/{task_id}`). Polls while the task is active, renders its
 * progress / message / timestamps / error, exposes the raw result payload when
 * complete, and lets the owner cancel a still-running task (with confirmation)
 * via `DELETE /api/v1/tasks/{task_id}`.
 */

import { useCallback, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
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
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";
import {
  cancelTask,
  getTask,
  isActiveTaskStatus,
  taskIsCancelable,
  taskPercentage,
  taskProgressCounter,
  taskStatusColor,
  taskStatusLabel,
  taskTypeLabel,
  formatTaskTime,
  type Task,
} from "@/lib/tasks";

const POLL_INTERVAL_MS = 3000;

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

/** Read the first value of a route param that may arrive as string | string[]. */
function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

function safeStringify(value: unknown): string {
  try {
    if (typeof value === "string") return value;
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function TaskDetailScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;
  const params = useLocalSearchParams<{ id?: string | string[] }>();
  const taskId = firstParam(params.id).trim();

  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [canceling, setCanceling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!taskId) {
        setError("Missing task id.");
        return;
      }
      try {
        const next = await getTask(taskId, { token, signal });
        setTask(next);
        setError(null);
      } catch (err) {
        if (isAbortError(err)) return;
        setError(describe(err, "Failed to load this task."));
      }
    },
    [taskId, token],
  );

  // Initial load (and reload on focus).
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

  const active = task ? isActiveTaskStatus(task.status) : false;

  // Poll while the task is still in flight; stop once it settles.
  useFocusEffect(
    useCallback(() => {
      if (!active) return undefined;
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
    }, [active, load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const doCancel = useCallback(async () => {
    if (!taskId) return;
    setCanceling(true);
    setError(null);
    try {
      const result = await cancelTask(taskId, { token });
      Alert.alert("Task cancelled", result.message || "The task was cancelled.");
      await load();
    } catch (err) {
      setError(describe(err, "Couldn't cancel this task."));
    } finally {
      setCanceling(false);
    }
  }, [taskId, token, load]);

  const onCancelPress = useCallback(() => {
    Alert.alert(
      "Cancel this task?",
      "The running work stops and cannot be resumed. You can start a new one later.",
      [
        { text: "Keep running", style: "cancel" },
        {
          text: "Cancel task",
          style: "destructive",
          onPress: () => void doCancel(),
        },
      ],
    );
  }, [doCancel]);

  if (loading) {
    return (
      <View style={[styles.container, styles.center]}>
        <Stack.Screen options={{ title: "Task" }} />
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  if (!task) {
    return (
      <View style={[styles.container, styles.center]}>
        <Stack.Screen options={{ title: "Task" }} />
        <Text style={styles.error}>{error ?? "Task not found."}</Text>
        <Pressable style={styles.secondary} onPress={() => router.back()}>
          <Text style={styles.secondaryText}>Go back</Text>
        </Pressable>
      </View>
    );
  }

  const color = taskStatusColor(task.status);
  const pct = taskPercentage(task);
  const counter = taskProgressCounter(task);
  const resultText = task.result != null ? safeStringify(task.result) : null;
  const paramsText =
    task.request_params && Object.keys(task.request_params).length > 0
      ? safeStringify(task.request_params)
      : null;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.accent}
        />
      }
    >
      <Stack.Screen options={{ title: "Task" }} />

      <View style={styles.headerRow}>
        <Text style={styles.title}>{taskTypeLabel(task.task_type)}</Text>
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
      <View style={styles.progressMeta}>
        <Text style={styles.metaStrong}>{pct}%</Text>
        {counter ? <Text style={styles.meta}>{counter}</Text> : null}
        {active ? (
          <View style={styles.liveDot}>
            <ActivityIndicator color={colors.accent} size="small" />
            <Text style={styles.meta}>Live</Text>
          </View>
        ) : null}
      </View>
      {task.progress?.message ? (
        <Text style={styles.message}>{task.progress.message}</Text>
      ) : null}

      <View style={styles.timeline}>
        <TimeRow label="Created" value={formatTaskTime(task.created_at)} />
        <TimeRow label="Started" value={formatTaskTime(task.started_at)} />
        <TimeRow label="Completed" value={formatTaskTime(task.completed_at)} />
      </View>

      {task.error ? (
        <View style={styles.errorCard}>
          <Text style={styles.errorTitle}>Error</Text>
          <Text style={styles.errorBody}>{task.error}</Text>
        </View>
      ) : null}

      {resultText ? (
        <View style={styles.block}>
          <Text style={styles.blockTitle}>Result</Text>
          <View style={styles.codeCard}>
            <Text style={styles.code}>{resultText}</Text>
          </View>
        </View>
      ) : null}

      {paramsText ? (
        <View style={styles.block}>
          <Text style={styles.blockTitle}>Request parameters</Text>
          <View style={styles.codeCard}>
            <Text style={styles.code}>{paramsText}</Text>
          </View>
        </View>
      ) : null}

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {taskIsCancelable(task) ? (
        <Pressable
          style={[styles.danger, canceling && styles.disabled]}
          onPress={onCancelPress}
          disabled={canceling}
          accessibilityRole="button"
          accessibilityLabel="Cancel this task"
        >
          {canceling ? (
            <ActivityIndicator color={colors.textPrimary} />
          ) : (
            <Text style={styles.dangerText}>Cancel task</Text>
          )}
        </Pressable>
      ) : null}

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

interface TimeRowProps {
  label: string;
  value: string;
}

function TimeRow({ label, value }: TimeRowProps) {
  return (
    <View style={styles.timeRow}>
      <Text style={styles.timeLabel}>{label}</Text>
      <Text style={styles.timeValue}>{value || "—"}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.xl, gap: spacing.md },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
    padding: spacing.xl,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  title: {
    color: colors.textPrimary,
    fontSize: typeScale.heading,
    fontWeight: "800",
    flex: 1,
  },
  badge: { fontSize: typeScale.body, fontWeight: "700" },
  taskId: { color: colors.textFaint, fontSize: typeScale.micro },
  progressTrack: {
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.surfaceMuted,
    overflow: "hidden",
    marginTop: spacing.sm,
  },
  progressFill: { height: 8 },
  progressMeta: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  liveDot: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  metaStrong: {
    color: colors.textPrimary,
    fontSize: typeScale.body,
    fontWeight: "700",
  },
  meta: { color: colors.textFaint, fontSize: typeScale.caption },
  message: { color: colors.textSecondary, fontSize: typeScale.body },
  timeline: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.sm,
  },
  timeRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  timeLabel: { color: colors.textSecondary, fontSize: typeScale.caption },
  timeValue: { color: colors.textPrimary, fontSize: typeScale.caption },
  block: { gap: spacing.sm },
  blockTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: "700",
  },
  codeCard: {
    backgroundColor: colors.surfaceAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  code: {
    color: colors.textSecondary,
    fontSize: typeScale.micro,
    fontFamily: "Courier",
  },
  errorCard: {
    backgroundColor: colors.surface,
    borderColor: colors.danger,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.xs,
  },
  errorTitle: {
    color: colors.danger,
    fontWeight: "700",
    fontSize: typeScale.caption,
  },
  errorBody: { color: colors.textSecondary, fontSize: typeScale.caption },
  danger: {
    borderColor: colors.danger,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: "center",
    marginTop: spacing.sm,
  },
  dangerText: {
    color: colors.danger,
    fontSize: typeScale.body,
    fontWeight: "700",
  },
  disabled: { opacity: 0.5 },
  secondary: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.xl,
  },
  secondaryText: { color: colors.textSecondary, fontWeight: "600" },
  error: { color: colors.danger, fontSize: typeScale.caption },
});
