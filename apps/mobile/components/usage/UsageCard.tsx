/**
 * A single API-key usage row: the caller's label, the non-secret `prefix` (so
 * they can recognise which key this is), and the key's current-month request
 * usage against its monthly quota — with a progress bar when a cap exists and an
 * "Unlimited" treatment when it does not. Purely presentational; the raw key is
 * NEVER available here (the server only ever returned its hash), so a card can
 * only show the safe `prefix`.
 */

import { StyleSheet, Text, View } from "react-native";

import type { ApiKeyUsage } from "@/lib/types";

import { formatCount } from "@/components/me/format";
import { colors } from "@/components/me/theme";

import { formatPeriod, usageRatio } from "./format";

interface UsageCardProps {
  usage: ApiKeyUsage;
}

/** Colour the progress bar red as it nears/exceeds the quota, else green→violet. */
function barColor(ratio: number): string {
  if (ratio >= 0.9) return colors.error;
  if (ratio >= 0.7) return colors.accent;
  return colors.success;
}

/** Requests left this month: prefer the server value, else derive it defensively. */
function remainingLabel(usage: ApiKeyUsage): string | null {
  const quota = usage.monthly_quota;
  if (typeof quota !== "number" || !Number.isFinite(quota) || quota <= 0) {
    return null;
  }
  const remaining =
    typeof usage.remaining === "number" && Number.isFinite(usage.remaining)
      ? Math.max(0, usage.remaining)
      : Math.max(0, quota - (Number.isFinite(usage.used) ? usage.used : 0));
  return `${formatCount(remaining)} left`;
}

/** Human label for the key's per-minute rate limit (null → the plan default). */
function rateLimitLabel(rateLimitPerMin: number | null | undefined): string {
  if (
    typeof rateLimitPerMin === "number" &&
    Number.isFinite(rateLimitPerMin) &&
    rateLimitPerMin > 0
  ) {
    return `${formatCount(rateLimitPerMin)} req/min`;
  }
  return "Default rate limit";
}

export function UsageCard({ usage }: UsageCardProps) {
  const ratio = usageRatio(usage.used, usage.monthly_quota);
  const period = formatPeriod(usage.period_ym);
  const remaining = remainingLabel(usage);

  const usedLabel =
    ratio === null
      ? `${formatCount(usage.used)} used · Unlimited`
      : `${formatCount(usage.used)} / ${formatCount(usage.monthly_quota as number)} used`;

  return (
    <View style={styles.card}>
      <View style={styles.nameRow}>
        <Text style={styles.name} numberOfLines={1}>
          {usage.name || "Untitled key"}
        </Text>
        <Text style={styles.prefix} numberOfLines={1}>
          {usage.prefix ? `${usage.prefix}…` : "—"}
        </Text>
      </View>

      {ratio === null ? (
        <View style={styles.unlimitedBadge} accessibilityLabel="Unlimited quota">
          <Text style={styles.unlimitedText}>No monthly cap</Text>
        </View>
      ) : (
        <View
          style={styles.track}
          accessibilityRole="progressbar"
          accessibilityValue={{ min: 0, max: 100, now: Math.round(ratio * 100) }}
        >
          <View
            style={[
              styles.fill,
              {
                width: `${Math.max(2, Math.round(ratio * 100))}%`,
                backgroundColor: barColor(ratio),
              },
            ]}
          />
        </View>
      )}

      <Text style={styles.usage} numberOfLines={1}>
        {usedLabel}
        {remaining ? ` · ${remaining}` : ""}
      </Text>

      <Text style={styles.meta} numberOfLines={1}>
        {period ? period : "This month"}
        {` · ${rateLimitLabel(usage.rate_limit_per_min)}`}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 8,
  },
  nameRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  name: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "700",
    flexShrink: 1,
  },
  prefix: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: "monospace",
  },
  track: {
    height: 8,
    borderRadius: 999,
    backgroundColor: colors.cardAlt,
    overflow: "hidden",
  },
  fill: {
    height: "100%",
    borderRadius: 999,
  },
  unlimitedBadge: {
    alignSelf: "flex-start",
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  unlimitedText: {
    color: colors.textSecondary,
    fontSize: 11,
    fontWeight: "600",
    letterSpacing: 0.3,
  },
  usage: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  meta: { color: colors.muted, fontSize: 12 },
});
