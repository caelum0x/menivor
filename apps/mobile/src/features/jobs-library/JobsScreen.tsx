import { useCallback, useMemo, useState } from "react";
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

import { ApiError, jobDisplayName, listJobs } from "@/lib/api";
import {
  REEL_STATUS_FILTERS,
  jobMatchesStatusFilter,
  type ReelStatusFilterId,
} from "@/lib/reels";
import { Icon } from "@/components/ui/Icon";
import { StatusFilterBar } from "@/src/features/reels/components/StatusFilterBar";
import { JobActionsSheet, type JobActionOutcome } from "./components/JobActionsSheet";
import { ContextualLinks } from "@/components/nav/ContextualLinks";
import { jobPosterUrl } from "@/src/shared/media";
import { stateBadge } from "./job-status";
import { useSession } from "@/src/shared/auth";
import { colors, kicker, radius, spacing, typeScale } from "@/src/shared/theme";
import { discardDraft, listDrafts, type ReelDraft } from "@/src/shared/product";
import type { Job } from "@/lib/types";

import { JobPoster } from "@/src/shared/media";
import { ReelCounter, RenderedMoment } from "@/src/ui/menivor";
import { demoNicheFor } from "@/src/shared/release/demo-data";

import { reelsMade } from "./reel-wins";
import { useReelWins } from "./useReelWins";
import { isRouteAvailable } from "@/src/shared/release/surface";

/** Library filters: the status buckets plus the archived shelf. */
type LibraryFilterId = ReelStatusFilterId | "archived";

const LIBRARY_FILTERS: readonly { id: LibraryFilterId; label: string }[] = [
  ...REEL_STATUS_FILTERS,
  { id: "archived", label: "Archived" },
];

function matchesLibraryFilter(job: Job, filter: LibraryFilterId): boolean {
  if (filter === "archived") return job.archived === true;
  if (job.archived === true) return false;
  return jobMatchesStatusFilter(job, filter);
}

/** Human-readable created date for a draft. */
function draftDate(ms: number): string {
  try {
    return new Date(ms).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

export function JobsScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [jobs, setJobs] = useState<Job[]>([]);
  const [drafts, setDrafts] = useState<ReelDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<LibraryFilterId>("all");
  const [managed, setManaged] = useState<Job | null>(null);
  // Only a successful fetch feeds the reels-made counter and win moments, so
  // an empty pre-load list can never trigger (or fake) a milestone.
  const [jobsLoaded, setJobsLoaded] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    // Drafts are device-local and always load, even when the API is down.
    setDrafts(await listDrafts());
    try {
      setJobs(await listJobs({ token }, { includeArchived: true }));
      setJobsLoaded(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load jobs.");
    }
  }, [token]);

  // Refresh whenever the tab regains focus (e.g. after creating a job/draft).
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

  const onDeleteDraft = useCallback(async (id: string) => {
    setDrafts(await discardDraft(id));
  }, []);

  const counts = useMemo(() => {
    const out = {} as Record<LibraryFilterId, number>;
    for (const option of LIBRARY_FILTERS) {
      out[option.id] = jobs.filter((job) => matchesLibraryFilter(job, option.id)).length;
    }
    return out;
  }, [jobs]);
  const visible = useMemo(
    () => jobs.filter((job) => matchesLibraryFilter(job, filter)),
    [jobs, filter],
  );

  const madeCount = useMemo(() => reelsMade(jobs), [jobs]);
  const { win, dismiss: dismissWin } = useReelWins(jobsLoaded ? madeCount : null);

  const onActionDone = useCallback((outcome: JobActionOutcome) => {
    setManaged(null);
    if (outcome.kind === "deleted") {
      setJobs((prev) => prev.filter((job) => job.job_id !== outcome.jobId));
      return;
    }
    setJobs((prev) =>
      prev.map((job) => (job.job_id === outcome.job.job_id ? outcome.job : job)),
    );
  }, []);

  if (loading) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  const filterHeader = (
    <View style={styles.filterRow}>
      {jobsLoaded ? (
        <View style={styles.madeRow} accessible accessibilityLabel={`${madeCount} reels made`}>
          <ReelCounter value={madeCount} style={styles.madeCount} />
          <Text style={styles.madeLabel}>{madeCount === 1 ? "reel made" : "reels made"}</Text>
        </View>
      ) : null}
      <StatusFilterBar
        options={LIBRARY_FILTERS}
        selected={filter}
        counts={counts}
        onSelect={setFilter}
      />
      <View style={styles.shortcutRow}>
        {isRouteAvailable("/scheduled") ? (
          <Pressable
            style={styles.shortcut}
            onPress={() => router.push("/scheduled")}
            accessibilityRole="button"
            accessibilityLabel="Open scheduled publishes"
          >
            <Icon name="calendar-outline" size={14} color={colors.textSecondary} />
            <Text style={styles.shortcutText}>Scheduled</Text>
          </Pressable>
        ) : null}
        <Pressable
          style={styles.shortcut}
          onPress={() => router.push("/uploads")}
          accessibilityRole="button"
          accessibilityLabel="Open your uploads"
        >
          <Icon name="cloud-upload-outline" size={14} color={colors.textSecondary} />
          <Text style={styles.shortcutText}>Uploads</Text>
        </Pressable>
      </View>
      <Text style={styles.hintText}>Long-press a reel to rename, archive, cancel or delete it.</Text>
    </View>
  );

  const header =
    drafts.length > 0 && filter !== "archived" ? (
      <View style={styles.draftsSection}>
        <Text style={styles.kicker}>DRAFTS / ON THIS DEVICE</Text>
        {drafts.map((draft) => (
          <View key={draft.id} style={styles.draftCard}>
            <View style={styles.draftBody}>
              <Text style={styles.draftTitle} numberOfLines={2}>
                {draft.subject || "Untitled draft"}
              </Text>
              <Text style={styles.meta} numberOfLines={1}>
                {draft.media ? draft.media.name : "No clip attached"}
                {"  ·  "}
                {draftDate(draft.createdAt)}
              </Text>
            </View>
            <Pressable
              style={styles.continueBtn}
              onPress={() =>
                router.push({
                  pathname: "/(tabs)/create",
                  params: { draft: draft.id },
                })
              }
              accessibilityRole="button"
              accessibilityLabel={`Continue draft ${draft.subject || draft.id}`}
              hitSlop={8}
            >
              <Text style={styles.continueText}>Continue</Text>
            </Pressable>
            <Pressable
              style={styles.deleteBtn}
              onPress={() => void onDeleteDraft(draft.id)}
              accessibilityRole="button"
              accessibilityLabel={`Delete draft ${draft.subject || draft.id}`}
              hitSlop={8}
            >
              <Text style={styles.deleteText}>Delete</Text>
            </Pressable>
          </View>
        ))}
        <Text style={styles.jobsHeading}>Reels</Text>
        {filterHeader}
      </View>
    ) : (
      filterHeader
    );

  return (
    <>
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      data={visible}
      keyExtractor={(item) => item.job_id}
      ListHeaderComponent={header}
      ListFooterComponent={
        jobs.length > 0 ? (
          <ContextualLinks context="jobs" title="Do more with your reels" />
        ) : null
      }
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.accent}
        />
      }
      ListEmptyComponent={
        <View style={styles.center}>
          <Text style={styles.empty}>
            {error ??
              (jobs.length > 0
                ? "No reels match this filter."
                : drafts.length > 0
                ? "No reels yet. Your drafts are saved above, ready when generation opens."
                : "No reels or drafts yet. Head to Create to start one.")}
          </Text>
        </View>
      }
      renderItem={({ item }) => {
        const badge = stateBadge(item.state);
        return (
          <Pressable
            style={styles.card}
            onPress={() => router.push(`/job/${item.job_id}`)}
            onLongPress={() => setManaged(item)}
            delayLongPress={350}
            accessibilityRole="button"
            accessibilityLabel={`Open reel ${jobDisplayName(item)}`}
            accessibilityHint="Long-press to rename, archive, cancel or delete"
          >
            <JobPoster
              posterUrl={jobPosterUrl(item)}
              seed={item.job_id}
              niche={demoNicheFor(item.job_id)}
              style={styles.thumb}
              accessibilityLabel={`Poster for job ${item.job_id}`}
            />
            <View style={styles.cardBody}>
              <View style={styles.cardHeader}>
                <Text style={styles.jobId} numberOfLines={1}>
                  {jobDisplayName(item)}
                </Text>
                <Text style={[styles.badge, { color: badge.color }]}>
                  {item.cancelled ? "Cancelled" : badge.label}
                </Text>
                <Pressable
                  onPress={() => setManaged(item)}
                  hitSlop={10}
                  accessibilityRole="button"
                  accessibilityLabel={`Manage reel ${jobDisplayName(item)}`}
                >
                  <Icon name="ellipsis-horizontal" size={18} color={colors.textSecondary} />
                </Pressable>
              </View>
              <View style={styles.progressTrack}>
                <View
                  style={[
                    styles.progressFill,
                    {
                      width: `${Math.max(0, Math.min(100, item.progress))}%`,
                      backgroundColor: badge.color,
                    },
                  ]}
                />
              </View>
              <Text style={styles.meta}>{item.progress}%</Text>
            </View>
          </Pressable>
        );
      }}
    />
    <JobActionsSheet
      visible={managed !== null}
      job={managed}
      token={token}
      onClose={() => setManaged(null)}
      onDone={onActionDone}
    />
    <RenderedMoment
      visible={win !== null}
      title={win?.title ?? ""}
      message={win?.message}
      actionLabel="See my reels"
      onDismiss={dismissWin}
    />
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.xl, gap: spacing.md, flexGrow: 1 },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingTop: 80,
  },
  empty: {
    color: colors.textFaint,
    fontSize: typeScale.body,
    textAlign: "center",
    paddingHorizontal: spacing.xl,
  },
  draftsSection: { gap: spacing.sm, marginBottom: spacing.xs },
  filterRow: { gap: spacing.sm, marginBottom: spacing.xs },
  madeRow: { flexDirection: "row", alignItems: "baseline", gap: spacing.sm, marginBottom: spacing.xs },
  madeCount: { color: colors.textPrimary, fontSize: typeScale.display, fontWeight: "700" },
  madeLabel: { color: colors.textSecondary, fontSize: typeScale.body },
  shortcutRow: { flexDirection: "row", gap: spacing.sm },
  shortcut: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  shortcutText: { color: colors.textSecondary, fontSize: typeScale.caption, fontWeight: "600" },
  hintText: { color: colors.textFaint, fontSize: typeScale.micro },
  kicker: { ...kicker },
  draftCard: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  draftBody: { flex: 1, gap: 4 },
  draftTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.body,
    fontWeight: "600",
  },
  continueBtn: {
    backgroundColor: colors.accent,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  continueText: {
    color: colors.onAccent,
    fontSize: typeScale.caption,
    fontWeight: "700",
  },
  deleteBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  deleteText: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    fontWeight: "600",
  },
  jobsHeading: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1,
    marginTop: spacing.md,
  },
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    flexDirection: "row",
    gap: spacing.md,
    alignItems: "center",
  },
  thumb: { width: 54, height: 96, borderRadius: radius.sm },
  cardBody: { flex: 1, gap: spacing.sm },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  jobId: { color: colors.textSecondary, fontSize: typeScale.caption, flex: 1 },
  badge: { fontSize: typeScale.caption, fontWeight: "700" },
  progressTrack: {
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.surfaceMuted,
    overflow: "hidden",
  },
  progressFill: { height: 6 },
  meta: { color: colors.textFaint, fontSize: typeScale.micro },
});
