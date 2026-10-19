/**
 * One workspace row in the workspaces list: name, the caller's role badge, and
 * an optional member count. Tapping the row opens its members view. Purely
 * presentational — selection is handled by the parent.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import type { Workspace } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { roleLabel } from "./roles";
import { Icon } from "@/components/ui/Icon";

export interface WorkspaceCardProps {
  workspace: Workspace;
  onPress: (workspace: Workspace) => void;
}

export function WorkspaceCard({
  workspace,
  onPress,
}: Readonly<WorkspaceCardProps>) {
  const count = workspace.member_count;
  const summary =
    typeof count === "number"
      ? `${count} member${count === 1 ? "" : "s"}`
      : null;

  return (
    <Pressable
      style={styles.card}
      onPress={() => onPress(workspace)}
      accessibilityRole="button"
      accessibilityLabel={`Open ${workspace.name}`}
    >
      <View style={styles.body}>
        <Text style={styles.name} numberOfLines={1}>
          {workspace.name}
        </Text>
        <View style={styles.metaRow}>
          <Text style={styles.badge}>{roleLabel(workspace.my_role)}</Text>
          {summary ? <Text style={styles.meta}>{summary}</Text> : null}
        </View>
      </View>
      <Icon name="chevron-forward" style={styles.chevron} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
  },
  body: { flex: 1, gap: 6 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  badge: {
    color: colors.accent,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.5,
  },
  meta: { color: colors.muted, fontSize: 12 },
  chevron: { color: colors.muted, fontSize: 22, fontWeight: "700" },
});
