/**
 * Horizontal, scrollable filter-chip row shared by the Reels library and the
 * schedule manager. Each chip shows a label plus a count badge; the selected
 * chip is filled with the accent. Purely presentational — the parent owns the
 * selected id and the counts.
 */

import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";

import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

export interface StatusFilterOption<Id extends string> {
  readonly id: Id;
  readonly label: string;
}

export interface StatusFilterBarProps<Id extends string> {
  readonly options: readonly StatusFilterOption<Id>[];
  readonly selected: Id;
  readonly counts: Readonly<Record<Id, number>>;
  readonly onSelect: (id: Id) => void;
}

export function StatusFilterBar<Id extends string>({
  options,
  selected,
  counts,
  onSelect,
}: Readonly<StatusFilterBarProps<Id>>) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
    >
      {options.map((option) => {
        const active = option.id === selected;
        const count = counts[option.id] ?? 0;
        return (
          <TouchableOpacity
            key={option.id}
            style={[styles.chip, active && styles.chipActive]}
            onPress={() => onSelect(option.id)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            accessibilityLabel={`${option.label}, ${count} items`}
          >
            <Text style={[styles.label, active && styles.labelActive]}>
              {option.label}
            </Text>
            <View style={[styles.badge, active && styles.badgeActive]}>
              <Text style={[styles.badgeText, active && styles.badgeTextActive]}>
                {count}
              </Text>
            </View>
          </TouchableOpacity>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { gap: spacing.sm, paddingVertical: spacing.xs, paddingRight: spacing.lg },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  chipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  label: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    fontWeight: "600",
  },
  labelActive: { color: colors.onAccent },
  badge: {
    minWidth: 20,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center",
  },
  badgeActive: { backgroundColor: "rgba(15,15,16,0.18)" },
  badgeText: {
    color: colors.textSecondary,
    fontSize: typeScale.micro,
    fontWeight: "700",
  },
  badgeTextActive: { color: colors.onAccent },
});
