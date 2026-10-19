/**
 * StatTile primitive — a key-metric display tile with label and value.
 * Optionally shows a change indicator and sub-label. No emoji.
 */

import {
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing, typeScale, weight } from "@/src/shared/theme";

export interface StatTileProps {
  label: string;
  value: string | number;
  subLabel?: string;
  /** Positive/negative change label, e.g. "+12%" */
  change?: string;
  /** If true, change is shown in danger color. */
  negative?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function StatTile({
  label,
  value,
  subLabel,
  change,
  negative = false,
  style,
}: StatTileProps): React.JSX.Element {
  return (
    <View style={[styles.tile, style]}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.valueRow}>
        <Text style={styles.value}>{String(value)}</Text>
        {change ? (
          <Text style={[styles.change, negative && styles.changeNeg]}>
            {change}
          </Text>
        ) : null}
      </View>
      {subLabel ? <Text style={styles.subLabel}>{subLabel}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  tile: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: 4,
    flex: 1,
  },
  label: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: weight.bold,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  valueRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: spacing.xs,
  },
  value: {
    color: colors.textPrimary,
    fontSize: typeScale.heading,
    fontWeight: weight.black,
    lineHeight: typeScale.heading * 1.2,
  },
  change: {
    color: colors.success,
    fontSize: 12,
    fontWeight: weight.semibold,
    paddingBottom: 2,
  },
  changeNeg: { color: colors.error },
  subLabel: {
    color: colors.textSecondary,
    fontSize: 12,
  },
});
