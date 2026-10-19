/**
 * Creator dashboard — a richer BI view over the caller's own ReelForge activity
 * (jobs / job_events / credit_ledger). All figures are STRICTLY per-user; the
 * shared api client sends the session key as `x-api-key`, and every metric is
 * computed server-side scoped to that user. No secrets live here.
 *
 * The screen owns its loading + error state via {@link useResource} and lets the
 * creator pick a trailing window (7 / 30 / 90 days). Charts are plain RN Views
 * (proportional bars) — no chart library.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { getAnalytics } from "@/lib/api";
import { useSession } from "@/src/shared/auth";
import type { Analytics } from "@/lib/types";
import type { ForecastTraceItem } from "@/lib/types";

import { Section } from "@/components/me/Section";
import { StatCard } from "@/components/me/StatCard";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

import { BreakdownList } from "@/components/analytics/BreakdownList";
import { DaysSelector, type DayOption } from "@/components/analytics/DaysSelector";
import { Funnel } from "@/components/analytics/Funnel";
import { RenderTimeCard } from "@/components/analytics/RenderTimeCard";
import { TimeSeriesBars } from "@/components/analytics/TimeSeriesBars";
import {
  formatCount,
  formatUsd,
} from "@/components/analytics/format";

export default function AnalyticsScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [days, setDays] = useState<DayOption>(30);

  const fetcher = useCallback(
    () => getAnalytics(days, { token }),
    [days, token],
  );
  const { status, data, error, reload } = useResource<Analytics>(fetcher);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <View style={styles.selectorRow}>
        <Text style={styles.windowLabel}>Trailing window</Text>
        <DaysSelector
          value={days}
          onChange={setDays}
          disabled={status === "loading"}
        />
      </View>

      {status === "loading" ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} size="large" />
        </View>
      ) : status === "error" ? (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>
            {error || "Failed to load your dashboard."}
          </Text>
          <Pressable style={styles.retry} onPress={reload}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : data ? (
        <Dashboard analytics={data} days={days} />
      ) : null}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

function Dashboard({ analytics, days }: { analytics: Analytics; days: number }) {
  const windowHint = `Last ${days} days`;
  return (
    <View style={styles.dashboard}>
      <View style={styles.tiles}>
        <StatCard
          label="Credits balance"
          value={formatCount(analytics.credits_balance)}
          hint="Current balance"
        />
        <StatCard
          label="Credits burned"
          value={formatCount(analytics.credits_burned)}
          hint={windowHint}
          accent={colors.error}
        />
        <StatCard
          label="Render spend"
          value={formatUsd(analytics.total_cost_usd)}
          hint={windowHint}
          accent={colors.accent}
        />
        <StatCard
          label="Published"
          value={formatCount(analytics.funnel.published)}
          hint={windowHint}
          accent={colors.success}
        />
      </View>

      <Section title="FUNNEL">
        <Funnel funnel={analytics.funnel} />
      </Section>

      <Section title="TREND → PUBLISH">
        <Funnel funnel={analytics.trend_funnel} />
        <View style={styles.trendList}>
          {analytics.trend_funnel.by_trend.length === 0 ? (
            <Text style={styles.trendEmpty}>No trend-attributed renders in this window yet.</Text>
          ) : analytics.trend_funnel.by_trend.slice(0, 8).map((trend) => (
            <View style={styles.trendRow} key={trend.key}>
              <Text style={styles.trendName} numberOfLines={1}>{trend.label || trend.key}</Text>
              <Text style={styles.trendCounts}>{trend.created} create · {trend.completed} render · {trend.published} publish</Text>
            </View>
          ))}
        </View>
      </Section>

      <Section title="FORECAST TRACE">
        {analytics.forecast_trace.status === "unavailable" ? (
          <Text style={styles.trendEmpty}>Forecast measurement is unavailable until storage is ready.</Text>
        ) : analytics.forecast_trace.traces.length === 0 ? (
          <Text style={styles.trendEmpty}>No trend-bound forecasts in this window yet.</Text>
        ) : (
          <View style={styles.traceList}>
            {analytics.forecast_trace.traces.slice(0, 8).map((trace) => (
              <ForecastRail key={`${trace.forecast_id}-${trace.job_id || "unstarted"}`} trace={trace} />
            ))}
          </View>
        )}
        {analytics.forecast_trace.by_content_type.length > 0 ? (
          <View style={styles.comparisonList}>
            {analytics.forecast_trace.by_content_type.map((row) => (
              <View style={styles.comparisonRow} key={row.content_type}>
                <Text style={styles.comparisonType}>{row.content_type.replace(/_/g, " ")}</Text>
                {row.measured > 0 ? (
                  <Text style={styles.comparisonValue}>
                    expected {formatCount(row.expected_reach || 0)} · actual {formatCount(row.actual_reach || 0)} · delta {formatSigned(row.delta)}
                  </Text>
                ) : (
                  <Text style={styles.pending}>veri bekleniyor</Text>
                )}
                {row.pending > 0 ? <Text style={styles.pending}>{row.pending} forecast: veri bekleniyor</Text> : null}
              </View>
            ))}
          </View>
        ) : null}
      </Section>

      <Section title="COST OVER TIME">
        <TimeSeriesBars
          points={analytics.cost_by_day}
          color={colors.accent}
          formatValue={formatUsd}
          peakLabel="spend"
          emptyLabel="No render spend in this window yet."
        />
      </Section>

      <Section title="CREDITS BURN RATE">
        <TimeSeriesBars
          points={analytics.credits_burn_by_day}
          color={colors.error}
          formatValue={formatCount}
          peakLabel="burn"
          emptyLabel="No credits spent in this window yet."
        />
      </Section>

      <Section title="RENDER TIME (COMPOSE)">
        <RenderTimeCard stats={analytics.render_time} />
      </Section>

      <Section title="BY LAYOUT">
        <BreakdownList
          items={analytics.by_layout}
          color={colors.primary}
          emptyLabel="No layout data in this window yet."
        />
      </Section>

      <Section title="BY LANGUAGE">
        <BreakdownList
          items={analytics.by_language}
          color={colors.accent}
          emptyLabel="No language data in this window yet."
        />
      </Section>

      <Section title="BY VARIANTS">
        <BreakdownList
          items={analytics.by_variants}
          color={colors.success}
          emptyLabel="No variant data in this window yet."
        />
      </Section>

      <Section title="TOP HOOKS & TEMPLATES">
        <BreakdownList
          items={analytics.top_hooks}
          color={colors.primary}
          limit={8}
          emptyLabel="No hooks or templates counted yet."
        />
      </Section>
    </View>
  );
}

function formatSigned(value: number | null): string {
  if (value === null) return "veri bekleniyor";
  return `${value > 0 ? "+" : ""}${formatCount(value)}`;
}

function ForecastRail({ trace }: { trace: ForecastTraceItem }) {
  const points = [
    { label: "Trend observation", value: trace.trend_label },
    { label: "Forecast", value: `${trace.forecast_id} · expected ${formatCount(trace.expected_reach)}` },
    { label: "Render", value: trace.job_id ? `${trace.job_state} · ${trace.job_id}` : "not started" },
    { label: "Native publish", value: trace.publish_status === "not_started" ? "not started" : `${trace.publish_status}${trace.publish_platform ? ` · ${trace.publish_platform}` : ""}` },
    { label: "Reach", value: trace.measurement_status === "measured" ? `${formatCount(trace.actual_reach || 0)} · delta ${formatSigned(trace.delta)}` : "veri bekleniyor" },
  ];
  return (
    <View style={styles.traceCard}>
      <Text style={styles.traceContentType}>{trace.content_type.replace(/_/g, " ")}</Text>
      {points.map((point, index) => (
        <View style={styles.tracePoint} key={point.label}>
          <View style={styles.traceMarkerColumn}>
            <View style={styles.traceDot} />
            {index < points.length - 1 ? <View style={styles.traceLine} /> : null}
          </View>
          <View style={styles.traceCopy}>
            <Text style={styles.traceLabel}>{point.label}</Text>
            <Text style={point.value === "veri bekleniyor" ? styles.pending : styles.traceValue}>{point.value}</Text>
          </View>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 20 },
  selectorRow: { gap: 10, marginBottom: 24 },
  windowLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
  },
  dashboard: { gap: 4 },
  trendList: { marginTop: 14, borderTopColor: colors.border, borderTopWidth: 1 },
  trendRow: { paddingVertical: 11, borderBottomColor: colors.border, borderBottomWidth: 1, gap: 3 },
  trendName: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  trendCounts: { color: colors.muted, fontSize: 12 },
  trendEmpty: { color: colors.muted, fontSize: 13, paddingVertical: 14 },
  traceList: { gap: 12 },
  traceCard: { backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1, borderRadius: 12, padding: 14 },
  traceContentType: { color: colors.primary, fontSize: 11, fontWeight: "800", textTransform: "uppercase", marginBottom: 10 },
  tracePoint: { flexDirection: "row", minHeight: 50 },
  traceMarkerColumn: { width: 20, alignItems: "center" },
  traceDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.primary, marginTop: 4 },
  traceLine: { width: 1, flex: 1, backgroundColor: colors.border, marginVertical: 4 },
  traceCopy: { flex: 1, paddingBottom: 10 },
  traceLabel: { color: colors.muted, fontSize: 10, fontWeight: "700", textTransform: "uppercase" },
  traceValue: { color: colors.textPrimary, fontSize: 12, marginTop: 3 },
  pending: { color: colors.accent, fontSize: 12, marginTop: 3 },
  comparisonList: { borderTopColor: colors.border, borderTopWidth: 1, marginTop: 16 },
  comparisonRow: { paddingVertical: 12, borderBottomColor: colors.border, borderBottomWidth: 1 },
  comparisonType: { color: colors.textPrimary, fontSize: 13, fontWeight: "700", textTransform: "capitalize" },
  comparisonValue: { color: colors.textSecondary, fontSize: 12, marginTop: 4 },
  tiles: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
    marginBottom: 28,
  },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 80 },
  errorBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
    alignItems: "flex-start",
  },
  errorText: { color: colors.error, fontSize: 14 },
  retry: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  retryText: { color: colors.textSecondary, fontWeight: "600" },
  spacer: { height: 40 },
});
