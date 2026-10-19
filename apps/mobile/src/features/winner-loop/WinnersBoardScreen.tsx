/**
 * Winners board: projects whose variants produced a winner, loops still
 * collecting data, and recent multi-variant projects that can join the loop.
 * Each row opens the loop detail (ranking, why it won, remake).
 *
 * The native port of apps/web/src/features/insights/WinnersBoard.tsx.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useFocusEffect, useRouter } from "expo-router";

import { Badge, Button, Icon } from "@/components/ui";
import { isAbortError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, kicker, radius, spacing, typeScale } from "@/src/shared/theme";

import { getLoopBoard } from "./api";
import {
  MODE_LABELS,
  errorMessageOf,
  formatCount,
  formatPct,
  isCollecting,
  platformLabel,
  relativeTime,
  statusLabel,
} from "./format";
import type { LoopBoard, LoopCandidate, LoopSummary } from "./types";

const detailHref = (batchId: string) => `/insights/winners/${encodeURIComponent(batchId)}`;

export function WinnersBoardScreen() {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [board, setBoard] = useState<LoopBoard | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        setBoard(await getLoopBoard({ token, signal }));
        setError("");
      } catch (err) {
        if (isAbortError(err)) return;
        setError(errorMessageOf(err, "Couldn't load your winners."));
      } finally {
        setRefreshing(false);
      }
    },
    [token],
  );

  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      void load(controller.signal);
      return () => controller.abort();
    }, [load]),
  );

  const open = (batchId: string) => router.push(detailHref(batchId) as never);
  const active = board?.loops.filter((loop) => !loop.winner_job_id) ?? [];

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true);
            void load();
          }}
          tintColor={colors.accent}
        />
      }
    >
      <Text style={styles.kicker}>Winner loop</Text>
      <Text style={styles.title}>Which hook won</Text>
      <Text style={styles.muted}>
        Every 3-variant run is a hook test. Once the variants have been live long enough, the loop
        ranks them on real views, watch time and engagement, explains why the winner won, and can
        remake it as 3 new variants.
      </Text>

      {error ? (
        <View style={styles.notice}>
          <Text style={[styles.error, styles.flex]}>{error}</Text>
          <Button label="Retry" size="sm" variant="secondary" onPress={() => void load()} />
        </View>
      ) : null}
      {!board && !error ? <ActivityIndicator color={colors.accent} style={styles.spinner} /> : null}

      {board ? (
        <>
          <View style={styles.sectionHead}>
            <Icon name="trophy-outline" size={18} color={colors.accent} />
            <Text style={styles.sectionTitle}>Winners</Text>
          </View>
          {board.winners.length === 0 ? (
            <Text style={styles.muted}>
              No winners yet. A winner is picked once at least two variants have been live long
              enough to compare (48 hours by default).
            </Text>
          ) : (
            board.winners.map((loop) => (
              <WinnerCard key={loop.batch_id} loop={loop} onPress={() => open(loop.batch_id)} />
            ))
          )}

          <View style={styles.sectionHead}>
            <Icon name="layers-outline" size={18} color={colors.textSecondary} />
            <Text style={styles.sectionTitle}>Loops in progress</Text>
          </View>
          {active.length === 0 ? (
            <Text style={styles.muted}>No loops running.</Text>
          ) : (
            active.map((loop) => <LoopRow key={loop.batch_id} loop={loop} onPress={() => open(loop.batch_id)} />)
          )}

          <View style={styles.sectionHead}>
            <Icon name="add-circle-outline" size={18} color={colors.textSecondary} />
            <Text style={styles.sectionTitle}>Start a loop</Text>
          </View>
          <Text style={styles.muted}>
            Projects from the last 60 days with at least two variants. Remaking a winner renders 3
            new variants for {board.remake_cost_credits} credits.
          </Text>
          {board.candidates.length === 0 ? (
            <View style={styles.notice}>
              <Text style={[styles.muted, styles.flex]}>
                Make a reel with 3 hook variants to compare, then come back here.
              </Text>
              <Button label="Make 3 reels" size="sm" onPress={() => router.push("/(tabs)/create" as never)} />
            </View>
          ) : (
            board.candidates.map((candidate) => (
              <CandidateRow
                key={candidate.batch_id}
                candidate={candidate}
                onPress={() => open(candidate.batch_id)}
              />
            ))
          )}
        </>
      ) : null}
    </ScrollView>
  );
}

function WinnerCard({ loop, onPress }: Readonly<{ loop: LoopSummary; onPress: () => void }>) {
  return (
    <Pressable style={styles.card} onPress={onPress} accessibilityRole="button" accessibilityLabel={`Open ${loop.title}`}>
      <View style={styles.rowBetween}>
        <Text style={[styles.meta, styles.flex]} numberOfLines={1}>
          {loop.title} · round {loop.generation}
        </Text>
        <Badge
          label={loop.confidence === "high" ? "Clear winner" : "Low confidence"}
          variant={loop.confidence === "high" ? "success" : "neutral"}
        />
      </View>
      <Text style={styles.hook} numberOfLines={3}>
        {loop.winner_hook || "Winning variant"}
      </Text>
      {loop.headline ? (
        <Text style={styles.muted} numberOfLines={2}>
          {loop.headline}
        </Text>
      ) : null}
      <View style={styles.metrics}>
        <Metric label="Views" value={formatCount(loop.winner_views)} />
        <Metric label="Avg watch" value={formatPct(loop.winner_avg_watch_frac)} />
        <Metric label="Engagement" value={formatPct(loop.winner_engagement_rate)} />
      </View>
      <Text style={styles.meta}>
        {loop.remake_batch_id
          ? "Remade into 3 new variants"
          : loop.mode === "auto" && loop.conclusive
            ? "Auto remake pending"
            : "Ready to remake"}
      </Text>
    </Pressable>
  );
}

function LoopRow({ loop, onPress }: Readonly<{ loop: LoopSummary; onPress: () => void }>) {
  const due = loop.check_due_at && isCollecting(loop.status) ? relativeTime(loop.check_due_at) : "";
  return (
    <Pressable style={styles.row} onPress={onPress} accessibilityRole="button" accessibilityLabel={`Open ${loop.title}`}>
      <View style={styles.flex}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {loop.title}
        </Text>
        <Text style={styles.meta}>
          Round {loop.generation} · {loop.variant_count} variants ·{" "}
          {loop.platforms.length ? loop.platforms.map(platformLabel).join(", ") : "You post"}
          {due ? ` · check ${due}` : ""}
        </Text>
        <View style={styles.badges}>
          <Badge label={MODE_LABELS[loop.mode] ?? loop.mode} />
          <Badge label={statusLabel(loop.status)} variant={loop.status === "winner_ready" ? "success" : "neutral"} />
        </View>
      </View>
      <Icon name="chevron-forward" size={18} color={colors.textSecondary} />
    </Pressable>
  );
}

function CandidateRow({ candidate, onPress }: Readonly<{ candidate: LoopCandidate; onPress: () => void }>) {
  return (
    <Pressable style={styles.row} onPress={onPress} accessibilityRole="button" accessibilityLabel={`Set up a loop for ${candidate.title}`}>
      <View style={styles.flex}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {candidate.title}
        </Text>
        <Text style={styles.meta}>
          {candidate.complete_count} of {candidate.variant_count} variants rendered
          {candidate.created_at ? ` · ${relativeTime(candidate.created_at)}` : ""}
        </Text>
      </View>
      <Text style={styles.link}>Set up loop</Text>
      <Icon name="chevron-forward" size={18} color={colors.accent} />
    </Pressable>
  );
}

function Metric({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: 48 },
  kicker,
  title: { color: colors.textPrimary, fontSize: typeScale.heading, fontWeight: "800" },
  spinner: { marginVertical: spacing.xl },
  sectionHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.lg },
  sectionTitle: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700" },
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.sm,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
  },
  rowBetween: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  rowTitle: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700" },
  badges: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginTop: spacing.xs },
  hook: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700", lineHeight: 21 },
  metrics: { flexDirection: "row", gap: spacing.sm },
  metric: {
    flex: 1,
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
    alignItems: "center",
  },
  metricLabel: { color: colors.textSecondary, fontSize: typeScale.micro },
  metricValue: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700" },
  notice: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.lg,
    padding: spacing.md,
  },
  flex: { flex: 1 },
  meta: { color: colors.textSecondary, fontSize: typeScale.micro + 1, lineHeight: 17 },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  error: { color: colors.danger, fontSize: typeScale.caption },
  link: { color: colors.accent, fontSize: typeScale.caption, fontWeight: "700" },
});
