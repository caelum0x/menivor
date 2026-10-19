import { Pressable, StyleSheet, Text, View } from "react-native";

import type { SocialPlatform } from "@/lib/types";

import { platformLabel } from "./platforms";

/**
 * A horizontal wrap of single-select platform chips for the social-caption
 * section. Selection state is owned by the parent; this component is purely
 * presentational.
 */
export interface PlatformSelectorProps {
  platforms: readonly SocialPlatform[];
  /** Currently selected platform id, or undefined when none is chosen. */
  selectedId?: string;
  onSelect: (id: string) => void;
  disabled?: boolean;
}

export function PlatformSelector({
  platforms,
  selectedId,
  onSelect,
  disabled = false,
}: Readonly<PlatformSelectorProps>) {
  return (
    <View style={styles.wrap}>
      {platforms.map((platform) => {
        const active = platform.id === selectedId;
        return (
          <Pressable
            key={platform.id}
            style={[
              styles.chip,
              active && styles.chipActive,
              disabled && styles.chipDisabled,
            ]}
            onPress={() => onSelect(platform.id)}
            disabled={disabled}
            accessibilityRole="radio"
            accessibilityState={{ selected: active, disabled }}
            accessibilityLabel={platformLabel(platform)}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]}>
              {platformLabel(platform)}
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
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: "#2a2416", borderColor: "#E6C76A" },
  chipDisabled: { opacity: 0.5 },
  chipText: { color: "#ece9e1", fontSize: 13, fontWeight: "600" },
  chipTextActive: { color: "#E6C76A" },
});
