/**
 * Conversion funnel: jobs Created → Completed → Published. Three stacked bars
 * sized relative to the top ("Created") stage, each annotated with its count
 * and conversion rate off the top of the funnel.
 */

import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import type { AnalyticsFunnel } from "@/lib/types";

import { Bar } from "./Bar";
import { formatCount, toPercent } from "./format";

interface FunnelProps {
  funnel: AnalyticsFunnel;
}

interface Stage {
  label: string;
  value: number;
  color: string;
}

export function Funnel({ funnel }: FunnelProps) {
  const top = Math.max(funnel.created, 0);
  const stages: Stage[] = [
    { label: "Created", value: funnel.created, color: colors.accent },
    { label: "Completed", value: funnel.completed, color: colors.primary },
    { label: "Published", value: funnel.published, color: colors.success },
  ];

  return (
    <View style={styles.container}>
      {stages.map((stage) => {
        const pct = toPercent(stage.value, top);
        return (
          <View key={stage.label} style={styles.stage}>
            <View style={styles.stageHeader}>
              <Text style={styles.stageLabel}>{stage.label}</Text>
              <Text style={styles.stageValue}>{formatCount(stage.value)}</Text>
            </View>
            <Bar percent={top > 0 ? pct : 0} color={stage.color} height={14} />
            <Text style={styles.stageRate}>
              {top > 0 ? `${Math.round(pct)}% of created` : "No jobs yet"}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 16,
  },
  stage: { gap: 6 },
  stageHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  stageLabel: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
  stageValue: { color: colors.textPrimary, fontSize: 16, fontWeight: "800" },
  stageRate: { color: colors.muted, fontSize: 11 },
});
