import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { ApiError, isAbortError, pollJob, rerunJob } from "@/lib/api";
import { JobState, isFailedState, isTerminalState, type Job } from "@/lib/types";
import { JobPoster, JobVideo, jobPosterUrl, jobResultUrl } from "@/src/shared/media";
import { reviewPhase } from "../logic";

interface GenerationReviewProps {
  token: string | undefined;
  /** The job returned by createJob — polled to completion here. */
  initialJob: Job;
  /** Approve = keep the reel as-is (advance out of the flow). */
  onApprove: (job: Job) => void;
  /** Start over from the template browser. */
  onStartOver: () => void;
}

function describe(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong while generating.";
}

const PHASE_LABEL: Record<string, string> = {
  queued: "Queued — waiting for a worker…",
  running: "Generating your reel…",
  completed: "Reel ready for review",
  failed: "Generation failed",
};

/**
 * Poll a just-created reel job to a terminal state, then let the creator
 * approve (keep) the result or redo it (rerun the same job). Polling is
 * cancellable and restarts whenever a rerun produces a fresh job id.
 */
export function GenerationReview({
  token,
  initialJob,
  onApprove,
  onStartOver,
}: GenerationReviewProps) {
  const [job, setJob] = useState<Job>(initialJob);
  const [pollError, setPollError] = useState<string | null>(null);
  const [redoing, setRedoing] = useState(false);
  const [pollNonce, setPollNonce] = useState(0);
  // The job id currently being polled; a rerun swaps this to restart polling.
  const [jobId, setJobId] = useState<string>(initialJob.job_id);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setPollError(null);
    void pollJob(jobId, (snapshot) => {
      if (active) setJob(snapshot);
    }, { token, signal: controller.signal }).catch((err: unknown) => {
      if (!active || isAbortError(err)) return;
      setPollError(describe(err));
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [jobId, pollNonce, token]);

  const phase = reviewPhase(job.state, job.progress);
  const terminal = isTerminalState(job.state);
  const failed = isFailedState(job.state);
  const completed = job.state === JobState.Complete;
  const resultUrl = jobResultUrl(job);
  const posterUrl = jobPosterUrl(job);

  const onRedo = async (): Promise<void> => {
    setRedoing(true);
    setPollError(null);
    try {
      // Rerun clones this job's params and enqueues a fresh job to re-poll.
      const next = await rerunJob(job.job_id, {}, { token });
      setJob(next);
      setJobId(next.job_id);
    } catch (err) {
      setPollError(describe(err));
    } finally {
      setRedoing(false);
    }
  };

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
    >
      <Text style={styles.title}>Review</Text>
      <Text style={styles.phase}>{PHASE_LABEL[phase] ?? phase}</Text>

      {!terminal ? (
        <View style={styles.progressCard}>
          <ActivityIndicator color="#E6C76A" />
          <View style={styles.progressTrack}>
            <View
              style={[
                styles.progressFill,
                { width: `${Math.round(Math.max(0, Math.min(1, job.progress)) * 100)}%` },
              ]}
            />
          </View>
          <Text style={styles.meta}>{Math.round(job.progress * 100)}%</Text>
        </View>
      ) : null}

      {terminal && !failed ? (
        <View style={styles.previewCard}>
          {resultUrl ? (
            <JobVideo uri={resultUrl} posterUri={posterUrl} />
          ) : posterUrl ? (
            <JobPoster posterUrl={posterUrl} />
          ) : (
            <Text style={styles.meta}>
              Reel completed. No preview URL was returned.
            </Text>
          )}
        </View>
      ) : null}

      {failed ? (
        <View style={styles.errorBanner}>
          <Text style={styles.errorText}>
            {job.error || "The reel could not be generated."}
          </Text>
        </View>
      ) : null}

      {pollError ? (
        <View style={styles.errorBanner}>
          <Text style={styles.errorText}>{pollError}</Text>
          <Text style={styles.errorHint}>
            Job {jobId} still exists. Retry status checks for this same job.
          </Text>
          <Pressable
            style={styles.pollRetry}
            onPress={() => {
              setPollError(null);
              setPollNonce((value) => value + 1);
            }}
            accessibilityRole="button"
            accessibilityLabel={`Retry status checks for job ${jobId}`}
          >
            <Text style={styles.pollRetryText}>Retry status</Text>
          </Pressable>
        </View>
      ) : null}

      {terminal ? (
        <View style={styles.actions}>
          {completed ? (
            <Pressable
              style={styles.primary}
              onPress={() => onApprove(job)}
              disabled={redoing}
            >
              <Text style={styles.primaryText}>Approve and continue</Text>
            </Pressable>
          ) : null}
          <Pressable
            style={styles.secondary}
            onPress={onRedo}
            disabled={redoing}
          >
            {redoing ? (
              <ActivityIndicator color="#ece9e1" />
            ) : (
              <Text style={styles.secondaryText}>Redo</Text>
            )}
          </Pressable>
          <Pressable
            style={styles.ghost}
            onPress={onStartOver}
            disabled={redoing}
          >
            <Text style={styles.ghostText}>Start over</Text>
          </Pressable>
        </View>
      ) : null}

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0a0a0b" },
  content: { padding: 20, gap: 12 },
  title: { color: "#ece9e1", fontSize: 22, fontWeight: "800" },
  phase: { color: "#ece9e1", fontSize: 15 },
  progressCard: {
    backgroundColor: "#0f0f10",
    borderRadius: 12,
    padding: 16,
    gap: 12,
    alignItems: "center",
  },
  progressTrack: {
    alignSelf: "stretch",
    height: 6,
    borderRadius: 3,
    backgroundColor: "#27272a",
    overflow: "hidden",
  },
  progressFill: { height: 6, backgroundColor: "#E6C76A" },
  previewCard: {
    backgroundColor: "#0f0f10",
    borderRadius: 12,
    padding: 8,
  },
  meta: { color: "#6f6c65", fontSize: 13 },
  errorBanner: {
    backgroundColor: "#2a1420",
    borderColor: "#E0847F",
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    gap: 8,
  },
  errorText: { color: "#E0847F", fontSize: 14 },
  errorHint: { color: "#ece9e1", fontSize: 12, lineHeight: 17 },
  pollRetry: {
    borderColor: "#E0847F",
    borderWidth: 1,
    paddingVertical: 10,
    alignItems: "center",
  },
  pollRetryText: { color: "#ece9e1", fontWeight: "700" },
  actions: { gap: 10, marginTop: 8 },
  primary: {
    backgroundColor: "#E6C76A",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
  },
  primaryText: { color: "#0f0f10", fontSize: 16, fontWeight: "700" },
  secondary: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  secondaryText: { color: "#ece9e1", fontWeight: "600" },
  ghost: { paddingVertical: 12, alignItems: "center" },
  ghostText: { color: "#E6C76A", fontWeight: "600" },
});
