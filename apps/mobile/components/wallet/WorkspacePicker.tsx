/**
 * WorkspacePicker — a presentational horizontal selector for the caller's
 * workspaces, shared by the plans/subscription and billing-history screens.
 * Purely presentational: the list, the selected id and the change handler are
 * all owned by the parent. Billing reads/writes are tenant-scoped server-side;
 * this only chooses WHICH tenant the parent screen queries.
 */

import { ScrollView, StyleSheet, Text, Pressable } from "react-native";

import { colors } from "@/components/me/theme";
import type { Workspace } from "@/lib/types";

export interface WorkspacePickerProps {
  workspaces: readonly Workspace[];
  selectedId: string | null;
  onSelect: (workspaceId: string) => void;
}

export function WorkspacePicker({
  workspaces,
  selectedId,
  onSelect,
}: Readonly<WorkspacePickerProps>) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
    >
      {workspaces.map((ws) => {
        const active = ws.id === selectedId;
        return (
          <Pressable
            key={ws.id}
            onPress={() => onSelect(ws.id)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            style={[styles.chip, active && styles.chipActive]}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]} numberOfLines={1}>
              {ws.name}
            </Text>
            <Text style={[styles.chipRole, active && styles.chipRoleActive]}>
              {String(ws.my_role)}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { gap: 10, paddingVertical: 4 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 10,
    maxWidth: 200,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  chipTextActive: { color: colors.bg },
  chipRole: { color: colors.textSecondary, fontSize: 11, marginTop: 2 },
  chipRoleActive: { color: colors.bg, opacity: 0.8 },
});
