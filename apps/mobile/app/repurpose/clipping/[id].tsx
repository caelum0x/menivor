/**
 * Route: /repurpose/clipping/[id] — an AI-highlight (repurpose) job detail.
 *
 * NAV MANIFEST:
 *   { route: "/repurpose/clipping/[id]", title: "Repurpose Job" }
 *
 * Shows the job's status + source, lets the creator RANK its transcript into
 * AI-scored highlight candidates (with confirmation), lists those candidates
 * newest-highest-score first, and promotes any candidate into a ready-to-submit
 * reel draft (with confirmation). Pull-to-refresh re-loads job + clips.
 * Comprehensive loading / empty / error states.
 *
 * Auth flows through the shared api client (x-api-key); writes carry an
 * Idempotency-Key. No secrets here.
 */

import { useCallback, useState } from "react";
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
} from "expo-router";

import { ApiError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, radius, spacing, typeScale, weight } from "@/src/shared/theme";
import {
  clipIsPromotable,
  getRepurposeJob,
  listRepurposeClips,
  promoteRepurposeClip,
  rankRepurposeJob,
  repurposeJobTitle,
  statusColor,
  type PromoteResult,
  type RepurposeClip,
  type RepurposeJob,
} from "@/lib/repurpose";

import { ClipCandidateCard } from "@/src/features/repurpose/components/ClipCandidateCard";
import { ReelDraftCard } from "@/src/features/repurpose/components/ReelDraftCard";
import { StatusPill } from "@/src/features/repurpose/components/StatusPill";
import { GenerationErrorNotice } from "@/components/billing/GenerationErrorNotice";

function newIdempotencyKey(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
}

function byScoreDesc(a: RepurposeClip, b: RepurposeClip): number {
  return b.virality_score - a.virality_score;
}

export default function RepurposeJobScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [job, setJob] = useState<RepurposeJob | null>(null);
  const [clips, setClips] = useState<RepurposeClip[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [ranking, setRanking] = useState(false);
  const [promotingId, setPromotingId] = useState<string | null>(null);
  const [lastPromoted, setLastPromoted] = useState<PromoteResult | null>(null);

  const load = useCallback(async () => {
    if (!id) {
      setError("This link does not contain a job id.");
      return;
    }
    setError(null);
    try {
      const [nextJob, nextClips] = await Promise.all([
        getRepurposeJob(id, { token }),
        listRepurposeClips(id, { token }),
      ]);
      setJob(nextJob);
      setClips([...nextClips].sort(byScoreDesc));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load this job.");
    }
  }, [id, token]);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoading(true);
      load().finally(() => {
        if (active) setLoading(false);
      });
      return () => {
        active = false;
      };
    }, [load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const doRank = useCallback(async () => {
    if (!id || ranking) return;
    setRanking(true);
    setError(null);
    try {
      const ranked = await rankRepurposeJob(
        id,
        {},
        { token, idempotencyKey: newIdempotencyKey("rank") },
      );
      setClips([...ranked].sort(byScoreDesc));
      const refreshed = await getRepurposeJob(id, { token });
      setJob(refreshed);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ranking failed.");
    } finally {
      setRanking(false);
    }
  }, [id, ranking, token]);

  const onRank = useCallback(() => {
    const hasClips = clips.length > 0;
    Alert.alert(
      hasClips ? "Re-rank this job?" : "Rank into highlights?",
      hasClips
        ? "This re-scores the transcript and replaces the current candidate list."
        : "The transcript will be scored 0–100 and split into non-overlapping highlight clips.",
      [
        { text: "Cancel", style: "cancel" },
        { text: hasClips ? "Re-rank" : "Rank now", onPress: () => void doRank() },
      ],
    );
  }, [clips.length, doRank]);

  const doPromote = useCallback(
    async (clip: RepurposeClip) => {
      setPromotingId(clip.id);
      try {
        const result = await promoteRepurposeClip(clip.id, {
          token,
          idempotencyKey: newIdempotencyKey("promote"),
        });
        setLastPromoted(result);
        setClips((prev) =>
          prev.map((c) =>
            c.id === clip.id ? { ...c, status: "promoted" } : c,
          ),
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
    (clip: RepurposeClip) => {
      Alert.alert(
        "Promote to reel?",
        "This creates a ready-to-submit reel draft from the clip. No credits are spent until you submit it.",
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
        <Stack.Screen options={{ title: "Repurpose Job" }} />
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  if (!job) {
    return (
      <View style={[styles.container, styles.center]}>
        <Stack.Screen options={{ title: "Repurpose Job" }} />
        <Text style={styles.errorTitle}>Job unavailable</Text>
        <Text style={styles.errorBody}>{error ?? "This job could not be loaded."}</Text>
        <Pressable style={styles.retryBtn} onPress={() => void onRefresh()}>
          <Text style={styles.retryText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

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
      <Stack.Screen options={{ title: "Repurpose Job" }} />

      <View style={styles.headerRow}>
        <Text style={styles.title} numberOfLines={2}>
          {repurposeJobTitle(job)}
        </Text>
        <StatusPill label={job.status} color={statusColor(job.status)} />
      </View>
      <Text style={styles.source} numberOfLines={1}>
        {job.source_kind} · {job.source_ref}
      </Text>
      {job.error ? <Text style={styles.error}>{job.error}</Text> : null}

      {/* Rank action */}
      <Pressable
        style={[styles.rankBtn, ranking && styles.dim]}
        onPress={onRank}
        disabled={ranking}
        accessibilityRole="button"
        accessibilityLabel="Rank this job's transcript into highlight clips"
        accessibilityState={{ busy: ranking }}
      >
        {ranking ? (
          <ActivityIndicator color={colors.onAccent} />
        ) : (
          <Text style={styles.rankText}>
            {clips.length > 0 ? "Re-rank highlights" : "Rank into highlights"}
          </Text>
        )}
      </Pressable>

      {lastPromoted ? (
        <View style={styles.promotedBlock}>
          <ReelDraftCard draft={lastPromoted.reel_draft} />
        </View>
      ) : null}

      <Text style={styles.sectionTitle}>
        Clip candidates{clips.length > 0 ? ` (${clips.length})` : ""}
      </Text>

      {clips.length === 0 ? (
        <Text style={styles.empty}>
          {ranking
            ? "Ranking your transcript…"
            : "No candidates yet. Rank the transcript to surface AI-scored highlights."}
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
              score={clip.virality_score}
              status={clip.status}
              promotable={clipIsPromotable(clip.status)}
              promoting={promotingId === clip.id}
              onPromote={() => onPromote(clip)}
            />
          ))}
        </View>
      )}

      {job ? <GenerationErrorNotice message={error} style={styles.error} /> : null}
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
  source: { color: colors.textFaint, fontSize: typeScale.micro },
  rankBtn: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 48,
    marginTop: spacing.sm,
  },
  rankText: {
    color: colors.onAccent,
    fontSize: typeScale.body,
    fontWeight: weight.bold,
  },
  dim: { opacity: 0.5 },
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
