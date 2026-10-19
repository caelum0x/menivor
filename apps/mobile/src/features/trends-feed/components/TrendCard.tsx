/**
 * A single row in the Trends Feed. Renders a backend-scored trend (from the
 * durable recommended feed or an ad-hoc ranked candidate) with its opportunity
 * bar, lifecycle phase, saturation, and a "recommend" badge. The primary CTA
 * deep-links to the Compose screen (Group A) so a creator can build to the sound
 * before it peaks. Presentational only — no data fetching lives here.
 */

import * as React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";

/**
 * The minimal, normalized shape a card needs. Both `ObservedTrend` (feed) and
 * `ScoredTrend` (ranked candidate) from `@/lib/trends` are assignable to it, so
 * one card renders either source. `label` is optional (ranked rows omit it).
 */
export interface TrendCardData {
  id?: string | number;
  trend_id: string;
  opportunity: number;
  saturation: number;
  phase: string;
  recommend: boolean;
  label?: string;
}

interface TrendCardProps {
  trend: TrendCardData;
  onCompose: (trend: TrendCardData) => void;
  onForecast?: (trend: TrendCardData) => void;
}

/** Clamp a 0..1 ratio and render it as an integer percentage (RN dimension). */
function pct(ratio: number): `${number}%` {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(ratio) ? ratio : 0));
  return `${Math.round(clamped * 100)}%`;
}

/** Opportunity → color: green (build now), amber (watch), muted (late). */
function opportunityColor(opportunity: number): string {
  if (opportunity >= 0.66) return colors.success;
  if (opportunity >= 0.4) return colors.accent;
  return "#fbbf24";
}

function TrendCardBase({ trend, onCompose, onForecast }: TrendCardProps) {
  const title = trend.label?.trim() ? trend.label : trend.trend_id;
  const oppColor = opportunityColor(trend.opportunity);

  return (
    <View style={styles.card} testID={`trend-card-${trend.trend_id}`}>
      <View style={styles.headerRow}>
        <Text style={styles.title} numberOfLines={1}>
          {title}
        </Text>
        {trend.recommend ? (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>BUILD</Text>
          </View>
        ) : null}
      </View>

      <Text style={styles.phase}>
        {trend.phase} · saturation {pct(trend.saturation)}
      </Text>

      <View style={styles.meterRow}>
        <View style={styles.meterTrack}>
          <View
            style={[
              styles.meterFill,
              { width: pct(trend.opportunity), backgroundColor: oppColor },
            ]}
          />
        </View>
        <Text style={[styles.meterValue, { color: oppColor }]}>
          {pct(trend.opportunity)}
        </Text>
      </View>
      <Text style={styles.meterLabel}>opportunity</Text>

      <Pressable
        style={styles.cta}
        accessibilityRole="button"
        accessibilityLabel={`Create a reel for ${title}`}
        onPress={() => onCompose(trend)}
      >
        <Text style={styles.ctaText}>Create reel</Text>
      </Pressable>
      {trend.id && onForecast ? (
        <Pressable style={styles.forecastCta} onPress={() => onForecast(trend)}>
          <Text style={styles.forecastCtaText}>Forecast this trend</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export const TrendCard = React.memo(TrendCardBase);

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
    gap: 8,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  title: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "700",
    flexShrink: 1,
  },
  badge: {
    backgroundColor: "rgba(74, 222, 128, 0.16)",
    borderColor: colors.success,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  badgeText: {
    color: colors.success,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.5,
  },
  phase: {
    color: colors.textSecondary,
    fontSize: 13,
    textTransform: "capitalize",
  },
  meterRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginTop: 2,
  },
  meterTrack: {
    flex: 1,
    height: 8,
    borderRadius: 999,
    backgroundColor: colors.cardAlt,
    overflow: "hidden",
  },
  meterFill: {
    height: "100%",
    borderRadius: 999,
  },
  meterValue: {
    fontSize: 14,
    fontWeight: "800",
    width: 46,
    textAlign: "right",
  },
  meterLabel: {
    color: colors.muted,
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  cta: {
    marginTop: 8,
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 10,
    alignItems: "center",
  },
  ctaText: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: "700",
  },
  forecastCta: { borderColor: colors.primary, borderWidth: 1, borderRadius: 10, paddingVertical: 10, alignItems: "center" },
  forecastCtaText: { color: colors.primary, fontSize: 13, fontWeight: "700" },
});
