/**
 * Route: /repurpose/clipping/clip/[id] — an AUTO-CLIP (worker) job detail.
 *
 * NAV MANIFEST:
 *   { route: "/repurpose/clipping/clip/[id]", title: "Auto-Clip Job" }
 *
 * Polls the clipping worker (GET /clipping/jobs/{id}) every few seconds while it
 * renders, showing a progress bar + status. Once clips exist it lists the
 * produced shorts (GET /clipping/jobs/{id}/clips) and lets the creator promote
 * any one into a ready-to-submit reel draft (with confirmation). Pull-to-refresh,
 * plus comprehensive loading / empty / error states.
 *
 * Auth flows through the shared api client (x-api-key). No secrets here.
 */

import { useCallback, useEffect, useRef, useState } from "react";
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

import { Stack, useLocalSearchParams } from "expo-router";

import { ApiError, POLL_INTERVAL_MS } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { useAppStateStatus } from "@/src/shared/lifecycle";
import { colors, radius, spacing, typeScale, weight } from "@/src/shared/theme";
import {
  clipIsPromotable,
  getClipJob,
  isClipJobTerminal,
  listProducedClips,
  promoteProducedClip,
  statusColor,
  type ClipJob,
  type ProducedClip,
  type PromoteResult,
} from "@/lib/repurpose";

import { ClipCandidateCard } from "@/src/features/repurpose/components/ClipCandidateCard";
import { ReelDraftCard } from "@/src/features/repurpose/components/ReelDraftCard";
import { StatusPill } from "@/src/features/repurpose/components/StatusPill";

export default function AutoClipJobScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const appState = useAppStateStatus();

  const [job, setJob] = useState<ClipJob | null>(null);
  const [clips, setClips] = useState<ProducedClip[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [promotingId, setPromotingId] = useState<string | null>(null);
  const [lastPromoted, setLastPromoted] = useState<PromoteResult | null>(null);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    if (!id) {
      setError("This link does not contain a job id.");
      return;
    }
    setError(null);
    try {
      const nextJob = await getClipJob(id, { token });
      setJob(nextJob);
      if (nextJob.clip_count > 0 || isClipJobTerminal(nextJob.state)) {
        const nextClips = await listProducedClips(id, { token });
        setClips(nextClips);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load this job.");
    }
  }, [id, token]);

  // Initial load.
  useEffect(() => {
    let active = true;
    setLoading(true);
    load().finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [load]);

  // Poll while foregrounded and not terminal.
  useEffect(() => {
    if (appState !== "active") return undefined;
    if (!job || isClipJobTerminal(job.state)) return undefined;
    timerRef.current = setTimeout(() => {
      void load();
    }, POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [appState, job, load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const doPromote = useCallback(
    async (clip: ProducedClip) => {
      setPromotingId(clip.id);
      try {
        const result = await promoteProducedClip(clip.id, { token });
        setLastPromoted(result);
        setClips((prev) =>
          prev.map((c) => (c.id === clip.id ? { ...c, status: "promoted" } : c)),
        );
      } catch (err) {
        Alert.alert(
          "Couldn't promote",
          err instanceof ApiError ? err.message : "Failed to promote this clip.",
        );
      } finally {
        setPromotingId(null);
      }
    },
    [token],
  );

  const onPromote = useCallback(
    (clip: ProducedClip) => {
      Alert.alert(
        "Promote to reel?",
        "This creates a ready-to-submit reel draft from the short. No credits are spent until you submit it.",
        [
          { text: "Cancel", style: "cancel" },
          { text: "Promote", onPress: () => void doPromote(clip) },
        ],
      );
    },
    [doPromote],
  );

  if (loading && !job) {
    return (
      <View style={[styles.container, styles.center]}>
        <Stack.Screen options={{ title: "Auto-Clip Job" }} />
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  if (!job) {
    return (
      <View style={[styles.container, styles.center]}>
        <Stack.Screen options={{ title: "Auto-Clip Job" }} />
        <Text style={styles.errorTitle}>Job unavailable</Text>
        <Text style={styles.errorBody}>{error ?? "This job could not be loaded."}</Text>
        <Pressable style={styles.retryBtn} onPress={() => void onRefresh()}>
          <Text style={styles.retryText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  const terminal = isClipJobTerminal(job.state);
  const progress = Math.max(0, Math.min(100, job.progress));
  const color = statusColor(job.state);

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
      <Stack.Screen options={{ title: "Auto-Clip Job" }} />

      <View style={styles.headerRow}>
        <Text style={styles.title}>Auto-clip · {job.language}</Text>
        <StatusPill label={job.state} color={color} />
      </View>

      <View style={styles.progressTrack}>
        <View
          style={[styles.progressFill, { width: `${progress}%`, backgroundColor: color }]}
        />
      </View>
      <Text style={styles.meta}>
        {progress}% · {job.clip_count}/{job.target_count} shorts
        {terminal ? "" : " · working…"}
      </Text>
      {job.error ? <Text style={styles.error}>{job.error}</Text> : null}

      {lastPromoted ? (
        <View style={styles.promotedBlock}>
          <ReelDraftCard draft={lastPromoted.reel_draft} />
        </View>
      ) : null}

      <Text style={styles.sectionTitle}>
        Produced shorts{clips.length > 0 ? ` (${clips.length})` : ""}
      </Text>

      {clips.length === 0 ? (
        <Text style={styles.empty}>
          {terminal
            ? "This job produced no shorts. Try a longer source or a lower score floor."
            : "Shorts will appear here as the worker finishes them."}
        </Text>
      ) : (
        <View style={styles.clipList}>
          {clips.map((clip) => (
            <ClipCandidateCard
              key={clip.id}
              title={clip.title}
              hook={clip.hook}
              reason={clip.reason}
              transcript={clip.transcript}
              startS={clip.start_s}
              endS={clip.end_s}
              score={clip.score}
              status={clip.status}
              promotable={clipIsPromotable(clip.status)}
              promoting={promotingId === clip.id}
              onPromote={() => onPromote(clip)}
            />
          ))}
        </View>
      )}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, gap: spacing.sm },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xxl,
    gap: spacing.md,
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
    fontWeight: weight.bold,
    flex: 1,
  },
  progressTrack: {
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.surfaceMuted,
    overflow: "hidden",
    marginTop: spacing.sm,
  },
  progressFill: { height: 8 },
  meta: { color: colors.textFaint, fontSize: typeScale.micro, marginTop: spacing.xs },
  promotedBlock: { marginTop: spacing.md },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: weight.bold,
    marginTop: spacing.md,
  },
  clipList: { gap: spacing.md, marginTop: spacing.xs },
  empty: {
    color: colors.textFaint,
    fontSize: typeScale.caption,
    lineHeight: 20,
    paddingVertical: spacing.lg,
    textAlign: "center",
  },
  error: { color: colors.danger, fontSize: typeScale.caption, lineHeight: 18 },
  errorTitle: {
    color: colors.danger,
    fontSize: typeScale.heading,
    fontWeight: weight.black,
  },
  errorBody: {
    color: colors.textPrimary,
    fontSize: typeScale.caption,
    textAlign: "center",
    lineHeight: 20,
  },
  retryBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  retryText: {
    color: colors.textPrimary,
    fontSize: typeScale.caption,
    fontWeight: weight.semibold,
  },
  spacer: { height: 48 },
});
