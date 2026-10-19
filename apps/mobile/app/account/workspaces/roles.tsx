/**
 * Route: /account/workspaces/roles (legacy /team-roles redirects here) — part
 * of the Workspaces hub. Team Roles & Permissions (ENTERPRISE Access & Governance, Epic 1).
 *
 * Pick a workspace to view your effective role + permissions, the member roster
 * with each member's Enterprise role, and — for admins/owners — change roles and
 * read the append-only audit trail. Every authorization decision is made
 * server-side by the pycasbin enforcer; this screen only mirrors the returned
 * role/permissions to gate what it shows. TENANT ISOLATION is preserved end to
 * end. Auth flows through the shared api client as `x-api-key`; no secrets here.
 */

import { ScrollView, StyleSheet } from "react-native";

import { TeamRolesManager } from "@/components/team/TeamRolesManager";
import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";

export default function TeamRolesScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <TeamRolesManager token={token} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24, paddingBottom: 48 },
});
