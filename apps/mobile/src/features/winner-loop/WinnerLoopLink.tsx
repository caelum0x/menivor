/**
 * "Which hook won?" entry on a reel's detail screen. Shows when the reel was
 * one of a one-flow run's hook variants started on this device (the run's
 * batch id is remembered locally), linking straight to its winner loop.
 * Renders nothing for single reels.
 */

import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useRouter } from "expo-router";

import { Icon } from "@/components/ui";
import { loadBatchForJob } from "@/src/features/one-flow/run-store";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";
import { isRouteAvailable } from "@/src/shared/release/surface";

export interface WinnerLoopLinkProps {
  readonly jobId: string;
}

export function WinnerLoopLink({ jobId }: WinnerLoopLinkProps) {
  const router = useRouter();
  const [batchId, setBatchId] = useState("");

  useEffect(() => {
    let active = true;
    setBatchId("");
    if (!jobId) return;
    void loadBatchForJob(jobId).then((id) => {
      if (active) setBatchId(id);
    });
    return () => {
      active = false;
    };
  }, [jobId]);

  if (!batchId || !isRouteAvailable("/insights/winners/x")) return null;
  return (
    <Pressable
      style={styles.row}
      onPress={() => router.push(`/insights/winners/${encodeURIComponent(batchId)}` as never)}
      accessibilityRole="button"
      accessibilityLabel="Open this reel's winner loop"
    >
      <Icon name="trophy-outline" size={18} color={colors.accent} />
      <View style={styles.body}>
        <Text style={styles.title}>Which hook won?</Text>
        <Text style={styles.subtitle}>
          This reel is one of 3 hook variants. See the ranking and remake the winner.
        </Text>
      </View>
      <Icon name="chevron-forward" size={18} color={colors.textSecondary} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
  },
  body: { flex: 1, gap: 2 },
  title: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700" },
  subtitle: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 18 },
});
