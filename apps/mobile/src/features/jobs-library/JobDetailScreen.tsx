import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import {
  ApiError,
  isAbortError,
  jobDisplayName,
  pollJob,
  retryJob,
} from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import { JobActionsSheet, type JobActionOutcome } from "./components/JobActionsSheet";
import {
  ExportVideoError,
  exportVideoToDevice,
  jobCoverUrl,
  jobPosterUrl,
  jobPreviewUrl,
  jobResultUrl,
  loadExportReceipt,
  type ExportReceipt,
} from "@/src/shared/media";
import { stateBadge } from "./job-status";
import { useSession } from "@/src/shared/auth";
import { ProExportAccess, useRevenueCat } from "@/src/shared/billing";
import { useAppStateStatus } from "@/src/shared/lifecycle";
import {
  CreatorFlowRail,
  type CreatorFlowStage,
} from "@/src/shared/product/CreatorFlowRail";
import {
  JOB_STAGES,
  JobState,
  isFailedState,
  isTerminalState,
  type CoverResult,
  type DubJobResult,
  type Job,
  type JobStage,
} from "@/lib/types";

import { BrollSection } from "./components/broll/BrollSection";
import { CoverSheet } from "@/components/cover/CoverSheet";
import { DubSheet } from "@/components/dub/DubSheet";
import { JobPoster, JobVideo } from "@/src/shared/media";
import { demoNicheFor } from "@/src/shared/release/demo-data";
import { RerunSheet } from "./components/RerunSheet";
import { ExportReceiptCard } from "./components/ExportReceiptCard";
import { StageProgress } from "./components/StageProgress";
import { ScheduleSheet } from "@/components/schedule/ScheduleSheet";
import { SocialSection } from "@/components/social/SocialSection";
import { ShareReelSection } from "@/components/share/ShareReelSection";
import { GenerationErrorNotice } from "@/components/billing/GenerationErrorNotice";
import { WinnerLoopLink } from "@/src/features/winner-loop/WinnerLoopLink";
import { isRouteAvailable } from "@/src/shared/release/surface";

/**
 * A job can be dubbed once its source SCRIPT exists. When per-stage status is
 * known we require the `script` stage to have completed; otherwise a Complete
 * reel implies a finished script.
 */
function jobHasScript(job: Job): boolean {
  if (job.stages && "script" in job.stages) {
    return job.stages.script === "complete";
  }
  return job.state === JobState.Complete;
}

export function JobDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { apiKey } = useSession();
  const {
    requireProAccess,
    requireProExport,
    snapshot: entitlement,
  } = useRevenueCat();
  const router = useRouter();
  const token = apiKey ?? undefined;
  const appState = useAppStateStatus();

  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportProgress, setExportProgress] = useState<number | null>(null);
  const [exported, setExported] = useState(false);
  const [exportReceipt, setExportReceipt] = useState<ExportReceipt | null>(null);
  const [videoDuration, setVideoDuration] = useState<number | null>(null);
  const [rerunOpen, setRerunOpen] = useState(false);
  const [dubOpen, setDubOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [coverOpen, setCoverOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [pollNonce, setPollNonce] = useState(0);
  const cleanResultRefreshAttempts = useRef(0);

  const runPoll = useCallback(
    (signal: AbortSignal) => {
      if (!id) {
        setError("This job link does not contain a job ID.");
        return;
      }
      setError(null);
      pollJob(id, setJob, { token, signal }).catch((err) => {
        if (isAbortError(err)) return;
        setError(err instanceof ApiError ? err.message : "Failed to load job.");
      });
    },
    [id, token],
  );

  const onRetryLoad = useCallback(() => {
    if (!id) return;
    setError(null);
    setPollNonce((value) => value + 1);
  }, [id]);

  useFocusEffect(
    useCallback(() => {
      if (appState !== "active") return undefined;
      const controller = new AbortController();
      // pollJob fetches server truth immediately before starting its timer.
      runPoll(controller.signal);
      return () => controller.abort();
    }, [appState, id, pollNonce, runPoll, token]),
  );

  const onRetry = useCallback(async () => {
    if (!id) return;
    setRetrying(true);
    try {
      const updated = await retryJob(id, { token });
      setJob(updated);
      setPollNonce((value) => value + 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Retry failed.");
    } finally {
      setRetrying(false);
    }
  }, [id, token]);

  const onRerun = useCallback(
    (newJobId: string) => {
      setRerunOpen(false);
      router.push(`/job/${newJobId}`);
    },
    [router],
  );

  const onDubbed = useCallback(
    (_result: DubJobResult) => {
      setDubOpen(false);
      // The dubbed variants share one batch_id and run in the background; send
      // the creator to the jobs list to watch them render.
      router.push("/(tabs)/jobs");
    },
    [router],
  );

  const onScheduled = useCallback(() => {
    setScheduleOpen(false);
    // The schedule runs in the background; send the creator to the list to
    // review or cancel it.
    router.push("/scheduled");
  }, [router]);

  const onOpenSchedule = useCallback(async () => {
    setError(null);
    const access = await requireProAccess();
    if (!access.allowed) {
      setError(access.snapshot.message);
      return;
    }
    setScheduleOpen(true);
  }, [requireProAccess]);

  const onManaged = useCallback(
    (outcome: JobActionOutcome) => {
      setManageOpen(false);
      if (outcome.kind === "deleted") {
        // The reel is gone — leave the detail screen for the library.
        router.replace("/(tabs)/jobs");
        return;
      }
      setJob((prev) => (prev ? { ...prev, ...outcome.job } : outcome.job));
      setPollNonce((value) => value + 1);
    },
    [router],
  );

  const onCoverGenerated = useCallback((result: CoverResult) => {
    // Reflect the new cover on the in-memory job so re-opening the sheet (and any
    // future poster surfaces) sees it immediately. Immutable update.
    setJob((prev) =>
      prev ? { ...prev, cover_key: result.cover_key } : prev,
    );
  }, []);

  const onExport = useCallback(async () => {
    if (!job || exporting) return;
    const url = jobResultUrl(job);
    if (!url) {
      setError("The finished video is not ready to export.");
      return;
    }

    setExporting(true);
    setExportProgress(0);
    setError(null);
    try {
      const access = await requireProExport();
      if (!access.allowed) {
        setError(access.snapshot.message);
        return;
      }

      const result = await exportVideoToDevice({
        url,
        jobId: job.job_id,
        durationSeconds: videoDuration,
        onProgress: setExportProgress,
      });
      setExportReceipt(result);
      setExported(result.status === "ready" || result.status === "shared");
    } catch (err) {
      if (err instanceof ExportVideoError) {
        setExportReceipt(err.receipt);
      }
      setError(err instanceof Error ? err.message : "Video export failed.");
    } finally {
      setExporting(false);
      setExportProgress(null);
    }
  }, [exporting, job, requireProExport, videoDuration]);

  const badge = job ? stateBadge(job.state) : null;
  const posterUrl = job ? jobPosterUrl(job) : undefined;
  const previewUrl = job ? jobPreviewUrl(job) : undefined;
  const resultUrl = job ? jobResultUrl(job) : undefined;
  const coverUrl = job ? jobCoverUrl(job) : undefined;
  const terminal = job ? isTerminalState(job.state) : false;
  const canDub = job ? jobHasScript(job) : false;
  // Scheduling auto-publishes the finished output, so it needs a complete reel.
  const canSchedule = job ? job.state === JobState.Complete : false;
  const footageReady = job?.source_footage_ready === true;
  const briefReady = job?.brief_ready === true;
  const renderReady = job?.state === JobState.Complete;
  const showCreatorFlow = job?.kind === "avatar_reel";
  const flowActive: CreatorFlowStage | undefined = !footageReady
    ? "footage"
    : !briefReady
      ? "brief"
      : !renderReady
        ? "render"
        : !exported
          ? "export"
          : undefined;
  const flowCompleted: CreatorFlowStage[] = [
    ...(footageReady ? (["footage"] as const) : []),
    ...(briefReady ? (["brief"] as const) : []),
    ...(renderReady ? (["render"] as const) : []),
    ...(exported ? (["export"] as const) : []),
  ];
  const exportNeedsRetry =
    exportReceipt?.status === "failed" ||
    exportReceipt?.status === "downloading";
  const exportButtonLabel = exportNeedsRetry
    ? exportReceipt?.failedStep === "share"
      ? "Try sharing again"
      : "Retry export"
    : exported
      ? "Share again"
      : "Export video";

  useEffect(() => {
    if (entitlement.status !== "active") {
      cleanResultRefreshAttempts.current = 0;
      return undefined;
    }
    if (!job || !terminal || resultUrl) return undefined;
    if (cleanResultRefreshAttempts.current >= 5) return undefined;

    const timeout = setTimeout(() => {
      cleanResultRefreshAttempts.current += 1;
      setPollNonce((value) => value + 1);
    }, 1_500);
    return () => clearTimeout(timeout);
  }, [entitlement.status, job?.job_id, pollNonce, resultUrl, terminal]);

  useEffect(() => {
    if (!job?.job_id) return undefined;
    let active = true;
    setVideoDuration(null);
    void loadExportReceipt(job.job_id).then((receipt) => {
      if (!active) return;
      setExportReceipt(receipt);
      setExported(receipt?.status === "ready" || receipt?.status === "shared");
    });
    return () => {
      active = false;
    };
  }, [job?.job_id]);

  // Hide the upload stage when the job finished without it (no platforms).
  const visibleStages = useMemo<readonly JobStage[]>(() => {
    if (job && terminal && job.stages && !("upload" in job.stages)) {
      return JOB_STAGES.filter((s) => s !== "upload");
    }
    return JOB_STAGES;
  }, [job, terminal]);

  return (
    <>
      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        <Stack.Screen
          options={{
            title: job ? jobDisplayName(job) : "Reel",
            headerRight: job
              ? () => (
                  <Pressable
                    onPress={() => setManageOpen(true)}
                    hitSlop={10}
                    accessibilityRole="button"
                    accessibilityLabel="Manage this reel"
                  >
                    <Icon name="ellipsis-horizontal-circle-outline" size={24} color="#ece9e1" />
                  </Pressable>
                )
              : undefined,
          }}
        />

        {!job ? (
          error ? (
            <View style={styles.initialError}>
              <Text style={styles.initialErrorTitle}>Job unavailable</Text>
              <Text style={styles.initialErrorMessage}>{error}</Text>
              <Text style={styles.initialErrorHint}>
                Retry loads this same job ID. It does not create or rerun a job.
              </Text>
              <Pressable
                style={[styles.loadRetry, !id && styles.disabled]}
                onPress={onRetryLoad}
                disabled={!id}
                accessibilityRole="button"
                accessibilityLabel={`Retry loading job ${id || ""}`.trim()}
                accessibilityState={{ disabled: !id }}
              >
                <Text style={styles.loadRetryText}>Retry loading</Text>
              </Pressable>
            </View>
          ) : (
            <View style={styles.center}>
              <ActivityIndicator color="#E6C76A" size="large" />
              <Text style={styles.loadingText}>Loading job {id}</Text>
            </View>
          )
        ) : (
          <>
            <View style={styles.headerRow}>
              <Text style={styles.jobId} numberOfLines={1}>
                {jobDisplayName(job)}
              </Text>
              {badge ? (
                <Text style={[styles.badge, { color: badge.color }]}>
                  {job.cancelled ? "Cancelled" : badge.label}
                </Text>
              ) : null}
            </View>
            {job.archived ? (
              <Text style={styles.meta}>Archived — hidden from the main library.</Text>
            ) : null}
            <WinnerLoopLink jobId={job.job_id || id || ""} />
            {!terminal && !job.cancelled ? (
              <Pressable
                style={styles.cancelInline}
                onPress={() => setManageOpen(true)}
                accessibilityRole="button"
                accessibilityLabel="Cancel rendering or manage this reel"
              >
                <Icon name="stop-circle-outline" size={16} color="#ff9a9a" />
                <Text style={styles.cancelInlineText}>Cancel or manage</Text>
              </Pressable>
            ) : null}

            {showCreatorFlow ? (
              <CreatorFlowRail active={flowActive} completed={flowCompleted} />
            ) : null}

            {/* Poster thumbnail — shown until a playable video is available. */}
            {!resultUrl && !previewUrl ? (
              <JobPoster
                posterUrl={posterUrl}
                seed={job.job_id}
                niche={demoNicheFor(job.job_id)}
                style={styles.poster}
              />
            ) : null}

            <View style={styles.progressTrack}>
              <View
                style={[
                  styles.progressFill,
                  {
                    width: `${Math.max(0, Math.min(100, job.progress))}%`,
                    backgroundColor: badge?.color ?? "#E6C76A",
                  },
                ]}
              />
            </View>
            <Text style={styles.meta}>{job.progress}%</Text>

            {/* Final result takes priority; otherwise the short teaser clip. */}
            {resultUrl ? (
              <>
                <Text style={styles.h2}>Result</Text>
                <JobVideo
                  uri={resultUrl}
                  posterUri={posterUrl}
                  onDurationChange={setVideoDuration}
                />
                <ProExportAccess />
                <Pressable
                  style={[styles.export, exporting && styles.disabled]}
                  onPress={() => void onExport()}
                  disabled={exporting}
                  accessibilityRole="button"
                  accessibilityLabel="Export the finished video to this iPhone"
                  accessibilityState={{ disabled: exporting, busy: exporting }}
                >
                  {exporting ? (
                    <View style={styles.exportBusy}>
                      <ActivityIndicator color="#0a0a0b" />
                      <Text style={styles.exportText}>
                        {exportProgress === null
                          ? "Preparing video…"
                          : `Preparing ${Math.round(exportProgress * 100)}%`}
                      </Text>
                    </View>
                  ) : (
                    <Text style={styles.exportText}>{exportButtonLabel}</Text>
                  )}
                </Pressable>
                <Text style={styles.exportHint}>
                  Downloads the full MP4, then opens iPhone options including Save
                  Video, AirDrop, and installed publishing apps.
                </Text>
                {exportReceipt ? (
                  <ExportReceiptCard receipt={exportReceipt} />
                ) : null}
                <ShareReelSection jobId={job.job_id} token={token} />
              </>
            ) : previewUrl ? (
              <>
                <Text style={styles.h2}>Preview clip</Text>
                <JobVideo
                  uri={previewUrl}
                  posterUri={posterUrl}
                  isLooping
                  isMuted
                />
              </>
            ) : job.state === JobState.Processing ? (
              <Text style={styles.hint}>
                Rendering… this screen refreshes every 3 seconds.
              </Text>
            ) : null}

            {terminal && !resultUrl ? (
              <>
                <ProExportAccess />
                <Text style={styles.exportHint}>
                  The preview remains available. Pro unlocks the clean,
                  full-length result for export and sharing.
                </Text>
              </>
            ) : null}

            <Text style={styles.h2}>Stages</Text>
            <StageProgress stages={job.stages} visibleStages={visibleStages} />

            {isFailedState(job.state) ? (
              <View style={styles.failBox}>
                {job.failed_stage ? (
                  <Text style={styles.failText}>
                    Failed at stage: {job.failed_stage}
                  </Text>
                ) : null}
                {job.error ? (
                  <Text style={styles.failText}>{job.error}</Text>
                ) : null}
                <Pressable
                  style={[
                    styles.retry,
                    (retrying || job.retry_eligible === false) && styles.disabled,
                  ]}
                  onPress={onRetry}
                  disabled={retrying || job.retry_eligible === false}
                  accessibilityRole="button"
                  accessibilityLabel="Retry this failed job"
                  accessibilityState={{
                    disabled: retrying || job.retry_eligible === false,
                    busy: retrying,
                  }}
                >
                  {retrying ? (
                    <ActivityIndicator color="#0f0f10" />
                  ) : (
                    <Text style={styles.retryText}>Retry this job</Text>
                  )}
                </Pressable>
                <Text style={styles.retryHint}>
                  {job.retry_eligible === false
                    ? "This job type cannot be retried in place."
                    : "Retry keeps this job ID and resumes from the failed stage when its saved output is available."}
                </Text>
              </View>
            ) : null}

            {/* Re-run with tweaks — available once the job is terminal. */}
            {terminal ? (
              <Pressable
                style={styles.rerun}
                onPress={() => setRerunOpen(true)}
                accessibilityRole="button"
              >
                <Text style={styles.rerunText}>Re-run with tweaks</Text>
              </Pressable>
            ) : null}

            {/* Edit timeline — non-destructively trim/reorder/caption the finished
                reel into a new export. Needs a rendered result to edit. */}
            {terminal && resultUrl ? (
              <Pressable
                style={styles.editTimeline}
                onPress={() =>
                  router.push(
                    `/editor?jobId=${encodeURIComponent(job.job_id)}&url=${encodeURIComponent(resultUrl)}`,
                  )
                }
                accessibilityRole="button"
                accessibilityLabel="Edit this reel in the timeline editor"
              >
                <Text style={styles.editTimelineText}>Edit timeline</Text>
              </Pressable>
            ) : null}
            {terminal && resultUrl ? (
              <Pressable
                style={styles.editTimeline}
                onPress={() =>
                  router.push(
                    `/capture/trim?jobId=${encodeURIComponent(job.job_id)}&url=${encodeURIComponent(resultUrl)}${
                      videoDuration ? `&duration=${videoDuration}` : ""
                    }`,
                  )
                }
                accessibilityRole="button"
                accessibilityLabel="Trim and export a cut of this reel"
              >
                <Text style={styles.editTimelineText}>Trim & export</Text>
              </Pressable>
            ) : null}

            {/* Dub into more languages — needs a finished source script. */}
            {terminal ? (
              <>
                <Pressable
                  style={[styles.dub, !canDub && styles.disabled]}
                  onPress={() => setDubOpen(true)}
                  disabled={!canDub}
                  accessibilityRole="button"
                  accessibilityLabel="Dub into more languages"
                  accessibilityState={{ disabled: !canDub }}
                >
                  <Text style={styles.dubText}>Dub into more languages</Text>
                </Pressable>
                {!canDub ? (
                  <Text style={styles.hint}>
                    Dubbing needs a finished script — available once this reel
                    completes.
                  </Text>
                ) : null}
              </>
            ) : null}

            {/* Schedule auto-publish — needs a completed reel. */}
            {canSchedule && isRouteAvailable("/scheduled") ? (
              <Pressable
                style={styles.schedule}
                onPress={() => void onOpenSchedule()}
                accessibilityRole="button"
                accessibilityLabel="Schedule this reel to auto-publish"
              >
                <Text style={styles.scheduleText}>Schedule publish</Text>
              </Pressable>
            ) : null}

            {/* Cover / thumbnail generator — hook headline over the poster. */}
            <Text style={styles.h2}>Cover</Text>
            {coverUrl ? (
              <JobPoster
                posterUrl={coverUrl}
                style={styles.poster}
                accessibilityLabel="Generated cover"
              />
            ) : null}
            <Pressable
              style={styles.cover}
              onPress={() => setCoverOpen(true)}
              accessibilityRole="button"
              accessibilityLabel="Generate a cover image for this reel"
            >
              <Text style={styles.coverText}>
                {coverUrl ? "Edit cover" : "Generate cover"}
              </Text>
            </Pressable>

            {/* B-roll cutaways — suggest muted stock clips to splice as a
                brief intro/outro. Optional; nothing loads until requested. */}
            <Text style={styles.h2}>B-roll</Text>
            <BrollSection jobId={job.job_id} token={token} />

            {/* Caption & hashtags — generate platform-tailored post copy for a
                finished reel. Optional; nothing loads until requested. */}
            {terminal ? (
              <>
                <Text style={styles.h2}>Caption &amp; Hashtags</Text>
                <SocialSection jobId={job.job_id} token={token} />
              </>
            ) : null}
          </>
        )}

        {job ? <GenerationErrorNotice message={error} style={styles.error} /> : null}
        <View style={{ height: 40 }} />
      </ScrollView>

      <JobActionsSheet
        visible={manageOpen}
        job={job}
        token={token}
        onClose={() => setManageOpen(false)}
        onDone={onManaged}
      />

      {job ? (
        <RerunSheet
          visible={rerunOpen}
          job={job}
          token={token}
          onClose={() => setRerunOpen(false)}
          onRerun={onRerun}
        />
      ) : null}

      {job ? (
        <DubSheet
          visible={dubOpen}
          jobId={job.job_id}
          token={token}
          onClose={() => setDubOpen(false)}
          onDone={onDubbed}
        />
      ) : null}

      {job ? (
        <ScheduleSheet
          visible={scheduleOpen}
          jobId={job.job_id}
          token={token}
          onClose={() => setScheduleOpen(false)}
          onScheduled={onScheduled}
        />
      ) : null}

      {job ? (
        <CoverSheet
          visible={coverOpen}
          jobId={job.job_id}
          token={token}
          initialCoverUrl={coverUrl}
          onClose={() => setCoverOpen(false)}
          onGenerated={onCoverGenerated}
        />
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0a0a0b" },
  content: { padding: 20, gap: 10 },
  center: { paddingTop: 80, alignItems: "center" },
  loadingText: {
    color: "#9b978d",
    fontFamily: "monospace",
    fontSize: 12,
    marginTop: 12,
  },
  initialError: {
    backgroundColor: "#0b0c0a",
    borderColor: "#D0605B",
    borderWidth: 1,
    padding: 16,
    gap: 9,
    marginTop: 48,
  },
  initialErrorTitle: {
    color: "#D0605B",
    fontFamily: "monospace",
    fontSize: 16,
    fontWeight: "800",
  },
  initialErrorMessage: {
    color: "#ece9e1",
    fontFamily: "monospace",
    fontSize: 13,
    lineHeight: 18,
  },
  initialErrorHint: {
    color: "#9b978d",
    fontFamily: "monospace",
    fontSize: 11,
    lineHeight: 16,
  },
  loadRetry: {
    backgroundColor: "#D0605B",
    borderColor: "#D0605B",
    borderWidth: 1,
    paddingVertical: 11,
    alignItems: "center",
  },
  loadRetryText: {
    color: "#ece9e1",
    fontFamily: "monospace",
    fontWeight: "800",
  },
  cancelInline: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    alignSelf: "flex-start",
    borderColor: "#3a2226",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  cancelInlineText: { color: "#ff9a9a", fontSize: 13, fontWeight: "600" },
  headerRow: { flexDirection: "row", justifyContent: "space-between", gap: 12 },
  jobId: { color: "#ece9e1", fontSize: 13, flex: 1 },
  badge: { fontSize: 14, fontWeight: "700" },
  poster: {
    width: "100%",
    aspectRatio: 9 / 16,
    borderRadius: 12,
    marginTop: 4,
  },
  progressTrack: {
    height: 8,
    borderRadius: 4,
    backgroundColor: "#27272a",
    overflow: "hidden",
    marginTop: 4,
  },
  progressFill: { height: 8 },
  meta: { color: "#6f6c65", fontSize: 12 },
  h2: { color: "#ece9e1", fontSize: 16, fontWeight: "700", marginTop: 16 },
  hint: { color: "#E6C76A", fontSize: 14, marginTop: 8 },
  failBox: {
    backgroundColor: "#1f1416",
    borderColor: "#3a2226",
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 10,
    marginTop: 12,
  },
  failText: { color: "#ff9a9a", fontSize: 14 },
  retry: {
    backgroundColor: "#E6C76A",
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  disabled: { opacity: 0.5 },
  retryText: { color: "#0f0f10", fontWeight: "700" },
  retryHint: { color: "#9b978d", fontSize: 12, lineHeight: 17 },
  rerun: {
    backgroundColor: "#0f0f10",
    borderColor: "#E6C76A",
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 20,
  },
  rerunText: { color: "#E6C76A", fontSize: 15, fontWeight: "700" },
  editTimeline: {
    backgroundColor: "#0f0f10",
    borderColor: "#E6C76A",
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 12,
  },
  editTimelineText: { color: "#E6C76A", fontSize: 15, fontWeight: "700" },
  export: {
    backgroundColor: "#E6C76A",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 2,
  },
  exportBusy: { flexDirection: "row", alignItems: "center", gap: 9 },
  exportText: { color: "#0a0a0b", fontSize: 15, fontWeight: "800" },
  exportHint: { color: "#9b978d", fontSize: 12, lineHeight: 17 },
  dub: {
    backgroundColor: "#E6C76A",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 12,
  },
  dubText: { color: "#0f0f10", fontSize: 15, fontWeight: "700" },
  schedule: {
    backgroundColor: "#0f0f10",
    borderColor: "#E6C76A",
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 12,
  },
  scheduleText: { color: "#E6C76A", fontSize: 15, fontWeight: "700" },
  cover: {
    backgroundColor: "#0f0f10",
    borderColor: "#E6C76A",
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 12,
  },
  coverText: { color: "#E6C76A", fontSize: 15, fontWeight: "700" },
  error: { color: "#E0847F", fontSize: 14, marginTop: 12 },
});
