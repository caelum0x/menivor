/**
 * The persisted project's shot list + per-shot render pipeline + final export.
 * Loads the project (`GET /film/projects/{id}`, owner-scoped), renders one
 * {@link ShotRenderPanel} per shot, aggregates whole-film render progress,
 * offers "Render all pending shots" (`POST /film/projects/{id}/render`) and,
 * once every shot is done, "Export film" (`POST /film/projects/{id}/export`)
 * which stitches the shot renders into one MP4 server-side; the export is
 * polled until `export_state` is done and the final video plays inline.
 *
 * A 404 means the caller does not own the project; a 503 means persistence is
 * unavailable. Both surface as inline, retryable errors.
 */

import * as React from "react";
import {
  ActivityIndicator,
  FlatList,
  Linking,
  Pressable,
  Share,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { ApiError, POLL_INTERVAL_MS, isAbortError, makeAbortError } from "@/src/shared/api";
import { JobVideo } from "@/src/shared/media";
import { Icon } from "@/components/ui/Icon";
import {
  exportFilmProject,
  getFilmProject,
  isExportPending,
  renderFilmProject,
  type FilmProject,
  type FilmProjectShot,
} from "@/lib/film";
import { isTerminalState, type RenderJob } from "@/lib/render";

import {
  SHOT_MAX_COST_MICROS,
  allShotsTerminal,
  overallRenderProgress,
} from "../logic";
import { ShotRenderPanel } from "./ShotRenderPanel";

interface ProjectShotListProps {
  token: string | undefined;
  projectId: string;
  onBack: () => void;
}

type Phase = "loading" | "ready" | "error";

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "Project not found (or not yours).";
    if (err.status === 503) return "Film persistence is unavailable right now.";
    if (err.status === 402) return "Not enough credits. Top up your wallet and try again.";
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "Could not load the project.";
}

export function ProjectShotList({ token, projectId, onBack }: ProjectShotListProps) {
  const [project, setProject] = React.useState<FilmProject | null>(null);
  const [phase, setPhase] = React.useState<Phase>("loading");
  const [error, setError] = React.useState<string | null>(null);
  const [jobs, setJobs] = React.useState<Record<string, RenderJob | undefined>>({});
  const inFlight = React.useRef<AbortController | null>(null);
  const [renderingAll, setRenderingAll] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [exportStarting, setExportStarting] = React.useState(false);

  const load = React.useCallback(async () => {
    inFlight.current?.abort(makeAbortError());
    const controller = new AbortController();
    inFlight.current = controller;
    setPhase("loading");
    setError(null);
    try {
      const res = await getFilmProject(projectId, {
        token,
        signal: controller.signal,
      });
      setProject(res);
      setPhase("ready");
    } catch (err) {
      if (isAbortError(err)) return;
      setError(describeError(err));
      setPhase("error");
    }
  }, [projectId, token]);

  React.useEffect(() => {
    void load();
    return () => inFlight.current?.abort(makeAbortError());
  }, [load]);

  /** Quiet re-read of the project (no loading flash) — used by export polling. */
  const refresh = React.useCallback(async () => {
    const res = await getFilmProject(projectId, { token });
    setProject(res);
    return res;
  }, [projectId, token]);

  // Poll while a stitched export is queued/running.
  const exportState = project?.export_state;
  React.useEffect(() => {
    if (!isExportPending(exportState)) return undefined;
    const timer = setTimeout(() => {
      refresh().catch((err) => {
        if (!isAbortError(err)) setActionError(describeError(err));
      });
    }, POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [exportState, project, refresh]);

  const onRenderAll = React.useCallback(async () => {
    if (renderingAll) return;
    setRenderingAll(true);
    setActionError(null);
    try {
      const result = await renderFilmProject(
        projectId,
        { max_cost_micros: SHOT_MAX_COST_MICROS },
        { token },
      );
      if (result.error) setActionError(result.error);
      // Reload so each started shot carries its render_job_id; the panels
      // then resume polling their own render.
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    } finally {
      setRenderingAll(false);
    }
  }, [projectId, refresh, renderingAll, token]);

  const onExport = React.useCallback(async () => {
    if (exportStarting) return;
    setExportStarting(true);
    setActionError(null);
    try {
      const started = await exportFilmProject(projectId, { token });
      setProject((prev) =>
        prev
          ? {
              ...prev,
              export_state: started.export_state,
              export_error: started.export_error ?? "",
              final_url: started.final_url ?? prev.final_url ?? null,
              status: started.status ?? prev.status,
            }
          : prev,
      );
    } catch (err) {
      setActionError(describeError(err));
    } finally {
      setExportStarting(false);
    }
  }, [exportStarting, projectId, token]);

  const onJob = React.useCallback((shotId: string, job: RenderJob) => {
    setJobs((prev) => ({ ...prev, [shotId]: job }));
  }, []);

  // Once every shot has a completed render, re-read the project so the server
  // folds the shot states (status -> shots_ready) before an export.
  const completedCount = Object.values(jobs).filter((j) => j?.state === "COMPLETED").length;
  const shotTotal = project?.shots.length ?? 0;
  React.useEffect(() => {
    if (shotTotal > 0 && completedCount === shotTotal) {
      refresh().catch((err) => setActionError(describeError(err)));
    }
  }, [completedCount, refresh, shotTotal]);

  if (phase === "loading") {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.primary} />
        <Text style={styles.meta}>Loading project…</Text>
      </View>
    );
  }

  if (phase === "error" || project === null) {
    return (
      <View style={styles.centered}>
        <Text style={styles.error}>{error ?? "Project unavailable."}</Text>
        <Pressable style={styles.retry} onPress={() => void load()}>
          <Text style={styles.retryText}>Retry</Text>
        </Pressable>
        <Text style={styles.link} onPress={onBack}>
          Back
        </Text>
      </View>
    );
  }

  const shots = project.shots;
  const progress = overallRenderProgress(shots, jobs);
  const done = allShotsTerminal(shots, jobs);
  const shotDone = (shot: FilmProjectShot) =>
    jobs[shot.shot_id]?.state === "COMPLETED" || shot.status === "done";
  const doneCount = shots.filter(shotDone).length;
  const allDone = shots.length > 0 && doneCount === shots.length;
  const shotActive = (shot: FilmProjectShot) => {
    const job = jobs[shot.shot_id];
    return job ? !isTerminalState(job.state) : shot.status === "rendering";
  };
  const pendingCount = shots.filter((shot) => !shotDone(shot) && !shotActive(shot)).length;
  const exporting = isExportPending(project.export_state) || exportStarting;
  const finalUrl = project.export_state === "done" ? project.final_url ?? null : null;
  const downloadUrl = project.final_download_url ?? finalUrl;
  const canExport = (allDone || project.can_export === true) && !exporting;

  const header = (
    <View style={styles.headerBlock}>
      <Text style={styles.title}>{project.title || "Untitled project"}</Text>
      <Text style={styles.meta}>
        {project.status} · {shots.length} shots ·{" "}
        {project.total_runtime_s.toFixed(1)}s runtime
      </Text>
      <View style={styles.progressTrack}>
        <View style={[styles.progressFill, { width: `${Math.round(progress * 100)}%` }]} />
      </View>
      <Text style={styles.progressLabel}>
        {allDone
          ? "All shots finished rendering"
          : done
            ? `${doneCount} of ${shots.length} shots rendered; retry the failed ones`
            : `${doneCount} of ${shots.length} shots rendered (${Math.round(progress * 100)}%)`}
      </Text>

      {pendingCount > 0 ? (
        <Pressable
          style={[styles.action, renderingAll && styles.disabled]}
          onPress={() => void onRenderAll()}
          disabled={renderingAll}
          accessibilityRole="button"
          accessibilityLabel="Render all pending shots"
        >
          {renderingAll ? (
            <ActivityIndicator color={colors.bg} />
          ) : (
            <Text style={styles.actionText}>Render all {pendingCount} pending shots</Text>
          )}
        </Pressable>
      ) : null}

      <View style={styles.exportBox}>
        <Text style={styles.exportTitle}>Final film</Text>
        {finalUrl ? (
          <>
            <JobVideo uri={finalUrl} />
            <View style={styles.exportActions}>
              <Pressable
                style={styles.inlineAction}
                onPress={() => void Linking.openURL(downloadUrl ?? finalUrl)}
                accessibilityRole="button"
                accessibilityLabel="Open the final film"
              >
                <Icon name="download-outline" size={16} color={colors.primary} />
                <Text style={styles.inlineActionText}>Download</Text>
              </Pressable>
              <Pressable
                style={styles.inlineAction}
                onPress={() => void Share.share({ url: finalUrl, message: finalUrl })}
                accessibilityRole="button"
                accessibilityLabel="Share the final film"
              >
                <Icon name="share-outline" size={16} color={colors.primary} />
                <Text style={styles.inlineActionText}>Share</Text>
              </Pressable>
            </View>
          </>
        ) : exporting ? (
          <View style={styles.exportRow}>
            <ActivityIndicator color={colors.primary} />
            <Text style={styles.meta}>Stitching {shots.length} shots into one video</Text>
          </View>
        ) : (
          <Text style={styles.meta}>
            {allDone
              ? "Every shot is rendered. Export stitches them into one MP4 in shot order."
              : "Export unlocks once every shot has rendered."}
          </Text>
        )}
        {project.export_state === "failed" && project.export_error ? (
          <Text style={styles.error}>{project.export_error}</Text>
        ) : null}
        {!exporting ? (
          <Pressable
            style={[styles.action, !canExport && styles.disabled]}
            onPress={() => void onExport()}
            disabled={!canExport}
            accessibilityRole="button"
            accessibilityLabel={finalUrl ? "Export the film again" : "Export the film"}
          >
            <Text style={styles.actionText}>
              {finalUrl ? "Re-export film" : project.export_state === "failed" ? "Retry export" : "Export film"}
            </Text>
          </Pressable>
        ) : null}
      </View>

      {actionError ? <Text style={styles.error}>{actionError}</Text> : null}
      <Text style={styles.link} onPress={onBack}>
        All projects
      </Text>
    </View>
  );

  return (
    <FlatList<FilmProjectShot>
      style={styles.container}
      contentContainerStyle={styles.content}
      data={shots}
      keyExtractor={(shot) => shot.shot_id}
      ListHeaderComponent={header}
      renderItem={({ item }) => (
        <ShotRenderPanel token={token} projectId={project.id} shot={item} onJob={onJob} />
      )}
      ListEmptyComponent={<Text style={styles.meta}>This project has no shots.</Text>}
    />
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  centered: {
    flex: 1,
    backgroundColor: colors.bg,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 12,
  },
  headerBlock: { marginBottom: 16 },
  title: { color: colors.textPrimary, fontSize: 20, fontWeight: "800" },
  meta: { color: colors.muted, fontSize: 13, marginTop: 4, textAlign: "center" },
  progressTrack: {
    height: 8,
    backgroundColor: colors.card,
    borderRadius: 4,
    marginTop: 12,
    overflow: "hidden",
  },
  progressFill: { height: 8, backgroundColor: colors.primary },
  progressLabel: { color: colors.textSecondary, fontSize: 13, marginTop: 6 },
  link: { color: colors.primary, fontSize: 15, fontWeight: "700", marginTop: 12 },
  error: { color: colors.error, fontSize: 14, textAlign: "center", marginTop: 8 },
  action: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 12,
  },
  actionText: { color: colors.bg, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.5 },
  exportBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginTop: 16,
    gap: 8,
  },
  exportTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  exportRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  exportActions: { flexDirection: "row", gap: 16 },
  inlineAction: { flexDirection: "row", alignItems: "center", gap: 4 },
  inlineActionText: { color: colors.primary, fontSize: 13, fontWeight: "600" },
  retry: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 20,
  },
  retryText: { color: colors.bg, fontSize: 14, fontWeight: "700" },
});
