import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { CoverStyle } from "@/lib/types";

/**
 * A horizontal wrap of single-select cover-style chips. Selection state is owned
 * by the parent (the selected style id); this component is purely
 * presentational. Each chip shows the style name and a small accent swatch.
 */
export interface CoverStyleChipsProps {
  styles: readonly CoverStyle[];
  /** Currently selected style id, or null when none is chosen. */
  value: string | null;
  onChange: (id: string) => void;
  loading?: boolean;
  disabled?: boolean;
  /** Shown when there are no styles and we are not loading. */
  emptyText?: string;
}

export function CoverStyleChips({
  styles: coverStyles,
  value,
  onChange,
  loading = false,
  disabled = false,
  emptyText = "No cover styles available.",
}: Readonly<CoverStyleChipsProps>) {
  if (loading) {
    return (
      <View style={styles.loadingRow}>
        <ActivityIndicator color="#E6C76A" />
        <Text style={styles.meta}>Loading styles…</Text>
      </View>
    );
  }

  if (coverStyles.length === 0) {
    return <Text style={styles.meta}>{emptyText}</Text>;
  }

  return (
    <View style={styles.wrap}>
      {coverStyles.map((style) => {
        const active = style.id === value;
        return (
          <Pressable
            key={style.id}
            style={[
              styles.chip,
              active && styles.chipActive,
              disabled && styles.chipDisabled,
            ]}
            onPress={() => onChange(style.id)}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityState={{ selected: active, disabled }}
            accessibilityLabel={style.name}
            accessibilityHint={style.description || undefined}
          >
            {style.accent ? (
              <View
                style={[styles.swatch, { backgroundColor: style.accent }]}
              />
            ) : null}
            <Text style={[styles.chipText, active && styles.chipTextActive]}>
              {style.name}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  loadingRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: "#E6C76A", borderColor: "#E6C76A" },
  chipDisabled: { opacity: 0.5 },
  swatch: { width: 12, height: 12, borderRadius: 6 },
  chipText: { color: "#ece9e1" },
  chipTextActive: { color: "#0f0f10", fontWeight: "700" },
  meta: { color: "#6f6c65", fontSize: 13 },
});
