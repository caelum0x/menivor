/**
 * A horizontal row of single-select role chips (owner / admin / member).
 * Selection state is owned by the parent; this component is purely
 * presentational. Used by the invite form and the per-member role controls.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { WORKSPACE_ROLES, type WorkspaceRole } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { roleLabel } from "./roles";

export interface RolePickerProps {
  /** Currently selected role. */
  selected: WorkspaceRole;
  onSelect: (role: WorkspaceRole) => void;
  disabled?: boolean;
  /** Restrict the offered roles (defaults to all assignable roles). */
  roles?: readonly WorkspaceRole[];
}

export function RolePicker({
  selected,
  onSelect,
  disabled = false,
  roles = WORKSPACE_ROLES,
}: Readonly<RolePickerProps>) {
  return (
    <View style={styles.wrap}>
      {roles.map((role) => {
        const active = role === selected;
        return (
          <Pressable
            key={role}
            style={[
              styles.chip,
              active && styles.chipActive,
              disabled && styles.chipDisabled,
            ]}
            onPress={() => onSelect(role)}
            disabled={disabled}
            accessibilityRole="radio"
            accessibilityState={{ selected: active, disabled }}
            accessibilityLabel={roleLabel(role)}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]}>
              {roleLabel(role)}
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
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipDisabled: { opacity: 0.5 },
  chipText: { color: colors.textSecondary, fontSize: 13 },
  chipTextActive: { color: colors.textPrimary, fontWeight: "700" },
});
