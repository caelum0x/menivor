/**
 * A single metric tile used in the insights grid. Purely presentational.
 */

import { StyleSheet, Text, View } from "react-native";

import { colors } from "./theme";

interface StatCardProps {
  label: string;
  value: string;
  hint?: string;
  /** Accent colour for the value text (defaults to the primary brand colour). */
  accent?: string;
}

export function StatCard({ label, value, hint, accent }: StatCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.label} numberOfLines={1}>
        {label}
      </Text>
      <Text style={[styles.value, accent ? { color: accent } : null]} numberOfLines={1}>
        {value}
      </Text>
      {hint ? (
        <Text style={styles.hint} numberOfLines={2}>
          {hint}
        </Text>
      ) : null}
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
    // Two-up grid: two cards per row with a 12px gap on the container.
    flexBasis: "47%",
    flexGrow: 1,
    gap: 4,
  },
  label: { color: colors.muted, fontSize: 12, fontWeight: "600" },
  value: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  hint: { color: colors.muted, fontSize: 11 },
});
