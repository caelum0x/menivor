/**
 * Privacy & data screen (ENTERPRISE Compliance, Epic 5).
 *
 * The self-service GDPR surface: export all of my data, manage consent, and
 * permanently delete my account. All logic lives in {@link PrivacyManager};
 * every call is authorised as the signed-in caller and strictly caller-scoped
 * server-side. Auth flows through the shared api client as `x-api-key`; no
 * secrets live here.
 */

import { ScrollView, StyleSheet } from "react-native";

import { colors } from "@/components/me/theme";
import { PrivacyManager } from "@/components/privacy/PrivacyManager";

export default function PrivacyScreen() {
  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <PrivacyManager />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24, paddingBottom: 48 },
});
