/**
 * A small status pill used across the content-engine surfaces. Pure & typed;
 * the color is driven by the shared `statusColor` helper.
 */

import { StyleSheet, Text, View } from "react-native";

import { radius, spacing, typeScale, weight } from "@/src/shared/theme";

interface StatusPillProps {
  readonly label: string;
  readonly color: string;
}

export function StatusPill({ label, color }: StatusPillProps) {
  return (
    <View
      style={[styles.pill, { borderColor: color }]}
      accessibilityRole="text"
      accessibilityLabel={`Status: ${label}`}
    >
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={[styles.text, { color }]}>{label.toUpperCase()}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  dot: { width: 6, height: 6, borderRadius: 3 },
  text: {
    fontSize: typeScale.micro,
    fontWeight: weight.bold,
    letterSpacing: 0.5,
  },
});
