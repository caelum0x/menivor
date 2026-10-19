/** Variants ranked by the loop's score, with per-platform numbers. */

import { Linking, Pressable, Text, View } from "react-native";

import { Badge } from "@/components/ui";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

import { formatCount, formatMeasuredPct, formatPct, platformLabel } from "../format";
import type { LoopVariant } from "../types";
import { sectionStyles as s } from "./styles";

const SOURCE_LABELS: Record<LoopVariant["source"], string> = {
  platform: "From platform",
  logged: "Logged by you",
  none: "No data yet",
};

export interface VariantRankingProps {
  readonly variants: readonly LoopVariant[];
  readonly usesRetention: boolean;
  readonly rankingReason: string;
  readonly onOpenReel: (jobId: string) => void;
}

export function VariantRanking({ variants, usesRetention, rankingReason, onOpenReel }: VariantRankingProps) {
  return (
    <View style={s.card}>
      <Text style={s.title}>Variant ranking</Text>
      <Text style={s.muted}>
        Ranked on {usesRetention ? "average watch share, views and engagement rate" : "views and engagement rate"}.
        Engagement rate is likes, comments, shares and saves per view; the platforms do not report
        a click-through rate for organic short videos.
        {rankingReason ? ` ${rankingReason}.` : ""}
      </Text>
      {variants.map((variant) => (
        <View
          key={variant.job_id}
          style={{
            borderWidth: 1,
            borderColor: variant.is_winner ? colors.accent : colors.border,
            borderRadius: radius.md,
            padding: spacing.sm,
            gap: spacing.xs,
          }}
        >
          <View style={s.row}>
            <Text style={s.micro}>{variant.rank !== null ? `#${variant.rank}` : "Unranked"}</Text>
            {variant.is_winner ? <Badge label="Winner" variant="success" /> : null}
            <Text style={s.micro}>{SOURCE_LABELS[variant.source]}</Text>
          </View>
          <Text style={s.strong}>{variant.hook || variant.title}</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
            <Metric label="Views" value={formatCount(variant.views)} />
            <Metric label="Avg watch" value={formatPct(variant.avg_watch_frac)} />
            <Metric label="Completion" value={formatMeasuredPct(variant.completion_rate)} />
            <Metric label="Rewatch" value={formatMeasuredPct(variant.rewatch_rate)} />
            <Metric label="Engagement" value={formatPct(variant.engagement_rate)} />
            <Metric label="Shares" value={formatCount(variant.shares)} />
            <Metric label="Score" value={variant.score !== null ? variant.score.toFixed(2) : "-"} />
          </View>
          {variant.posts.map((post) => (
            <View key={`${post.platform}-${post.external_id}`} style={s.row}>
              <Text style={s.label}>{platformLabel(post.platform)}</Text>
              <Text style={s.micro}>
                {post.available ? `${formatCount(post.views)} views` : "metrics unavailable"}
                {post.note ? ` · ${post.note}` : ""}
              </Text>
              {post.url && /^https:\/\//i.test(post.url) ? (
                <Pressable
                  onPress={() => void Linking.openURL(post.url).catch(() => undefined)}
                  accessibilityRole="link"
                  hitSlop={8}
                >
                  <Text style={s.link}>View post</Text>
                </Pressable>
              ) : null}
            </View>
          ))}
          {variant.state !== "complete" ? <Text style={s.micro}>Render status: {variant.state}</Text> : null}
          <Pressable onPress={() => onOpenReel(variant.job_id)} accessibilityRole="link" hitSlop={8}>
            <Text style={s.link}>Open reel</Text>
          </Pressable>
        </View>
      ))}
    </View>
  );
}

function Metric({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <View
      style={{
        backgroundColor: colors.surfaceAlt,
        borderRadius: radius.md,
        paddingHorizontal: spacing.sm,
        paddingVertical: spacing.xs,
        minWidth: 72,
      }}
    >
      <Text style={{ color: colors.textSecondary, fontSize: typeScale.micro }}>{label}</Text>
      <Text style={{ color: colors.textPrimary, fontSize: typeScale.caption, fontWeight: "700" }}>{value}</Text>
    </View>
  );
}
