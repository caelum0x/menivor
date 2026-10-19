/**
 * FilterChips — a horizontally-scrolling single-select chip row used by the
 * Studio screens to filter a list (voice category, avatar source, …).
 * Presentational: the parent owns the selected id and the option set.
 */

import { memo } from "react";
import { Pressable, ScrollView, StyleSheet, Text } from "react-native";

import { colors } from "@/components/me/theme";

export interface FilterOption {
  id: string;
  label: string;
}

interface FilterChipsProps {
  options: readonly FilterOption[];
  selected: string;
  onSelect: (id: string) => void;
}

function FilterChipsImpl({ options, selected, onSelect }: FilterChipsProps) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
      keyboardShouldPersistTaps="handled"
    >
      {options.map((opt) => {
        const active = opt.id === selected;
        return (
          <Pressable
            key={opt.id}
            style={[styles.chip, active && styles.chipActive]}
            onPress={() => onSelect(opt.id)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]}>
              {opt.label}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

export const FilterChips = memo(FilterChipsImpl);

const styles = StyleSheet.create({
  row: { gap: 8, paddingVertical: 2, paddingRight: 8 },
  chip: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  chipTextActive: { color: colors.bg, fontWeight: "700" },
});
