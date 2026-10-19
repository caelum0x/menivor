/**
 * PlatformPicker — presentational chip selector for publish targets. Works for
 * both the multi-select schedule flow (pick one or more of tiktok / instagram /
 * youtube_shorts) and the single-select native-publish flow (pick one connected
 * platform). Options + selection + toggling are owned by the parent screen.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";

/** Friendly labels for known platform ids; unknown ids render verbatim. */
const PLATFORM_LABEL: Record<string, string> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  youtube_shorts: "YouTube Shorts",
  youtube: "YouTube",
};

export function platformLabel(id: string): string {
  return PLATFORM_LABEL[id] ?? id;
}

export interface PlatformPickerProps {
  options: readonly string[];
  /** Currently selected platform ids. */
  selected: readonly string[];
  onToggle: (platform: string) => void;
  /** Optional message when there are no options (e.g. nothing connected). */
  emptyLabel?: string;
}

export function PlatformPicker({
  options,
  selected,
  onToggle,
  emptyLabel = "No platforms available.",
}: Readonly<PlatformPickerProps>) {
  if (options.length === 0) {
    return <Text style={styles.empty}>{emptyLabel}</Text>;
  }

  return (
    <View style={styles.chips}>
      {options.map((id) => {
        const active = selected.includes(id);
        return (
          <Pressable
            key={id}
            style={[styles.chip, active && styles.chipActive]}
            onPress={() => onToggle(id)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            accessibilityLabel={platformLabel(id)}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]}>
              {platformLabel(id)}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textSecondary, fontSize: 13 },
  chipTextActive: { color: "#fff", fontWeight: "600" },
  empty: { color: colors.muted, fontSize: 13, paddingVertical: 8 },
});
