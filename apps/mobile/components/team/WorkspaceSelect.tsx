/**
 * A single-select "charge to / share with" chip row: a leading "Personal" chip
 * (value `null`) followed by one chip per workspace the caller belongs to.
 * Purely presentational — the parent owns the selection and the workspace list.
 *
 * Used by the Create screen ("Charge to" — Personal vs a workspace's shared
 * credit pool) and the Presets form ("Share to team" — keep personal vs share a
 * brand kit to a workspace).
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import type { Workspace } from "@/lib/types";

import { colors } from "@/components/me/theme";

export interface WorkspaceSelectProps {
  /** Workspaces the caller can pick (typically GET /workspaces). */
  workspaces: readonly Workspace[];
  /** Selected workspace id, or `null` for the "Personal" option. */
  value: string | null;
  /** Called with the picked workspace id, or `null` for "Personal". */
  onSelect: (workspaceId: string | null) => void;
  disabled?: boolean;
  /** Label for the leading personal chip (defaults to "Personal"). */
  personalLabel?: string;
}

export function WorkspaceSelect({
  workspaces,
  value,
  onSelect,
  disabled = false,
  personalLabel = "Personal",
}: Readonly<WorkspaceSelectProps>) {
  const options: { id: string | null; label: string }[] = [
    { id: null, label: personalLabel },
    ...workspaces.map((w) => ({ id: w.id, label: w.name })),
  ];

  return (
    <View style={styles.wrap}>
      {options.map((option) => {
        const active = option.id === value;
        return (
          <Pressable
            key={option.id ?? "__personal__"}
            style={[
              styles.chip,
              active && styles.chipActive,
              disabled && styles.chipDisabled,
            ]}
            onPress={() => onSelect(option.id)}
            disabled={disabled}
            accessibilityRole="radio"
            accessibilityState={{ selected: active, disabled }}
            accessibilityLabel={option.label}
          >
            <Text
              style={[styles.chipText, active && styles.chipTextActive]}
              numberOfLines={1}
            >
              {option.label}
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
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
    maxWidth: 220,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipDisabled: { opacity: 0.5 },
  chipText: { color: colors.textSecondary, fontSize: 13 },
  chipTextActive: { color: colors.textPrimary, fontWeight: "700" },
});
