/**
 * WINNING TEMPLATES — the caller's reel templates ranked by a deterministic
 * `win_score` over the reels they've logged (GET /me/winning-templates). This
 * is the template-level companion to the hook-level leaderboard on
 * app/performance.tsx: it answers "which of my templates actually convert?".
 *
 * Everything is STRICTLY caller-scoped: the auth token comes from the session
 * and is sent as `x-api-key` by the shared api client — no secrets live here.
 * The backend clamps `limit` to 1..100; the on-screen selector picks how many
 * rows to request. A rolled-up summary (templates / reels / views / avg
 * retention) sits above the ranked list. Pull-to-refresh and a Try-again button
 * cover the refresh/error paths; an explicit empty state guides new creators.
 *
 * Nav manifest (for the integration agent to register in app/_layout.tsx):
 *   { route: "/insights/winning-templates", title: "Winning Templates" }
 */

import { useCallback, useMemo, useState } from "react";
import type { ReactElement } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack } from "expo-router";

import { getWinningTemplates } from "@/lib/api";
import type { WinningTemplate } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

import { Section, SectionState } from "@/components/me/Section";
import { StatCard } from "@/components/me/StatCard";
import { formatCount } from "@/components/me/format";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { WinningTemplateCard } from "@/components/performance/WinningTemplateCard";
import { formatPct } from "@/components/performance/format";

/** Selectable row counts; every option is inside the backend 1..100 clamp. */
const LIMIT_OPTIONS = [10, 25, 50] as const;
type LimitOption = (typeof LIMIT_OPTIONS)[number];

/** A safe non-negative integer, or 0 for a NaN/undefined backend field. */
function safeCount(value: number): number {
  return Number.isFinite(value) && value > 0 ? value : 0;
}

/** Roll the ranked rows up into headline totals for the summary cards. */
function summarize(rows: readonly WinningTemplate[]): {
  templates: number;
  reels: number;
  views: number;
  avgRetentionPct: number;
} {
  const templates = rows.length;
  let reels = 0;
  let views = 0;
  let retentionSum = 0;
  let retentionRows = 0;
  for (const row of rows) {
    reels += safeCount(row.reels);
    views += safeCount(row.views);
    if (Number.isFinite(row.avg_retention_pct)) {
      retentionSum += Math.max(0, Math.min(100, row.avg_retention_pct));
      retentionRows += 1;
    }
  }
  return {
    templates,
    reels,
    views,
    avgRetentionPct: retentionRows > 0 ? retentionSum / retentionRows : 0,
  };
}

export default function WinningTemplatesScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [limit, setLimit] = useState<LimitOption>(25);
  const [refreshing, setRefreshing] = useState(false);

  const fetcher = useCallback(
    () => getWinningTemplates(limit, { token }),
    [limit, token],
  );
  const templates = useResource<WinningTemplate[]>(fetcher);

  const rows = templates.data ?? [];
  const summary = useMemo(() => summarize(rows), [rows]);

  const onRefresh = useCallback((): void => {
    setRefreshing(true);
    templates.reload();
  }, [templates]);

  // Clear the pull-to-refresh spinner once a load settles (ready or error).
  if (refreshing && templates.status !== "loading") {
    setRefreshing(false);
  }

  return (
    <>
      <Stack.Screen options={{ title: "Winning Templates", presentation: "card" }} />
      <ScrollView
        style={styles.container}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.accent}
          />
        }
      >
        <Text style={styles.pageTitle}>Winning templates</Text>
        <Text style={styles.pageSub}>
          Your reel templates ranked by a deterministic win score over the reels
          you&apos;ve logged. Higher-scoring templates bias Spark to reuse the
          structures that actually convert for you.
        </Text>

        <View style={styles.selectorRow}>
          <Text style={styles.selectorLabel}>SHOW TOP</Text>
          <View style={styles.segments}>
            {LIMIT_OPTIONS.map((option) => {
              const active = option === limit;
              return (
                <Pressable
                  key={option}
                  style={[styles.segment, active ? styles.segmentActive : null]}
                  onPress={() => setLimit(option)}
                  accessibilityRole="button"
                  accessibilityState={{ selected: active }}
                >
                  <Text
                    style={[
                      styles.segmentText,
                      active ? styles.segmentTextActive : null,
                    ]}
                  >
                    {option}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        <Section title="ACROSS THESE TEMPLATES">
          <SectionState
            status={templates.status}
            error={templates.error}
            onRetry={templates.reload}
            loadingLabel="Loading winning templates…"
          >
            {rows.length > 0 ? (
              <View style={styles.grid}>
                <StatCard
                  label="Templates"
                  value={formatCount(summary.templates)}
                  hint="Ranked in this view"
                  accent={colors.accent}
                />
                <StatCard
                  label="Reels logged"
                  value={formatCount(summary.reels)}
                  hint="Backing these templates"
                />
                <StatCard
                  label="Total views"
                  value={formatCount(summary.views)}
                  hint="Across logged reels"
                  accent={colors.success}
                />
                <StatCard
                  label="Avg retention"
                  value={formatPct(summary.avgRetentionPct)}
                  hint="Mean watch-through"
                  accent={colors.primary}
                />
              </View>
            ) : (
              <Text style={styles.muted}>
                No template performance yet. Log a few finished reels on the Hook
                Performance screen and your best-converting templates will rank
                here.
              </Text>
            )}
          </SectionState>
        </Section>

        <Section title="RANKED BY WIN SCORE">
          <SectionState
            status={templates.status}
            error={templates.error}
            onRetry={templates.reload}
            loadingLabel="Loading winning templates…"
          >
            {rows.length > 0 ? (
              <View style={styles.list}>
                {rows.map((template, i) => (
                  <WinningTemplateCard
                    key={`${template.template || "template"}-${i}`}
                    template={template}
                    rank={i + 1}
                  />
                ))}
              </View>
            ) : (
              <Text style={styles.muted}>
                Nothing to rank yet — log reels to build this leaderboard.
              </Text>
            )}
          </SectionState>
        </Section>

        <Text style={styles.footNote}>
          Showing your top {limit} · pull down to refresh
        </Text>
        <View style={styles.spacer} />
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20 },
  pageTitle: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  pageSub: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 19,
    marginTop: 4,
    marginBottom: 20,
  },
  selectorRow: { gap: 10, marginBottom: 24 },
  selectorLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
  },
  segments: {
    flexDirection: "row",
    gap: 8,
  },
  segment: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    backgroundColor: colors.card,
    paddingHorizontal: 18,
    paddingVertical: 8,
  },
  segmentActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  segmentText: { color: colors.textSecondary, fontSize: 14, fontWeight: "700" },
  segmentTextActive: { color: colors.bg },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  list: { gap: 12 },
  muted: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  footNote: {
    color: colors.muted,
    fontSize: 12,
    textAlign: "center",
    marginTop: 4,
  },
  spacer: { height: 40 },
});
