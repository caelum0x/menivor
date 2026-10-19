/**
 * Studio · Character Canon — version snapshot
 *
 * Nav manifest: { route: "/studio/characters/canon/[id]/versions/[version]", title: "Version" }
 *
 * A single immutable locked canon version (GET /canon/{id}/versions/{version}).
 * Read-only: content hash, lock time, bound character identity key, and every
 * locked value (style, palette, typography, voice, product, brand). This is the
 * exact snapshot a generation is verified against, so nothing here is editable.
 * Explicit loading / not-found / error states.
 */

import { useCallback, useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { getCanonVersion, type CanonVersionSnapshot } from "@/lib/canon";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

interface ScalarField {
  label: string;
  value: string;
}

interface ListField {
  label: string;
  values: string[];
}

export default function CanonVersionScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const params = useLocalSearchParams<{ id?: string | string[]; version?: string | string[] }>();
  const canonId = firstParam(params.id).trim();
  const versionRaw = firstParam(params.version).trim();
  const versionNum = Number.parseInt(versionRaw, 10);

  const [snapshot, setSnapshot] = useState<CanonVersionSnapshot | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!canonId || !Number.isFinite(versionNum)) {
      setStatus("error");
      setError("Missing or invalid version reference.");
      return;
    }
    setStatus("loading");
    try {
      const data = await getCanonVersion(canonId, versionNum, { token });
      setSnapshot(data);
      setStatus("ready");
      setError("");
    } catch (err) {
      setError(describeError(err, "Failed to load this version."));
      setStatus("error");
    }
  }, [canonId, versionNum, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const scalars: ScalarField[] = snapshot
    ? [
        { label: "Style", value: snapshot.values.style },
        { label: "Voice ID", value: snapshot.values.voice_id },
        { label: "Voice tone", value: snapshot.values.voice_tone },
        { label: "Language", value: snapshot.values.language },
        { label: "Product name", value: snapshot.values.product_name },
      ].filter((f) => f.value.trim().length > 0)
    : [];

  const lists: ListField[] = snapshot
    ? [
        { label: "Palette", values: snapshot.values.palette },
        { label: "Typography", values: snapshot.values.typography },
        { label: "Product descriptors", values: snapshot.values.product_descriptors },
        { label: "Product claims", values: snapshot.values.product_claims },
        { label: "Brand tone", values: snapshot.values.brand_tone },
        { label: "Brand avoid", values: snapshot.values.brand_avoid },
      ].filter((f) => f.values.length > 0)
    : [];

  const hasValues = scalars.length > 0 || lists.length > 0;

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load()}
      loadingLabel="Loading version…"
    >
      <Stack.Screen options={{ title: snapshot ? `Version ${snapshot.version}` : "Version" }} />
      {!snapshot ? (
        <View style={styles.notFound}>
          <Text style={styles.notFoundTitle}>Version not found</Text>
          <Text style={styles.notFoundText}>
            This canon version does not exist or is not owned by this account.
          </Text>
          <Pressable style={styles.secondary} onPress={() => router.back()}>
            <Text style={styles.secondaryText}>Back</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.content}>
          <View style={styles.headerRow}>
            <Text style={styles.title}>Version {snapshot.version}</Text>
            <View style={styles.lockedBadge}>
              <Text style={styles.lockedText}>IMMUTABLE</Text>
            </View>
          </View>

          <View style={styles.metaCard}>
            <MetaRow label="Content hash" value={snapshot.canon_hash} mono />
            <MetaRow label="Locked at" value={snapshot.locked_at} />
            <MetaRow
              label="Character identity"
              value={snapshot.character_identity_key || "None"}
              mono
              last
            />
          </View>

          <Text style={styles.sectionTitle}>LOCKED VALUES</Text>
          {!hasValues ? (
            <Text style={styles.empty}>This version locked no explicit values.</Text>
          ) : (
            <View style={styles.valuesCard}>
              {scalars.map((f, i) => (
                <View
                  key={f.label}
                  style={[
                    styles.valueRow,
                    i === scalars.length - 1 && lists.length === 0 && styles.valueRowLast,
                  ]}
                >
                  <Text style={styles.valueLabel}>{f.label}</Text>
                  <Text style={styles.valueText} selectable>
                    {f.value}
                  </Text>
                </View>
              ))}
              {lists.map((f, i) => (
                <View
                  key={f.label}
                  style={[styles.valueRow, i === lists.length - 1 && styles.valueRowLast]}
                >
                  <Text style={styles.valueLabel}>{f.label}</Text>
                  <View style={styles.chipWrap}>
                    {f.values.map((v, j) => (
                      <View key={`${f.label}-${j}`} style={styles.chip}>
                        <Text style={styles.chipText}>{v}</Text>
                      </View>
                    ))}
                  </View>
                </View>
              ))}
            </View>
          )}
        </ScrollView>
      )}
    </StudioScreen>
  );
}

interface MetaRowProps {
  label: string;
  value: string;
  mono?: boolean;
  last?: boolean;
}

function MetaRow({ label, value, mono, last }: MetaRowProps) {
  return (
    <View style={[styles.metaRow, last && styles.valueRowLast]}>
      <Text style={styles.valueLabel}>{label}</Text>
      <Text style={[styles.valueText, mono && styles.mono]} selectable numberOfLines={3}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 48, gap: 14 },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  lockedBadge: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  lockedText: {
    color: colors.textSecondary,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.8,
  },
  metaCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    overflow: "hidden",
  },
  metaRow: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 3,
  },
  sectionTitle: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
    marginTop: 6,
  },
  valuesCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    overflow: "hidden",
  },
  valueRow: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 6,
  },
  valueRowLast: { borderBottomWidth: 0 },
  valueLabel: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
  valueText: { color: colors.textPrimary, fontSize: 15 },
  mono: { fontFamily: "monospace", fontSize: 13 },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  chipText: { color: colors.textPrimary, fontSize: 13 },
  empty: { color: colors.muted, fontSize: 14 },
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
});
