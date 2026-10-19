import { Pressable, StyleSheet, Text, View } from "react-native";

import type { PlatformMeta } from "./platforms";

/**
 * A horizontal wrap of multi-select platform chips for the schedule sheet.
 * Selection state is owned by the parent (an immutable Set of platform ids);
 * this component is purely presentational.
 */
export interface PlatformChipsProps {
  platforms: readonly PlatformMeta[];
  /** Currently selected platform ids. */
  selected: ReadonlySet<string>;
  onToggle: (id: string) => void;
  disabled?: boolean;
}

export function PlatformChips({
  platforms,
  selected,
  onToggle,
  disabled = false,
}: Readonly<PlatformChipsProps>) {
  return (
    <View style={styles.wrap}>
      {platforms.map((platform) => {
        const active = selected.has(platform.id);
        return (
          <Pressable
            key={platform.id}
            style={[
              styles.chip,
              active && styles.chipActive,
              disabled && styles.chipDisabled,
            ]}
            onPress={() => onToggle(platform.id)}
            disabled={disabled}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: active, disabled }}
            accessibilityLabel={platform.label}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]}>
              {platform.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: "#E6C76A", borderColor: "#E6C76A" },
  chipDisabled: { opacity: 0.5 },
  chipText: { color: "#ece9e1" },
  chipTextActive: { color: "#0f0f10", fontWeight: "700" },
});
