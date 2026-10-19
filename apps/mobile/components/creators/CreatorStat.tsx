/**
 * A single stat tile (big value over a muted label) used in the creator profile
 * stat grid and the leaderboard row's secondary metrics. Presentational only.
 */

import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";

interface CreatorStatProps {
  label: string;
  value: string;
}

export function CreatorStat({ label, value }: CreatorStatProps) {
  return (
    <View style={styles.tile}>
      <Text style={styles.value} numberOfLines={1}>
        {value}
      </Text>
      <Text style={styles.label} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  tile: {
    flexGrow: 1,
    flexBasis: "30%",
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 10,
    alignItems: "center",
    gap: 4,
  },
  value: { color: colors.textPrimary, fontSize: 18, fontWeight: "800" },
  label: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
});
