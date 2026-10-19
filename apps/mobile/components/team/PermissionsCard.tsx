/**
 * Presentational card for a caller's effective access in a workspace: their role
 * badge plus a chip per granted permission. All data comes from
 * {@link getMyPermissions}; a non-member (`role === null`) renders a clear
 * "not a member" message with no permission chips (the tenant-isolation signal).
 */

import { StyleSheet, Text, View } from "react-native";

import type { Permissions } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { roleLabel } from "./roles";

/** Friendly labels for the Enterprise permission catalog (falls back to the id). */
const PERMISSION_LABELS: Readonly<Record<string, string>> = {
  "jobs.read": "View jobs",
  "jobs.create": "Create jobs",
  "members.manage": "Manage members",
  "workspace.settings": "Workspace settings",
  "billing.manage": "Manage billing",
  "audit.read": "Read audit log",
  "admin.access": "Full access",
};

function permissionLabel(permission: string): string {
  return PERMISSION_LABELS[permission] ?? permission;
}

export function PermissionsCard({
  permissions,
}: {
  permissions: Readonly<Permissions>;
}) {
  if (!permissions.role) {
    return (
      <Text style={styles.empty}>
        You are not a member of this workspace.
      </Text>
    );
  }

  return (
    <View style={styles.card}>
      <View style={styles.roleRow}>
        <Text style={styles.roleLabel}>Your role</Text>
        <Text style={styles.roleBadge}>{roleLabel(permissions.role)}</Text>
      </View>
      {permissions.permissions.length > 0 ? (
        <View style={styles.chips}>
          {permissions.permissions.map((permission) => (
            <Text key={permission} style={styles.chip}>
              {permissionLabel(permission)}
            </Text>
          ))}
        </View>
      ) : (
        <Text style={styles.empty}>No permissions granted.</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 12,
  },
  roleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  roleLabel: { color: colors.muted, fontSize: 13 },
  roleBadge: {
    color: colors.accent,
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 0.5,
  },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    color: colors.textSecondary,
    fontSize: 12,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 6,
    overflow: "hidden",
  },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
});
