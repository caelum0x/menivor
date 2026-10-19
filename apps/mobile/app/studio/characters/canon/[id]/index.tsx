/**
 * Studio · Character Canon — detail
 *
 * Nav manifest: { route: "/studio/characters/canon/[id]", title: "Canon" }
 *
 * One canon's governance surface (GET /canon/{id}):
 *   · Header: name, bound character, current version + content hash.
 *   · Version history — every immutable locked version, newest first; each row
 *     opens its snapshot (/studio/characters/canon/[id]/versions/[version]).
 *   · Lock a new version (POST /canon/{id}/lock): edit the value surface —
 *     prefilled from the current version — behind a confirmation dialog. Old
 *     versions are retained; the current version advances.
 *   · Verify a shot (POST /canon/{id}/verify): paste a generated asset id to
 *     check it was produced under this canon's locked values.
 * Explicit loading / not-found / error states + pull-to-refresh.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import {
  getCanon,
  getCanonVersion,
  lockCanonVersion,
  verifyCanonAsset,
  type CanonHeader,
  type CanonVerifyResult,
  type CanonVersionRef,
} from "@/lib/canon";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { CanonValueFields } from "@/components/canon/CanonValueFields";
import {
  EMPTY_CANON_FIELDS,
  fieldsAreEmpty,
  fieldsFromValues,
  fieldsToBody,
  type CanonValueFields as Fields,
} from "@/components/canon/canon-fields";
import { Icon } from "@/components/ui/Icon";

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

export default function CanonDetailScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const params = useLocalSearchParams<{ id?: string | string[] }>();
  const canonId = firstParam(params.id).trim();

  const [canon, setCanon] = useState<CanonHeader | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const [fields, setFields] = useState<Fields>(EMPTY_CANON_FIELDS);
  const [locking, setLocking] = useState(false);
  const [lockError, setLockError] = useState("");

  const [assetId, setAssetId] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState("");
  const [verifyResult, setVerifyResult] = useState<CanonVerifyResult | null>(null);

  const load = useCallback(
    async (mode: "initial" | "refresh") => {
      if (!canonId) {
        setStatus("error");
        setError("Missing canon id.");
        return;
      }
      if (mode === "initial") setStatus("loading");
      else setRefreshing(true);
      try {
        const header = await getCanon(canonId, { token });
        setCanon(header);
        // Prefill the lock form from the current version so a lock edits, not resets.
        try {
          const current = await getCanonVersion(canonId, header.current_version, { token });
          setFields(fieldsFromValues(current.values));
        } catch {
          setFields(EMPTY_CANON_FIELDS);
        }
        setStatus("ready");
        setError("");
      } catch (err) {
        setError(describeError(err, "Failed to load the canon."));
        if (mode === "initial") setStatus("error");
      } finally {
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [canonId, token],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const onChangeField = useCallback((key: keyof Fields, value: string) => {
    setFields((prev) => ({ ...prev, [key]: value }));
  }, []);

  const performLock = useCallback(async () => {
    setLocking(true);
    setLockError("");
    try {
      await lockCanonVersion(canonId, { ...fieldsToBody(fields) }, { token });
      await load("refresh");
    } catch (err) {
      setLockError(describeError(err, "Failed to lock a new version."));
    } finally {
      setLocking(false);
    }
  }, [canonId, fields, token, load]);

  const confirmLock = useCallback(() => {
    if (fieldsAreEmpty(fields)) {
      setLockError("Add at least one value before locking a version.");
      return;
    }
    setLockError("");
    Alert.alert(
      "Lock a new version",
      "This appends a new immutable version and advances the current version. Existing versions are kept and can never change. Continue?",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Lock version", onPress: () => void performLock() },
      ],
    );
  }, [fields, performLock]);

  const onVerify = useCallback(async () => {
    if (!assetId.trim()) {
      setVerifyError("Enter a generated asset id to verify.");
      setVerifyResult(null);
      return;
    }
    setVerifying(true);
    setVerifyError("");
    setVerifyResult(null);
    try {
      const result = await verifyCanonAsset(canonId, { asset_id: assetId.trim() }, { token });
      setVerifyResult(result);
    } catch (err) {
      setVerifyError(describeError(err, "Verification failed."));
    } finally {
      setVerifying(false);
    }
  }, [assetId, canonId, token]);

  const renderVersion = (v: CanonVersionRef) => {
    const isCurrent = canon != null && v.version === canon.current_version;
    return (
      <Pressable
        key={v.version}
        style={styles.versionRow}
        onPress={() =>
          router.push(`/studio/characters/canon/${canonId}/versions/${v.version}`)
        }
        accessibilityRole="button"
        accessibilityLabel={`Open version ${v.version}`}
      >
        <View style={styles.versionMain}>
          <View style={styles.versionTitleRow}>
            <Text style={styles.versionLabel}>Version {v.version}</Text>
            {isCurrent ? (
              <View style={styles.currentBadge}>
                <Text style={styles.currentText}>CURRENT</Text>
              </View>
            ) : null}
          </View>
          <Text style={styles.versionHash} numberOfLines={1}>
            {v.canon_hash}
          </Text>
          <Text style={styles.versionMeta}>Locked {v.locked_at}</Text>
        </View>
        <Icon name="chevron-forward" style={styles.chevron} />
      </Pressable>
    );
  };

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load("initial")}
      loadingLabel="Loading canon…"
    >
      <Stack.Screen options={{ title: canon ? canon.name : "Canon" }} />
      {!canon ? (
        <View style={styles.notFound}>
          <Text style={styles.notFoundTitle}>Canon not found</Text>
          <Text style={styles.notFoundText}>
            This canon is no longer available or is not owned by this account.
          </Text>
          <Pressable style={styles.secondary} onPress={() => router.back()}>
            <Text style={styles.secondaryText}>Back</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => void load("refresh")}
              tintColor={colors.accent}
            />
          }
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.headerCard}>
            <Text style={styles.title}>{canon.name}</Text>
            <View style={styles.rows}>
              <DetailRow label="Current version" value={`v${canon.current_version}`} />
              <DetailRow
                label="Current hash"
                value={canon.current_canon_hash || "—"}
                mono
              />
              <DetailRow
                label="Bound character"
                value={canon.character_id || "None"}
                last
              />
            </View>
          </View>

          <Text style={styles.sectionTitle}>VERSION HISTORY</Text>
          <View style={styles.versionList}>
            {canon.versions.length === 0 ? (
              <Text style={styles.empty}>No versions recorded.</Text>
            ) : (
              [...canon.versions]
                .sort((a, b) => b.version - a.version)
                .map(renderVersion)
            )}
          </View>

          <Text style={styles.sectionTitle}>LOCK A NEW VERSION</Text>
          <View style={styles.panel}>
            <Text style={styles.panelHint}>
              Prefilled from the current version. Edit any field, then lock to
              append an immutable v{canon.current_version + 1}.
            </Text>
            <CanonValueFields fields={fields} onChange={onChangeField} disabled={locking} />
            {lockError ? <Text style={styles.error}>{lockError}</Text> : null}
            <Pressable
              style={[styles.primary, locking && styles.disabled]}
              onPress={confirmLock}
              disabled={locking}
              accessibilityRole="button"
            >
              {locking ? (
                <ActivityIndicator color={colors.bg} />
              ) : (
                <Text style={styles.primaryText}>Lock new version</Text>
              )}
            </Pressable>
          </View>

          <Text style={styles.sectionTitle}>VERIFY A SHOT</Text>
          <View style={styles.panel}>
            <Text style={styles.panelHint}>
              Paste a generated asset id to confirm it was produced under this
              canon's locked values.
            </Text>
            <TextInput
              style={styles.input}
              value={assetId}
              onChangeText={setAssetId}
              placeholder="asset id"
              placeholderTextColor={colors.muted}
              editable={!verifying}
              autoCapitalize="none"
              autoCorrect={false}
            />
            {verifyError ? <Text style={styles.error}>{verifyError}</Text> : null}
            {verifyResult ? (
              <View
                style={[
                  styles.verifyResult,
                  verifyResult.verified ? styles.verifyOk : styles.verifyFail,
                ]}
              >
                <Text style={styles.verifyStatus}>
                  {verifyResult.verified ? "Verified" : "Not verified"}
                </Text>
                <Text style={styles.verifyReason}>{verifyResult.reason || "—"}</Text>
              </View>
            ) : null}
            <Pressable
              style={[styles.secondaryBtn, verifying && styles.disabled]}
              onPress={() => void onVerify()}
              disabled={verifying}
              accessibilityRole="button"
            >
              {verifying ? (
                <ActivityIndicator color={colors.textPrimary} />
              ) : (
                <Text style={styles.secondaryBtnText}>Verify asset</Text>
              )}
            </Pressable>
          </View>
        </ScrollView>
      )}
    </StudioScreen>
  );
}

interface DetailRowProps {
  label: string;
  value: string;
  mono?: boolean;
  last?: boolean;
}

function DetailRow({ label, value, mono, last }: DetailRowProps) {
  return (
    <View style={[styles.row, last && styles.rowLast]}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text
        style={[styles.rowValue, mono && styles.rowValueMono]}
        selectable
        numberOfLines={2}
      >
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 48, gap: 14 },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  headerCard: { gap: 12 },
  rows: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    overflow: "hidden",
  },
  row: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 3,
  },
  rowLast: { borderBottomWidth: 0 },
  rowLabel: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
  rowValue: { color: colors.textPrimary, fontSize: 15 },
  rowValueMono: { fontFamily: "monospace", fontSize: 13 },
  sectionTitle: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
    marginTop: 6,
  },
  versionList: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    overflow: "hidden",
  },
  versionRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  versionMain: { flex: 1, gap: 3 },
  versionTitleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  versionLabel: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  currentBadge: {
    backgroundColor: colors.primary,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  currentText: { color: colors.bg, fontSize: 10, fontWeight: "800", letterSpacing: 0.6 },
  versionHash: { color: colors.muted, fontSize: 12, fontFamily: "monospace" },
  versionMeta: { color: colors.muted, fontSize: 11 },
  chevron: { color: colors.muted, fontSize: 22, fontWeight: "300" },
  panel: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 12,
  },
  panelHint: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.textPrimary,
    fontSize: 14,
  },
  primary: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
  },
  primaryText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  secondaryBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: "center",
  },
  secondaryBtnText: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  disabled: { opacity: 0.6 },
  error: { color: colors.error, fontSize: 13 },
  verifyResult: { borderRadius: 10, padding: 12, gap: 4, borderWidth: 1 },
  verifyOk: { borderColor: colors.success, backgroundColor: colors.cardAlt },
  verifyFail: { borderColor: colors.error, backgroundColor: colors.cardAlt },
  verifyStatus: { color: colors.textPrimary, fontSize: 15, fontWeight: "800" },
  verifyReason: { color: colors.textSecondary, fontSize: 13 },
  notFound: {
    flex: 1,
    padding: 24,
    gap: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  notFoundTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  notFoundText: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
  },
  secondary: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  secondaryText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
  empty: { color: colors.muted, fontSize: 14, padding: 14 },
});
