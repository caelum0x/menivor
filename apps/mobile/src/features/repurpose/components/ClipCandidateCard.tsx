/**
 * An AI-ranked clip candidate card — the heart of the content-engine review
 * flow. Shows the virality score, time span, hook/title, the ranker's reason,
 * and a transcript preview, with a Promote-to-reel CTA. Purely presentational:
 * the parent owns the promote action + busy state.
 */

import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radius, spacing, typeScale, weight } from "@/src/shared/theme";
import { formatSpan, scoreColor } from "@/lib/repurpose";

interface ClipCandidateCardProps {
  readonly title: string;
  readonly hook: string;
  readonly reason: string;
  readonly transcript: string;
  readonly startS: number;
  readonly endS: number;
  readonly score: number;
  readonly status: string;
  readonly promotable: boolean;
  readonly promoting: boolean;
  readonly onPromote: () => void;
}

export function ClipCandidateCard({
  title,
  hook,
  reason,
  transcript,
  startS,
  endS,
  score,
  status,
  promotable,
  promoting,
  onPromote,
}: ClipCandidateCardProps) {
  const promoted = status === "promoted";
  const heading = (title || hook || "Untitled clip").trim();
  const scoreTint = scoreColor(score);

  return (
    <View style={styles.card}>
      <View style={styles.topRow}>
        <View style={[styles.scoreBadge, { borderColor: scoreTint }]}>
          <Text style={[styles.scoreValue, { color: scoreTint }]}>{score}</Text>
          <Text style={styles.scoreLabel}>SCORE</Text>
        </View>
        <View style={styles.headingCol}>
          <Text style={styles.heading} numberOfLines={2}>
            {heading}
          </Text>
          <Text style={styles.span}>{formatSpan(startS, endS)}</Text>
        </View>
      </View>

      {hook && hook.trim() && hook.trim() !== heading ? (
        <Text style={styles.hook} numberOfLines={2}>
          “{hook.trim()}”
        </Text>
      ) : null}

      {reason && reason.trim() ? (
        <Text style={styles.reason} numberOfLines={3}>
          {reason.trim()}
        </Text>
      ) : null}

      {transcript && transcript.trim() ? (
        <Text style={styles.transcript} numberOfLines={4}>
          {transcript.trim()}
        </Text>
      ) : null}

      <Pressable
        style={[styles.cta, (!promotable || promoting) && styles.ctaDim]}
        onPress={onPromote}
        disabled={!promotable || promoting}
        accessibilityRole="button"
        accessibilityLabel={
          promoted ? "Clip already promoted" : "Promote this clip to a reel"
        }
        accessibilityState={{ busy: promoting, disabled: !promotable }}
      >
        {promoting ? (
          <ActivityIndicator color={colors.onAccent} />
        ) : (
          <Text style={styles.ctaText}>
            {promoted ? "Promoted" : "Promote to reel"}
          </Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.sm,
  },
  topRow: { flexDirection: "row", gap: spacing.md, alignItems: "center" },
  scoreBadge: {
    width: 54,
    height: 54,
    borderRadius: radius.md,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  scoreValue: { fontSize: typeScale.heading, fontWeight: weight.black },
  scoreLabel: {
    color: colors.textFaint,
    fontSize: 8,
    letterSpacing: 1,
    fontWeight: weight.bold,
  },
  headingCol: { flex: 1, gap: 2 },
  heading: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: weight.bold,
  },
  span: { color: colors.textFaint, fontSize: typeScale.micro },
  hook: {
    color: colors.accent,
    fontSize: typeScale.caption,
    fontStyle: "italic",
  },
  reason: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    lineHeight: 18,
  },
  transcript: {
    color: colors.textFaint,
    fontSize: typeScale.caption,
    lineHeight: 18,
  },
  cta: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: spacing.sm + 2,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 42,
    marginTop: spacing.xs,
  },
  ctaDim: { opacity: 0.45 },
  ctaText: {
    color: colors.onAccent,
    fontSize: typeScale.body,
    fontWeight: weight.bold,
  },
});
