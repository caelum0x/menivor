/**
 * Render screen — submit a prompt to the RunPod render backend, then poll the
 * job (advancing it) until it reaches a terminal state. Below the composer the
 * caller's full render history (GET /render/jobs) is listed with playable
 * outputs, so a render is never lost when the screen is left.
 */

import * as React from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useFocusEffect, useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { RenderOutputs } from "@/components/render/RenderOutputs";
import { useSession } from "@/src/shared/auth";
import {
  advanceRenderJob,
  cancelRenderJob,
  createRenderJob,
  isTerminalState,
  listRenderJobs,
  renderStateColor,
  renderStateLabel,
  type RenderJob,
} from "@/lib/render";
import { GenerationErrorNotice } from "@/components/billing/GenerationErrorNotice";

const HISTORY_LIMIT = 50;

function renderDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

const MAX_COST_MICROS = 100000;

export default function RenderScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;
  const [prompt, setPrompt] = React.useState("");
  const [job, setJob] = React.useState<RenderJob | null>(null);
  const [starting, setStarting] = React.useState(false);
  const [polling, setPolling] = React.useState(false);
  const [cancelling, setCancelling] = React.useState(false);
  const [error, setError] = React.useState("");
  const [history, setHistory] = React.useState<RenderJob[]>([]);
  const [historyLoading, setHistoryLoading] = React.useState(true);
  const [historyError, setHistoryError] = React.useState("");

  const loadHistory = React.useCallback(async () => {
    setHistoryError("");
    try {
      setHistory(await listRenderJobs({ limit: HISTORY_LIMIT }, { token }));
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : "Failed to load render history.");
    } finally {
      setHistoryLoading(false);
    }
  }, [token]);

  useFocusEffect(
    React.useCallback(() => {
      void loadHistory();
    }, [loadHistory]),
  );

  // Keep the history row for the active job in sync with the live snapshot.
  React.useEffect(() => {
    if (!job) return;
    setHistory((prev) => {
      const exists = prev.some((row) => row.id === job.id);
      return exists
        ? prev.map((row) => (row.id === job.id ? { ...row, ...job } : row))
        : [job, ...prev];
    });
  }, [job]);

  const startRender = React.useCallback(async () => {
    if (!prompt.trim() || starting) return;
    setStarting(true);
    setError("");
    try {
      const created = await createRenderJob(
        {
          backend: "runpod",
          spec: { prompt: prompt.trim() },
          max_cost_micros: MAX_COST_MICROS,
        },
        { token },
      );
      setJob(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start render.");
    } finally {
      setStarting(false);
    }
  }, [prompt, starting, token]);

  const poll = React.useCallback(async () => {
    if (!job || polling || isTerminalState(job.state)) return;
    setPolling(true);
    setError("");
    try {
      let current = job;
      while (!isTerminalState(current.state)) {
        current = await advanceRenderJob(current.id, { token });
        setJob(current);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to advance render.");
    } finally {
      setPolling(false);
    }
  }, [job, polling, token]);

  const cancel = React.useCallback(async () => {
    if (!job || cancelling || isTerminalState(job.state)) return;
    setCancelling(true);
    setError("");
    try {
      const cancelled = await cancelRenderJob(job.id, { token });
      setJob(cancelled);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel render.");
    } finally {
      setCancelling(false);
    }
  }, [job, cancelling, token]);

  const terminal = job ? isTerminalState(job.state) : false;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Describe the render you want. It runs on the RunPod backend — start it, then poll until
        it finishes.
      </Text>

      <Text style={styles.label}>Prompt</Text>
      <TextInput
        style={styles.input}
        value={prompt}
        onChangeText={setPrompt}
        placeholder="A neon city flythrough at night…"
        placeholderTextColor={colors.muted}
        multiline
        editable={!starting}
      />

      <Pressable
        style={[styles.button, (!prompt.trim() || starting) && styles.buttonDisabled]}
        onPress={startRender}
        disabled={!prompt.trim() || starting}
      >
        {starting ? (
          <ActivityIndicator color={colors.bg} />
        ) : (
          <Text style={styles.buttonText}>Start render</Text>
        )}
      </Pressable>

      {job ? (
        <View style={styles.card}>
          <Text style={styles.name}>Job {job.id}</Text>
          <Text style={styles.meta}>
            {job.backend} · {job.state} · {Math.round(job.progress * 100)}%
          </Text>
          <Text style={styles.meta}>Cost: {job.cost_micros} micros</Text>
          <RenderOutputs job={job} />
          {job.error ? <Text style={styles.error}>{job.error}</Text> : null}

          <Pressable
            style={styles.detailLink}
            onPress={() =>
              router.push(`/reels/render-job?id=${encodeURIComponent(job.id)}`)
            }
            accessibilityRole="button"
            accessibilityLabel="Open the shareable render job page"
          >
            <Text style={styles.detailLinkText}>Open job page</Text>
          </Pressable>

          <Pressable
            style={[styles.button, styles.pollButton, (polling || terminal) && styles.buttonDisabled]}
            onPress={poll}
            disabled={polling || terminal}
          >
            {polling ? (
              <ActivityIndicator color={colors.bg} />
            ) : (
              <Text style={styles.buttonText}>{terminal ? "Done" : "Poll"}</Text>
            )}
          </Pressable>

          {!terminal ? (
            <>
              <Pressable
                style={[styles.cancelButton, cancelling && styles.buttonDisabled]}
                onPress={cancel}
                disabled={cancelling}
                accessibilityRole="button"
                accessibilityLabel="Cancel this render and refund the hold"
              >
                {cancelling ? (
                  <ActivityIndicator color={colors.error} />
                ) : (
                  <Text style={styles.cancelText}>Cancel &amp; refund</Text>
                )}
              </Pressable>
              <Text style={styles.cancelHint}>
                Stops the job and releases the held credits — you are billed only on success.
              </Text>
            </>
          ) : null}
        </View>
      ) : null}

      <GenerationErrorNotice message={error} style={styles.error} />

      <Text style={styles.historyHeading}>Render history</Text>
      {historyLoading ? (
        <ActivityIndicator color={colors.primary} style={styles.historySpinner} />
      ) : historyError ? (
        <View>
          <Text style={styles.error}>{historyError}</Text>
          <Pressable style={styles.detailLink} onPress={() => void loadHistory()} accessibilityRole="button">
            <Text style={styles.detailLinkText}>Retry</Text>
          </Pressable>
        </View>
      ) : history.length === 0 ? (
        <Text style={styles.meta}>No renders yet. Start one above.</Text>
      ) : (
        history
          .filter((row) => row.id !== job?.id)
          .map((row) => (
            <Pressable
              key={row.id}
              style={styles.card}
              onPress={() => router.push(`/reels/render-job?id=${encodeURIComponent(row.id)}`)}
              accessibilityRole="button"
              accessibilityLabel={`Open render ${row.label || row.id}`}
            >
              <View style={styles.historyRow}>
                <Text style={styles.name} numberOfLines={1}>
                  {row.label || row.id}
                </Text>
                <Text style={[styles.historyState, { color: renderStateColor(row.state) }]}>
                  {renderStateLabel(row.state)}
                </Text>
              </View>
              <Text style={styles.meta}>
                {[row.source && row.source !== "render" ? row.source : row.backend, renderDate(row.created_at)]
                  .filter(Boolean)
                  .join(" · ")}
              </Text>
              {row.state === "COMPLETED" ? <RenderOutputs job={row} compact /> : null}
              {row.error ? <Text style={styles.error}>{row.error}</Text> : null}
            </Pressable>
          ))
      )}
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  label: { color: colors.textPrimary, fontSize: 13, fontWeight: "600", marginBottom: 6 },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    color: colors.textPrimary,
    fontSize: 14,
    minHeight: 88,
    textAlignVertical: "top",
    marginBottom: 12,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  pollButton: { marginTop: 12 },
  detailLink: { marginTop: 12, alignSelf: "flex-start" },
  detailLinkText: { color: colors.primary, fontSize: 13, fontWeight: "600" },
  cancelButton: {
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 12,
  },
  cancelText: { color: colors.error, fontSize: 15, fontWeight: "600" },
  cancelHint: { color: colors.muted, fontSize: 12, marginTop: 8 },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.bg, fontSize: 15, fontWeight: "600" },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginTop: 16,
  },
  name: { color: colors.textPrimary, fontSize: 16, fontWeight: "600", marginBottom: 4 },
  desc: { color: colors.textSecondary, fontSize: 13, marginTop: 8 },
  meta: { color: colors.muted, fontSize: 12, marginBottom: 2 },
  error: { color: colors.error, fontSize: 14, marginTop: 8 },
  historyHeading: { color: colors.textPrimary, fontSize: 16, fontWeight: "700", marginTop: 28 },
  historySpinner: { marginTop: 12 },
  historyRow: { flexDirection: "row", justifyContent: "space-between", gap: 8 },
  historyState: { fontSize: 13, fontWeight: "700" },
  spacer: { height: 24 },
});
