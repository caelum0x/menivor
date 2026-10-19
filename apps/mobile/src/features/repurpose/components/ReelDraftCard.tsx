/**
 * Read-only preview of a reel DRAFT produced by promoting a clip (or ingesting
 * a URL). Shows exactly what would be submitted to `POST /jobs`, so the creator
 * can confirm the hook + script before spending credits. Purely presentational.
 */

import { StyleSheet, Text, View } from "react-native";

import { colors, radius, spacing, typeScale, weight } from "@/src/shared/theme";
import { formatSpan, type ReelDraft } from "@/lib/repurpose";

interface ReelDraftCardProps {
  readonly draft: ReelDraft;
}

export function ReelDraftCard({ draft }: ReelDraftCardProps) {
  const hasSpan = draft.end_s > draft.start_s;
  return (
    <View style={styles.card}>
      <Text style={styles.kicker}>REEL DRAFT · READY TO SUBMIT</Text>
      <Text style={styles.subject}>{draft.video_subject || "Untitled reel"}</Text>
      {draft.hook && draft.hook.trim() ? (
        <Text style={styles.hook}>“{draft.hook.trim()}”</Text>
      ) : null}
      {draft.video_script && draft.video_script.trim() ? (
        <Text style={styles.script}>{draft.video_script.trim()}</Text>
      ) : null}
      <View style={styles.metaRow}>
        <Text style={styles.meta}>Source: {draft.source_kind}</Text>
        {hasSpan ? (
          <Text style={styles.meta}>{formatSpan(draft.start_s, draft.end_s)}</Text>
        ) : null}
      </View>
      {draft.broll_prompts && draft.broll_prompts.length > 0 ? (
        <View style={styles.broll}>
          <Text style={styles.brollTitle}>B-roll prompts</Text>
          {draft.broll_prompts.map((prompt, index) => (
            <Text key={`${index}-${prompt}`} style={styles.brollItem}>
              • {prompt}
            </Text>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surfaceAlt,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.xs,
  },
  kicker: {
    color: colors.accent,
    fontSize: typeScale.micro,
    fontWeight: weight.bold,
    letterSpacing: 1,
  },
  subject: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: weight.bold,
    marginTop: spacing.xs,
  },
  hook: {
    color: colors.accent,
    fontSize: typeScale.caption,
    fontStyle: "italic",
  },
  script: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    lineHeight: 19,
    marginTop: spacing.xs,
  },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: spacing.xs,
  },
  meta: { color: colors.textFaint, fontSize: typeScale.micro },
  broll: { marginTop: spacing.sm, gap: 2 },
  brollTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.caption,
    fontWeight: weight.semibold,
  },
  brollItem: {
    color: colors.textFaint,
    fontSize: typeScale.micro,
    lineHeight: 16,
  },
});
