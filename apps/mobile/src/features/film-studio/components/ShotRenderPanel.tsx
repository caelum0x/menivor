/**
 * Per-shot render control. Starts the render THROUGH the project
 * (`POST /film/projects/{id}/shots/{shot_id}/render`) so the persisted shot row
 * tracks its render job and the project learns when every shot is done, then
 * polls that render job to a terminal state (`POST /render/jobs/{id}/advance`)
 * on a `POLL_INTERVAL_MS` cadence.
 *
 * A shot that already has a `render_job_id` (e.g. after reopening the project
 * or after "Render all") is hydrated from `GET /render/jobs/{id}` and resumed.
 * Every render snapshot is reported up so the parent can aggregate progress.
 * Completed outputs are presigned by the API and play inline.
 */

import * as React from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { RenderOutputs } from "@/components/render/RenderOutputs";
import { ApiError, POLL_INTERVAL_MS, isAbortError, makeAbortError } from "@/src/shared/api";
import {
  advanceRenderJob,
  getRenderJob,
  isTerminalState,
  type RenderJob,
} from "@/lib/render";
import { renderFilmShot, type FilmProjectShot } from "@/lib/film";

import { SHOT_MAX_COST_MICROS, shotRenderPhase, type ShotRenderPhase } from "../logic";

interface ShotRenderPanelProps {
  token: string | undefined;
  projectId: string;
  shot: FilmProjectShot;
  /** Report every render snapshot up so the parent can aggregate progress. */
  onJob: (shotId: string, job: RenderJob) => void;
}

const PHASE_LABEL: Record<string, string> = {
  idle: "Not rendered yet",
  queued: "Queued, waiting for a worker",
  running: "Rendering",
  completed: "Render complete",
  failed: "Render failed",
};

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(makeAbortError());
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(makeAbortError());
      },
      { once: true },
    );
  });
}

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 402) return "Not enough credits to render this shot. Top up your wallet and retry.";
    if (err.status === 409) return "This shot is already rendering or done.";
    return err.message;
  }
  return err instanceof Error ? err.message : "Failed to render shot.";
}

export function ShotRenderPanel({ token, projectId, shot, onJob }: ShotRenderPanelProps) {
  const [job, setJob] = React.useState<RenderJob | undefined>(undefined);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const controllerRef = React.useRef<AbortController | null>(null);

  React.useEffect(() => {
    return () => controllerRef.current?.abort(makeAbortError());
  }, []);

  const publish = React.useCallback(
    (snapshot: RenderJob) => {
      setJob(snapshot);
      onJob(shot.shot_id, snapshot);
    },
    [onJob, shot.shot_id],
  );

  /** Follow a render job until terminal. Aborts any previous follow. */
  const follow = React.useCallback(
    async (renderJobId: string) => {
      controllerRef.current?.abort(makeAbortError());
      const controller = new AbortController();
      controllerRef.current = controller;
      setBusy(true);
      setError(null);
      try {
        let current = await getRenderJob(renderJobId, { token, signal: controller.signal });
        publish(current);
        while (!isTerminalState(current.state)) {
          await sleep(POLL_INTERVAL_MS, controller.signal);
          current = await advanceRenderJob(current.id, { token, signal: controller.signal });
          publish(current);
        }
      } catch (err) {
        if (isAbortError(err)) return;
        setError(describe(err));
      } finally {
        if (controllerRef.current === controller) setBusy(false);
      }
    },
    [publish, token],
  );

  // Hydrate/resume a render started earlier (reopened project, "Render all").
  React.useEffect(() => {
    if (shot.render_job_id && job?.id !== shot.render_job_id) {
      void follow(shot.render_job_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shot.render_job_id]);

  const render = React.useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const started = await renderFilmShot(
        projectId,
        shot.shot_id,
        { max_cost_micros: SHOT_MAX_COST_MICROS },
        { token },
      );
      await follow(started.render_job_id);
    } catch (err) {
      if (isAbortError(err)) return;
      setError(describe(err));
      setBusy(false);
    }
  }, [busy, follow, projectId, shot.shot_id, token]);

  const phase: ShotRenderPhase = job
    ? shotRenderPhase(job)
    : shot.status === "done"
      ? "completed"
      : shot.status === "failed"
        ? "failed"
        : "idle";
  const terminal = job ? isTerminalState(job.state) : shot.status === "done";
  const completed = phase === "completed";
  const pct = job ? Math.round(job.progress * 100) : 0;

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.order}>#{shot.order + 1}</Text>
        <Text style={styles.role}>{shot.role}</Text>
        <Text style={styles.motion}>{shot.camera_motion}</Text>
      </View>
      <Text style={styles.prompt} numberOfLines={3}>
        {shot.prompt}
      </Text>
      <Text style={styles.meta}>
        {(shot.duration_ms / 1000).toFixed(1)}s · seed {shot.seed}
      </Text>

      <Text style={[styles.phase, phase === "failed" && styles.phaseFailed]}>
        {PHASE_LABEL[phase]}
        {job && !terminal ? ` · ${pct}%` : ""}
      </Text>

      {job && completed ? <RenderOutputs job={job} compact /> : null}

      {error ? <Text style={styles.error}>{error}</Text> : null}
      {job?.error ? <Text style={styles.error}>{job.error}</Text> : null}

      {!completed ? (
        <Pressable
          style={[styles.button, busy && styles.buttonDisabled]}
          onPress={() => void render()}
          disabled={busy}
          accessibilityRole="button"
          accessibilityLabel={`Render shot ${shot.order + 1}`}
        >
          {busy ? (
            <ActivityIndicator color={colors.bg} />
          ) : (
            <Text style={styles.buttonText}>{phase === "failed" ? "Retry render" : "Render shot"}</Text>
          )}
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  header: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  order: { color: colors.primary, fontSize: 14, fontWeight: "800" },
  role: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  motion: { color: colors.muted, fontSize: 12, marginLeft: "auto" },
  prompt: { color: colors.textSecondary, fontSize: 13, marginBottom: 4 },
  meta: { color: colors.muted, fontSize: 12, marginBottom: 8 },
  phase: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  phaseFailed: { color: colors.error },
  error: { color: colors.error, fontSize: 13, marginTop: 6 },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 10,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.bg, fontSize: 14, fontWeight: "700" },
});
