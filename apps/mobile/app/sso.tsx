/**
 * Enterprise SSO screen (Identity & SSO, Epic 2).
 *
 * Pick a workspace to view whether single sign-on is configured + enabled and a
 * summary of its login security policy. Owner/admins can toggle SSO on/off; there
 * is no certificate entry on mobile (identity providers are configured from the
 * web admin). Every read/write is authorised and tenant-scoped server-side via
 * RBAC (`workspace.settings`). Auth flows through the shared api client as
 * `x-api-key`; no secrets live here.
 */

import { ScrollView, StyleSheet } from "react-native";

import { colors } from "@/components/me/theme";
import { SsoManager } from "@/components/sso/SsoManager";
import { useSession } from "@/src/shared/auth";

export default function SsoScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <SsoManager token={token} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24, paddingBottom: 48 },
});
