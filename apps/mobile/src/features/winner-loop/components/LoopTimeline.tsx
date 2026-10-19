/** Chronological loop history (newest first) across every round of remakes. */

import { useMemo } from "react";
import { Linking, Pressable, Text, View } from "react-native";

import { Chip, Icon, type IconName } from "@/components/ui";
import { colors, spacing } from "@/src/shared/theme";

import { formatWhen, platformLabel, timelineLabel } from "../format";
import type { LineageEntry, TimelineItem } from "../types";
import { sectionStyles as s } from "./styles";

const KIND_ICONS: Record<string, IconName> = {
  configured: "settings-outline",
  scheduled: "calendar-outline",
  published: "send-outline",
  failed: "warning-outline",
  held: "shield-outline",
  measured: "bar-chart-outline",
  extended: "bar-chart-outline",
  inconclusive: "warning-outline",
  winner: "trophy-outline",
  remake_started: "refresh-outline",
  remake_failed: "warning-outline",
  cap_reached: "wallet-outline",
};

export interface LoopTimelineProps {
  readonly items: readonly TimelineItem[];
  readonly lineage: readonly LineageEntry[];
  readonly onSelectBatch: (batchId: string) => void;
}

export function LoopTimeline({ items, lineage, onSelectBatch }: LoopTimelineProps) {
  const roundOf = useMemo(() => new Map(lineage.map((entry) => [entry.batch_id, entry.generation])), [lineage]);
  return (
    <View style={s.card}>
      <Text style={s.title}>Loop timeline</Text>
      {lineage.length > 1 ? (
        <View style={s.row}>
          {lineage.map((entry) => (
            <Chip
              key={entry.batch_id}
              label={`Round ${entry.generation}`}
              active={entry.current}
              disabled={entry.current}
              onPress={() => onSelectBatch(entry.batch_id)}
            />
          ))}
        </View>
      ) : null}
      {items.length === 0 ? (
        <Text style={s.muted}>Nothing has happened in this loop yet.</Text>
      ) : (
        items.map((item, index) => {
          const round = roundOf.get(item.batch_id);
          return (
            <View
              key={`${item.at}-${item.kind}-${index}`}
              style={{ flexDirection: "row", gap: spacing.sm, paddingVertical: spacing.xs }}
            >
              <Icon name={KIND_ICONS[item.kind] ?? "ellipse-outline"} size={16} color={colors.accent} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={s.label}>
                  {timelineLabel(item.kind)}
                  {item.platform ? ` · ${platformLabel(item.platform)}` : ""}
                  {round && lineage.length > 1 ? ` · round ${round}` : ""}
                </Text>
                <Text style={s.micro}>{formatWhen(item.at)}</Text>
                {item.message ? <Text style={s.muted}>{item.message}</Text> : null}
                {item.url && /^https:\/\//i.test(item.url) ? (
                  <Pressable
                    onPress={() => void Linking.openURL(item.url).catch(() => undefined)}
                    accessibilityRole="link"
                    hitSlop={8}
                  >
                    <Text style={s.link}>View post</Text>
                  </Pressable>
                ) : null}
              </View>
            </View>
          );
        })
      )}
    </View>
  );
}
