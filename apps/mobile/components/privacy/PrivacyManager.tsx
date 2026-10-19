/**
 * Privacy & data controls (ENTERPRISE Compliance, Epic 5).
 *
 * The mobile self-service GDPR surface, STRICTLY caller-scoped by the backend:
 *  - EXPORT MY DATA (Art. 15 / 20): request the caller's complete data archive
 *    and open its short-lived, presigned download link.
 *  - CONSENT: per-dimension opt-in toggles, append-only and audited server-side.
 *  - DELETE MY ACCOUNT (Art. 17): irreversible, PII-anonymizing erasure behind a
 *    two-step confirmation. On success the caller's API keys are revoked, so we
 *    sign out and return to the sign-in screen.
 *
 * Every affordance here is a UI layer only — the backend authorises every call
 * as the signed-in caller and never accepts a target user id, so nothing here
 * can touch another user's data. No secrets live in this file.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";

import { useRouter } from "expo-router";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import { describeError } from "@/components/me/errors";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import {
  CONSENT_KINDS,
  eraseAccount,
  getConsentTrail,
  latestConsents,
  recordConsent,
  requestDataExport,
  type ConsentRecord,
} from "@/lib/compliance";
import { deleteSignInIdentity, getSupabaseClient, useSession } from "@/src/shared/auth";

/** Open a URL in the in-app browser, falling back to the system browser. */
async function openUrl(url: string): Promise<void> {
  try {
    await WebBrowser.openBrowserAsync(url);
    return;
  } catch {
    // Fall through to the system browser.
  }
  const canOpen = await Linking.canOpenURL(url).catch(() => false);
  if (!canOpen) throw new Error("Couldn't open the download link on this device.");
  await Linking.openURL(url);
}

export function PrivacyManager() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  return (
    <View style={styles.container}>
      <Text style={styles.intro}>
        Your data is yours. Export a copy of everything we hold, choose what
        you consent to, or permanently delete your account.
      </Text>
      <Text style={styles.intro}>
        Free accounts see a small banner ad, which may use a device advertising
        identifier (IDFA/AAID) to request non-personalized ads. iOS asks for
        your tracking permission first, and you can decline. Menivor Pro removes
        all ads. See our Privacy Policy for full details.
      </Text>

      <ExportSection token={token} />
      <ConsentSectionBlock token={token} />
      <DeleteAccountSection token={token} />
    </View>
  );
}

// ---------------------------------------------------------------------------
// Export my data (GDPR Art. 15 / 20)
// ---------------------------------------------------------------------------

function ExportSection({ token }: { token: string | undefined }) {
  const [busy, setBusy] = useState(false);

  const onExport = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await requestDataExport({ token });
      if (!result.download_url) {
        throw new Error("The export finished but no download link was returned.");
      }
      const minutes = Math.max(1, Math.round(result.expires_in / 60));
      Alert.alert(
        "Your data is ready",
        `We've packaged everything we hold about you. The download link is ` +
          `private to you and expires in about ${minutes} minute${
            minutes === 1 ? "" : "s"
          }.`,
        [
          { text: "Later", style: "cancel" },
          {
            text: "Download",
            onPress: () => {
              openUrl(result.download_url).catch((err) =>
                Alert.alert("Couldn't open the link", describeError(err)),
              );
            },
          },
        ],
      );
    } catch (err) {
      Alert.alert("Export failed", describeError(err));
    } finally {
      setBusy(false);
    }
  }, [busy, token]);

  return (
    <Section title="EXPORT MY DATA">
      <View style={styles.card}>
        <Text style={styles.cardBody}>
          Download a complete copy of your account: your profile, jobs, asset
          metadata, credit history, consent trail and workspace memberships.
          Only your own data is ever included.
        </Text>
        <Pressable
          style={[styles.primaryButton, busy && styles.buttonDisabled]}
          onPress={() => void onExport()}
          disabled={busy}
          accessibilityRole="button"
          accessibilityLabel="Export my data"
        >
          {busy ? (
            <ActivityIndicator color={colors.textPrimary} />
          ) : (
            <Text style={styles.primaryButtonText}>Prepare my export</Text>
          )}
        </Pressable>
      </View>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Consent toggles (GDPR / SOC2)
// ---------------------------------------------------------------------------

function ConsentSectionBlock({ token }: { token: string | undefined }) {
  const fetcher = useCallback(() => getConsentTrail({ token }), [token]);
  const { status, data, error, reload } = useResource<ConsentRecord[]>(fetcher);

  return (
    <Section title="CONSENT">
      <SectionState status={status} error={error} onRetry={reload}>
        <ConsentToggles token={token} trail={data ?? []} />
      </SectionState>
    </Section>
  );
}

interface ConsentTogglesProps {
  token: string | undefined;
  trail: readonly ConsentRecord[];
}

function ConsentToggles({ token, trail }: ConsentTogglesProps) {
  // Seed each toggle from the newest decision for its kind, defaulting OFF
  // (consent is opt-in) when the caller has never decided.
  const [granted, setGranted] = useState<Record<string, boolean>>(() => {
    const current = latestConsents(trail);
    const seed: Record<string, boolean> = {};
    for (const item of CONSENT_KINDS) {
      seed[item.kind] = current[item.kind] ?? item.defaultGranted;
    }
    return seed;
  });
  const [busyKind, setBusyKind] = useState<string | null>(null);

  const onToggle = useCallback(
    async (kind: string, next: boolean) => {
      if (busyKind) return;
      const previous = granted[kind] ?? false;
      setBusyKind(kind);
      // Optimistically flip, then confirm with the backend.
      setGranted((prev) => ({ ...prev, [kind]: next }));
      try {
        await recordConsent(kind, next, { token });
      } catch (err) {
        setGranted((prev) => ({ ...prev, [kind]: previous }));
        Alert.alert("Couldn't save your choice", describeError(err));
      } finally {
        setBusyKind(null);
      }
    },
    [busyKind, granted, token],
  );

  return (
    <View style={styles.card}>
      {CONSENT_KINDS.map((item, index) => (
        <View key={item.kind}>
          {index > 0 ? <View style={styles.divider} /> : null}
          <View style={styles.consentRow}>
            <View style={styles.consentText}>
              <Text style={styles.consentLabel}>{item.label}</Text>
              <Text style={styles.consentDescription}>{item.description}</Text>
            </View>
            <Switch
              value={granted[item.kind] ?? false}
              onValueChange={(next) => void onToggle(item.kind, next)}
              disabled={busyKind !== null}
              trackColor={{ false: colors.border, true: colors.primary }}
              thumbColor={colors.textPrimary}
              accessibilityLabel={item.label}
            />
          </View>
        </View>
      ))}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Delete my account (GDPR Art. 17) — irreversible, two-step confirmation
// ---------------------------------------------------------------------------

function DeleteAccountSection({ token }: { token: string | undefined }) {
  const { signOut } = useSession();
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  const doErase = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      await eraseAccount({ token });
      // Then remove the Apple/Google sign-in identity from the auth project
      // (best effort; never blocks the confirmed erasure).
      await deleteSignInIdentity(getSupabaseClient());
      // Erasure revokes every API key, so the stored session key is now dead:
      // clear it and return the (now signed-out) caller to the sign-in screen.
      await signOut();
      Alert.alert(
        "Account deleted",
        "Your personal information has been permanently removed. Records we're " +
          "legally required to keep (such as invoices) are retained but no longer " +
          "identify you.",
      );
      router.replace("/");
    } catch (err) {
      Alert.alert("Deletion failed", describeError(err));
      setBusy(false);
    }
  }, [busy, token, signOut, router]);

  const confirmFinal = useCallback(() => {
    Alert.alert(
      "This cannot be undone",
      "Deleting your account permanently anonymizes your email, name and " +
        "handle, revokes your API keys and signs you out on every device. " +
        "Are you absolutely sure?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete my account",
          style: "destructive",
          onPress: () => void doErase(),
        },
      ],
    );
  }, [doErase]);

  const confirmFirst = useCallback(() => {
    if (busy) return;
    Alert.alert(
      "Delete your account?",
      "We'll permanently remove your personal data. This can't be reversed — " +
        "consider exporting your data first.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Continue", style: "destructive", onPress: confirmFinal },
      ],
    );
  }, [busy, confirmFinal]);

  return (
    <Section title="DELETE MY ACCOUNT">
      <View style={[styles.card, styles.dangerCard]}>
        <Text style={styles.cardBody}>
          Permanently delete your account. Your personal information is
          anonymized and cannot be recovered. Financial and audit records
          required by law are kept but no longer identify you.
        </Text>
        <Pressable
          style={[styles.dangerButton, busy && styles.buttonDisabled]}
          onPress={confirmFirst}
          disabled={busy}
          accessibilityRole="button"
          accessibilityLabel="Delete my account"
        >
          {busy ? (
            <ActivityIndicator color={colors.textPrimary} />
          ) : (
            <Text style={styles.dangerButtonText}>Delete my account</Text>
          )}
        </Pressable>
      </View>
    </Section>
  );
}

const styles = StyleSheet.create({
  container: { gap: 8 },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 20,
  },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 14,
  },
  cardBody: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 14 },
  primaryButton: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 46,
  },
  primaryButtonText: {
    color: colors.textPrimary,
    fontWeight: "700",
    fontSize: 15,
  },
  buttonDisabled: { opacity: 0.6 },
  consentRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
  },
  consentText: { flex: 1, gap: 4 },
  consentLabel: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  consentDescription: { color: colors.muted, fontSize: 12, lineHeight: 17 },
  dangerCard: { borderColor: colors.error },
  dangerButton: {
    backgroundColor: colors.error,
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 46,
  },
  dangerButtonText: {
    color: colors.textPrimary,
    fontWeight: "700",
    fontSize: 15,
  },
});
