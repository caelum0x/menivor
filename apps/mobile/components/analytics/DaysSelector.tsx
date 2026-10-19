/**
 * Trailing-window selector for the dashboard. A small row of chips (7 / 30 / 90
 * days); the active one is highlighted. Controlled — the parent owns the value.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";

/** The selectable windows, in days. */
export const DAY_OPTIONS = [7, 30, 90] as const;
export type DayOption = (typeof DAY_OPTIONS)[number];

interface DaysSelectorProps {
  value: number;
  onChange: (days: DayOption) => void;
  /** Disables interaction while a fetch is in flight. */
  disabled?: boolean;
}

export function DaysSelector({ value, onChange, disabled }: DaysSelectorProps) {
  return (
    <View style={styles.row} accessibilityRole="tablist">
      {DAY_OPTIONS.map((option) => {
        const active = option === value;
        return (
          <Pressable
            key={option}
            onPress={() => onChange(option)}
            disabled={disabled}
            accessibilityRole="tab"
            accessibilityState={{ selected: active, disabled: !!disabled }}
            style={[
              styles.chip,
              active && styles.chipActive,
              disabled && styles.chipDisabled,
            ]}
          >
            <Text style={[styles.label, active && styles.labelActive]}>
              {option}d
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: 8 },
  chip: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipDisabled: { opacity: 0.5 },
  label: { color: colors.textSecondary, fontSize: 13, fontWeight: "700" },
  labelActive: { color: colors.textPrimary },
});
