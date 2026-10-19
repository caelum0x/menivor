/**
 * NAV MANIFEST
 * ------------
 * Route:   /reels/render-job          (expo-router auto-registers this file)
 * Params:  ?id=<renderJobId>          the RunPod/render-engine job id (required)
 * Push:    router.push(`/reels/render-job?id=${encodeURIComponent(renderJob.id)}`)
 * Purpose: A shareable, deep detail + lifecycle surface for a single render-engine
 *          job — inspect status, poll it to a terminal state, and CANCEL an
 *          in-flight job (full wallet refund) with confirmation.
 *
 * WHY THIS SCREEN AND NOT THE REEL JobDetailScreen
 * ------------------------------------------------
 * The task asked whether the render-cancel endpoint should be wired into the
 * reel/variant JobDetailScreen. Confirming against the backend job lifecycle:
 *   - Reel/variant jobs (reelforge Celery pipeline, `Job` type) expose only the
 *     states Failed(-1) / Complete(1) / Processing(4) — there is NO cancelled
 *     state — and the reels router (`/jobs`) exposes retry/rerun/dub/broll but
 *     NO `/jobs/{id}/cancel`.
 *   - `/render/jobs/{id}/cancel` operates on a SEPARATE store (RenderJobRepository)
 *     keyed by render-engine ids. A reel `job_id` is not a render-job id, so
 *     wiring render-cancel into the reel screen would 404 ("render job not found")
 *     on every reel. Cancel is intentionally limited to render/media jobs.
 * So the render-cancel endpoint is wired here, on its correct id space, giving it
 * a shareable per-job detail home (previously it only lived inline in app/render).
 */

import * as React from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useLocalSearchParams } from "expo-router";

import { colors } from "@/components/me/theme";
import { RenderOutputs } from "@/components/render/RenderOutputs";
import { useSession } from "@/src/shared/auth";
import {
  advanceRenderJob,
  cancelRenderJob,
  getRenderJob,
  isCancelableState,
  isTerminalState,
  renderStateColor,
  renderStateLabel,
  type RenderJob,
} from "@/lib/render";

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export default function RenderJobScreen() {
  const params = useLocalSearchParams<{ id?: string | string[] }>();
  const jobId = React.useMemo(() => {
    const raw = Array.isArray(params.id) ? params.id[0] : params.id;
    return (raw ?? "").trim();
  }, [params.id]);

  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [job, setJob] = React.useState<RenderJob | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [advancing, setAdvancing] = React.useState(false);
  const [cancelling, setCancelling] = React.useState(false);

  const load = React.useCallback(async () => {
    if (!jobId) return;
    setLoading(true);
    setError(null);
    try {
      const fetched = await getRenderJob(jobId, { token });
      setJob(fetched);
    } catch (err) {
      setError(errorMessage(err, "Failed to load this render job."));
    } finally {
      setLoading(false);
    }
  }, [jobId, token]);

  // Load server truth whenever the screen focuses or the id changes.
  React.useEffect(() => {
    let active = true;
    if (!jobId) {
      setJob(null);
      return () => {
        active = false;
      };
    }
    setLoading(true);
    setError(null);
    getRenderJob(jobId, { token })
      .then((fetched) => {
        if (active) setJob(fetched);
      })
      .catch((err: unknown) => {
        if (active) setError(errorMessage(err, "Failed to load this render job."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [jobId, token]);

  const advance = React.useCallback(async () => {
    if (!job || advancing || cancelling || isTerminalState(job.state)) return;
    setAdvancing(true);
    setError(null);
    try {
      let current = job;
      while (!isTerminalState(current.state)) {
        current = await advanceRenderJob(current.id, { token });
        setJob(current);
      }
    } catch (err) {
      setError(errorMessage(err, "Failed to advance this render job."));
    } finally {
      setAdvancing(false);
    }
  }, [job, advancing, cancelling, token]);

  const runCancel = React.useCallback(async () => {
    if (!job || cancelling) return;
    setCancelling(true);
    setError(null);
    try {
      const cancelled = await cancelRenderJob(job.id, { token });
      setJob(cancelled);
    } catch (err) {
      setError(errorMessage(err, "Failed to cancel this render job."));
    } finally {
      setCancelling(false);
    }
  }, [job, cancelling, token]);

  const confirmCancel = React.useCallback(() => {
    if (!job || cancelling || !isCancelableState(job.state)) return;
    Alert.alert(
      "Cancel this render?",
      "The job stops and its held credits are released in full. You are billed only on success. This cannot be undone.",
      [
        { text: "Keep rendering", style: "cancel" },
        {
          text: "Cancel & refund",
          style: "destructive",
          onPress: () => {
            void runCancel();
          },
        },
      ],
    );
  }, [job, cancelling, runCancel]);

  const stateColor = job ? renderStateColor(job.state) : colors.muted;
  const terminal = job ? isTerminalState(job.state) : false;
  const cancelable = job ? isCancelableState(job.state) : false;
  const progressPct = job ? Math.max(0, Math.min(100, Math.round(job.progress * 100))) : 0;
  const busy = advancing || cancelling;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: "Render job" }} />

      {!jobId ? (
        <View style={styles.stateBox}>
          <Text style={styles.stateTitle}>No render job selected</Text>
          <Text style={styles.stateBody}>
            Open this screen with a render job id, e.g. /reels/render-job?id=abc123.
          </Text>
        </View>
      ) : loading && !job ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.primary} size="large" />
          <Text style={styles.loadingText}>Loading render job {jobId}</Text>
        </View>
      ) : error && !job ? (
        <View style={styles.stateBox}>
          <Text style={styles.errorTitle}>Render job unavailable</Text>
          <Text style={styles.stateBody}>{error}</Text>
          <Pressable
            style={styles.retry}
            onPress={() => void load()}
            accessibilityRole="button"
            accessibilityLabel={`Retry loading render job ${jobId}`}
          >
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      ) : job ? (
        <>
          <View style={styles.headerRow}>
            <Text style={styles.jobId} numberOfLines={1}>
              {job.id}
            </Text>
            <Text style={[styles.badge, { color: stateColor }]}>
              {renderStateLabel(job.state)}
            </Text>
          </View>

          <Text style={styles.meta}>Backend: {job.backend}</Text>

          <View style={styles.progressTrack}>
            <View
              style={[styles.progressFill, { width: `${progressPct}%`, backgroundColor: stateColor }]}
            />
          </View>
          <Text style={styles.meta}>{progressPct}%</Text>

          <Text style={styles.meta}>
            Cost held: {job.cost_micros.toLocaleString()} micros
          </Text>

          {job.output_refs.length > 0 || job.state === "COMPLETED" ? (
            <>
              <Text style={styles.h2}>Outputs</Text>
              <RenderOutputs job={job} />
            </>
          ) : null}

          {job.error ? (
            <View style={styles.failBox}>
              <Text style={styles.failText}>{job.error}</Text>
            </View>
          ) : null}

          {!terminal ? (
            <>
              <Pressable
                style={[styles.button, (busy || terminal) && styles.disabled]}
                onPress={() => void advance()}
                disabled={busy || terminal}
                accessibilityRole="button"
                accessibilityLabel="Poll this render job until it finishes"
                accessibilityState={{ disabled: busy || terminal, busy: advancing }}
              >
                {advancing ? (
                  <ActivityIndicator color={colors.bg} />
                ) : (
                  <Text style={styles.buttonText}>Poll until done</Text>
                )}
              </Pressable>

              <Pressable
                style={[styles.cancelButton, (cancelling || !cancelable) && styles.disabled]}
                onPress={confirmCancel}
                disabled={cancelling || !cancelable}
                accessibilityRole="button"
                accessibilityLabel="Cancel this render and refund the hold"
                accessibilityState={{ disabled: cancelling || !cancelable, busy: cancelling }}
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
          ) : (
            <Pressable
              style={[styles.button, loading && styles.disabled]}
              onPress={() => void load()}
              disabled={loading}
              accessibilityRole="button"
              accessibilityLabel="Refresh this render job"
              accessibilityState={{ disabled: loading, busy: loading }}
            >
              {loading ? (
                <ActivityIndicator color={colors.bg} />
              ) : (
                <Text style={styles.buttonText}>Refresh</Text>
              )}
            </Pressable>
          )}

          {error ? <Text style={styles.inlineError}>{error}</Text> : null}
        </>
      ) : null}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, gap: 10 },
  center: { paddingTop: 80, alignItems: "center" },
  loadingText: { color: colors.muted, fontSize: 12, marginTop: 12 },
  stateBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 9,
    marginTop: 40,
  },
  stateTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "800" },
  errorTitle: { color: colors.error, fontSize: 16, fontWeight: "800" },
  stateBody: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  retry: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 11,
    alignItems: "center",
    marginTop: 4,
  },
  retryText: { color: colors.bg, fontWeight: "800" },
  headerRow: { flexDirection: "row", justifyContent: "space-between", gap: 12 },
  jobId: { color: colors.textSecondary, fontSize: 13, flex: 1 },
  badge: { fontSize: 14, fontWeight: "700" },
  meta: { color: colors.muted, fontSize: 12 },
  progressTrack: {
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.cardAlt,
    overflow: "hidden",
    marginTop: 4,
  },
  progressFill: { height: 8 },
  h2: { color: colors.textPrimary, fontSize: 16, fontWeight: "700", marginTop: 12 },
  output: { color: colors.textSecondary, fontSize: 13 },
  failBox: {
    backgroundColor: "#1f1416",
    borderColor: "#3a2226",
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginTop: 12,
  },
  failText: { color: "#ff9a9a", fontSize: 14 },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 16,
  },
  buttonText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  cancelButton: {
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 12,
  },
  cancelText: { color: colors.error, fontSize: 15, fontWeight: "700" },
  cancelHint: { color: colors.muted, fontSize: 12, marginTop: 8, lineHeight: 17 },
  disabled: { opacity: 0.5 },
  inlineError: { color: colors.error, fontSize: 14, marginTop: 12 },
  spacer: { height: 32 },
});
