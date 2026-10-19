/**
 * A single winning-template aggregate: the template name, its deterministic
 * win_score, and the supporting reel/view/engagement/retention stats. Purely
 * presentational. `rank` is the 1-based position in the ranked list; the top
 * three ranks get a subtly emphasised score pill so the leaderboard reads at a
 * glance. Defensive against partial backend rows (NaN/undefined never renders).
 */

import { StyleSheet, Text, View } from "react-native";

import type { WinningTemplate } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { formatCount } from "@/components/me/format";
import { formatPct, formatScore } from "./format";

interface WinningTemplateCardProps {
  template: WinningTemplate;
  rank: number;
}

/** Human label for a template id/name, tolerating an empty/blank value. */
function templateLabel(value: string): string {
  const trimmed = typeof value === "string" ? value.trim() : "";
  return trimmed.length > 0 ? trimmed : "Untitled template";
}

export function WinningTemplateCard({ template, rank }: WinningTemplateCardProps) {
  const reels = Number.isFinite(template.reels) ? template.reels : 0;
  const isTop = rank <= 3;
  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.rank}>#{rank}</Text>
        <View style={[styles.scorePill, isTop ? styles.scorePillTop : null]}>
          <Text style={[styles.scoreValue, isTop ? styles.scoreTextTop : null]}>
            {formatScore(template.win_score)}
          </Text>
          <Text style={[styles.scoreLabel, isTop ? styles.scoreTextTop : null]}>
            win score
          </Text>
        </View>
      </View>

      <Text style={styles.template} numberOfLines={2}>
        {templateLabel(template.template)}
      </Text>

      <View style={styles.stats}>
        <Stat label="Reels" value={formatCount(reels)} />
        <Stat label="Views" value={formatCount(template.views)} />
        <Stat label="Engagements" value={formatCount(template.engagements)} />
        <Stat label="Avg retention" value={formatPct(template.avg_retention_pct)} />
      </View>
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  rank: { color: colors.muted, fontSize: 14, fontWeight: "800" },
  scorePill: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: 6,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 5,
  },
  scorePillTop: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  scoreValue: { color: colors.accent, fontSize: 16, fontWeight: "800" },
  scoreTextTop: { color: colors.bg },
  scoreLabel: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: "600",
    letterSpacing: 0.6,
    textTransform: "uppercase",
  },
  template: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "700",
    lineHeight: 21,
  },
  stats: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  stat: { flexBasis: "22%", flexGrow: 1, gap: 2 },
  statValue: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  statLabel: { color: colors.muted, fontSize: 11 },
});
