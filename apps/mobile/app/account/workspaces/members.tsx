/**
 * Route: /account/workspaces/members (legacy /team redirects here) — part of
 * the Workspaces hub. Lists the caller's workspaces and lets them create a
 * new one, invite existing users by email with a role, change roles, remove
 * members, and leave — all role-aware (owners/admins manage; members view +
 * leave). This is an additive team-membership layer and does not change how
 * individual jobs or credits are owned.
 *
 * Auth token comes from the session and is sent as `x-api-key` by the shared api
 * client. No secrets live here; each surface owns its own loading + error state.
 */

import { ScrollView, StyleSheet } from "react-native";

import { WorkspacesManager } from "@/components/team/WorkspacesManager";
import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";

export default function TeamScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <WorkspacesManager token={token} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24, paddingBottom: 48 },
});
