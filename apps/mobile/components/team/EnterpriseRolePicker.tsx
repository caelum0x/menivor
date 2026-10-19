/**
 * A horizontal row of single-select ENTERPRISE role chips
 * (owner / admin / editor / billing / viewer). Selection is owned by the parent;
 * this component is purely presentational.
 *
 * A chip whose rank is ABOVE `maxRank` is shown disabled — the client-side
 * mirror of the server rule "a caller may not grant a role above their own"
 * (the backend independently enforces it with a 403). This only gates the UI.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import {
  ENTERPRISE_ROLES,
  roleRank,
  type EnterpriseRole,
  type WorkspaceRole,
} from "@/lib/types";

import { colors } from "@/components/me/theme";
import { roleLabel } from "./roles";

export interface EnterpriseRolePickerProps {
  /** Currently selected role (widened `string` tolerated for legacy rows). */
  selected: WorkspaceRole | string;
  onSelect: (role: EnterpriseRole) => void;
  disabled?: boolean;
  /**
   * Highest rank the caller may grant; roles ranked above this are shown
   * disabled. Defaults to no cap. See {@link roleRank}.
   */
  maxRank?: number;
}

export function EnterpriseRolePicker({
  selected,
  onSelect,
  disabled = false,
  maxRank = Number.POSITIVE_INFINITY,
}: Readonly<EnterpriseRolePickerProps>) {
  return (
    <View style={styles.wrap}>
      {ENTERPRISE_ROLES.map((role) => {
        const active = role === selected;
        const outranks = roleRank(role) > maxRank;
        const isDisabled = disabled || outranks;
        return (
          <Pressable
            key={role}
            style={[
              styles.chip,
              active && styles.chipActive,
              isDisabled && styles.chipDisabled,
            ]}
            onPress={() => {
              if (!isDisabled) onSelect(role);
            }}
            disabled={isDisabled}
            accessibilityRole="radio"
            accessibilityState={{ selected: active, disabled: isDisabled }}
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
  chipDisabled: { opacity: 0.4 },
  chipText: { color: colors.textSecondary, fontSize: 13 },
  chipTextActive: { color: colors.textPrimary, fontWeight: "700" },
});
