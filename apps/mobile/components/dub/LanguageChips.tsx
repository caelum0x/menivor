import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { DubLanguage } from "@/lib/types";

/**
 * A horizontal wrap of multi-select language chips for the dub sheet. Selection
 * state is owned by the parent (an immutable Set of language codes); this
 * component is purely presentational.
 */
export interface LanguageChipsProps {
  languages: readonly DubLanguage[];
  /** Currently selected language codes. */
  selected: ReadonlySet<string>;
  onToggle: (code: string) => void;
  loading?: boolean;
  disabled?: boolean;
  /** Shown when there are no languages and we are not loading. */
  emptyText?: string;
}

export function LanguageChips({
  languages,
  selected,
  onToggle,
  loading = false,
  disabled = false,
  emptyText = "No languages available.",
}: Readonly<LanguageChipsProps>) {
  if (loading) {
    return (
      <View style={styles.loadingRow}>
        <ActivityIndicator color="#E6C76A" />
        <Text style={styles.meta}>Loading languages…</Text>
      </View>
    );
  }

  if (languages.length === 0) {
    return <Text style={styles.meta}>{emptyText}</Text>;
  }

  return (
    <View style={styles.wrap}>
      {languages.map((lang) => {
        const active = selected.has(lang.code);
        return (
          <Pressable
            key={lang.code}
            style={[
              styles.chip,
              active && styles.chipActive,
              disabled && styles.chipDisabled,
            ]}
            onPress={() => onToggle(lang.code)}
            disabled={disabled}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: active, disabled }}
            accessibilityLabel={lang.name}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]}>
              {lang.native_name || lang.name}
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
  meta: { color: "#6f6c65", fontSize: 13 },
});
