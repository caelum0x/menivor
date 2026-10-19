/**
 * Account · Webhooks — per-workspace webhook subscriptions, linked from the
 * Developer & API Keys hub (/account/developer-keys).
 *
 * Pick a workspace to view its subscriptions, create one (the HMAC signing
 * secret is shown exactly once), send a signed test event, inspect recent
 * deliveries, and revoke. Every read/write is authorised + tenant-scoped
 * server-side via RBAC (`workspace.settings`); callback URLs are SSRF-validated
 * by the backend before any row is persisted. Auth flows through the shared api
 * client as `x-api-key`; no secrets live in this screen.
 */

import { ScrollView, StyleSheet, Text, View } from "react-native";

import { DeveloperPortalManager } from "@/components/developer/DeveloperPortalManager";
import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";

export default function AccountWebhooksScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.intro}>
        Subscribe a workspace to webhook events (job.completed, publish.*,
        performance.ingested). Every delivery is HMAC-signed with a secret shown
        once at create.
      </Text>
      <DeveloperPortalManager token={token} showSummary={false} />
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 20 },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 20,
  },
  spacer: { height: 40 },
});
