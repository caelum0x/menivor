/**
 * Route: /wallet/transfer-policy — view & edit the per-source send guardrails.
 *
 * NAV MANIFEST (integration owns navigation; do not edit _layout.tsx here):
 *   path:   /wallet/transfer-policy
 *   title:  "Send limits"
 *   parent: /wallet  (link from the wallet dashboard / transfer screen)
 *   params: none
 *
 * Reads and writes the spending policy that bounds token transfers for one
 * authorized wallet source (a personal wallet or a workspace shared pool):
 *   - GET /wallet/transfer-policy  → getTransferPolicy(sourceAccountId)
 *   - PUT /wallet/transfer-policy  → setTransferPolicy(body)
 *
 * The source list comes from GET /wallet/sources (each source carries its
 * current `limits`, used as an authoritative fallback if the policy read
 * fails). Every amount on the wire is integer microdollars and the server owns
 * all arithmetic/validation; this screen only formats for display and mirrors
 * the range checks for fast inline feedback. A value of 0 (blank input) means
 * "no configured ceiling" — the global hard maximum still applies server-side.
 *
 * Guardrails: two USD inputs (per-transfer + UTC-daily), inline validation, a
 * dirty check that only enables Save when something changed, and a confirm
 * dialog before the write. Loading / empty / error / success states included.
 */

import { useCallback, useMemo, useState } from "react";
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

import { useFocusEffect, useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { ApiError } from "@/src/shared/api";
import { formatUsdMicros } from "@/lib/marketplace";
import {
  getTransferPolicy,
  getWalletSources,
  setTransferPolicy,
  type WalletSource,
} from "@/lib/wallet";

/** Server-enforced hard ceilings mirrored for fast inline feedback (micros). */
const PER_TRANSFER_MAX_MICROS = 1_000_000_000; // $1,000
const DAILY_MAX_MICROS = 1_000_000_000_000; // $1,000,000

type SourceLimits = WalletSource["limits"];

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

/**
 * Parse a limit input into exact integer micros. Blank or "0" disables the
 * ceiling (0 micros). Any other value must be a positive decimal USD amount.
 * Returns a discriminated result so callers render the precise error.
 */
type ParsedLimit = { ok: true; micros: number } | { ok: false; error: string };

function parseLimitInput(raw: string, maxMicros: number, label: string): ParsedLimit {
  const trimmed = raw.trim();
  if (trimmed === "" || /^0(?:\.0{0,6})?$/.test(trimmed)) {
    return { ok: true, micros: 0 };
  }
  const match = /^(\d+)(?:\.(\d{0,6}))?$/.exec(trimmed);
  if (!match) {
    return { ok: false, error: `Enter a valid ${label}, e.g. 25 or 25.50 (or 0 for no limit).` };
  }
  const whole = Number(match[1]);
  const fraction = Number((match[2] ?? "").padEnd(6, "0"));
  const micros = whole * 1_000_000 + fraction;
  if (!Number.isSafeInteger(micros) || micros <= 0) {
    return { ok: false, error: `Enter a valid ${label}.` };
  }
  if (micros > maxMicros) {
    return { ok: false, error: `The ${label} can't exceed ${formatUsdMicros(maxMicros)}.` };
  }
  return { ok: true, micros };
}

/** Render integer micros as a clean editable USD string ("" when 0/no limit). */
function microsToInput(micros: number): string {
  if (!Number.isFinite(micros) || micros <= 0) return "";
  const whole = Math.floor(micros / 1_000_000);
  const fraction = micros % 1_000_000;
  if (fraction === 0) return String(whole);
  const frac = String(fraction).padStart(6, "0").replace(/0+$/, "");
  return `${whole}.${frac}`;
}

/** Human copy for a ceiling value, treating 0 as an explicit "No limit". */
function describeLimit(micros: number): string {
  return micros > 0 ? formatUsdMicros(micros) : "No limit";
}

function pickSelected(
  sendable: readonly WalletSource[],
  current: string | null,
): string | null {
  if (current && sendable.some((s) => s.source_account_id === current)) return current;
  return sendable[0]?.source_account_id ?? null;
}

export default function WalletTransferPolicyScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [sources, setSources] = useState<readonly WalletSource[]>([]);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [limits, setLimits] = useState<SourceLimits | null>(null);
  const [perTransferInput, setPerTransferInput] = useState("");
  const [dailyInput, setDailyInput] = useState("");

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const selectedSource = useMemo(
    () => sources.find((s) => s.source_account_id === sourceId) ?? null,
    [sources, sourceId],
  );

  /** Seed the editable inputs from an authoritative limits block. */
  const seedFromLimits = useCallback((next: SourceLimits) => {
    setLimits(next);
    setPerTransferInput(microsToInput(next.per_transfer_micros));
    setDailyInput(microsToInput(next.daily_micros));
  }, []);

  /**
   * Read the policy for one source. Prefers GET /wallet/transfer-policy; if
   * that read fails, falls back to the `limits` already carried on the source
   * so the screen is never left without an authoritative starting point.
   */
  const loadPolicy = useCallback(
    async (source: WalletSource) => {
      setPolicyLoading(true);
      setError(null);
      setSaved(false);
      try {
        const policy = await getTransferPolicy(source.source_account_id, { token });
        seedFromLimits(policy.limits);
      } catch {
        seedFromLimits(source.limits);
      } finally {
        setPolicyLoading(false);
      }
    },
    [token, seedFromLimits],
  );

  const load = useCallback(async () => {
    setError(null);
    try {
      const rows = await getWalletSources({ token });
      const sendable = rows.filter((s) => s.can_send);
      setSources(sendable);
      const nextId = pickSelected(sendable, sourceId);
      setSourceId(nextId);
      const active = sendable.find((s) => s.source_account_id === nextId) ?? null;
      if (active) await loadPolicy(active);
      else {
        setLimits(null);
        setPerTransferInput("");
        setDailyInput("");
      }
    } catch (err) {
      setError(errorMessage(err, "Failed to load your wallet sources."));
    }
  }, [token, sourceId, loadPolicy]);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoading(true);
      load().finally(() => {
        if (active) setLoading(false);
      });
      return () => {
        active = false;
      };
    }, [load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const onSelectSource = useCallback(
    (source: WalletSource) => {
      if (source.source_account_id === sourceId) return;
      setSourceId(source.source_account_id);
      void loadPolicy(source);
    },
    [sourceId, loadPolicy],
  );

  const perTransferParsed = useMemo(
    () => parseLimitInput(perTransferInput, PER_TRANSFER_MAX_MICROS, "per-transfer limit"),
    [perTransferInput],
  );
  const dailyParsed = useMemo(
    () => parseLimitInput(dailyInput, DAILY_MAX_MICROS, "daily limit"),
    [dailyInput],
  );

  const isDirty = useMemo(() => {
    if (!limits) return false;
    if (!perTransferParsed.ok || !dailyParsed.ok) return true;
    return (
      perTransferParsed.micros !== limits.per_transfer_micros ||
      dailyParsed.micros !== limits.daily_micros
    );
  }, [limits, perTransferParsed, dailyParsed]);

  const performSave = useCallback(async () => {
    if (!selectedSource || !perTransferParsed.ok || !dailyParsed.ok) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const result = await setTransferPolicy(
        {
          source_account_id: selectedSource.source_account_id,
          per_transfer_limit_micros: perTransferParsed.micros,
          daily_limit_micros: dailyParsed.micros,
        },
        { token },
      );
      seedFromLimits(result.limits);
      setSources((prev) =>
        prev.map((s) =>
          s.source_account_id === selectedSource.source_account_id
            ? { ...s, limits: result.limits }
            : s,
        ),
      );
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err, "Couldn't update the send limits. Try again."));
    } finally {
      setSaving(false);
    }
  }, [selectedSource, perTransferParsed, dailyParsed, token, seedFromLimits]);

  const onSave = useCallback(() => {
    if (!selectedSource) return;
    if (!perTransferParsed.ok) {
      setError(perTransferParsed.error);
      return;
    }
    if (!dailyParsed.ok) {
      setError(dailyParsed.error);
      return;
    }
    const perLine = `Per transfer: ${describeLimit(perTransferParsed.micros)}`;
    const dailyLine = `Daily: ${describeLimit(dailyParsed.micros)}`;
    Alert.alert(
      "Update send limits?",
      `${selectedSource.label}\n\n${perLine}\n${dailyLine}`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Save", style: "default", onPress: () => void performSave() },
      ],
    );
  }, [selectedSource, perTransferParsed, dailyParsed, performSave]);

  // Initial load ----------------------------------------------------------
  if (loading && sources.length === 0) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.primary} size="large" />
      </View>
    );
  }

  // Hard load error (no sources rendered) ---------------------------------
  if (error && sources.length === 0) {
    return (
      <ScrollView
        style={styles.container}
        contentContainerStyle={[styles.content, styles.center]}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
        }
      >
        <Text style={styles.emptyTitle}>Couldn't load limits</Text>
        <Text style={styles.emptyBody}>{error}</Text>
        <Text style={styles.hint}>Pull down to try again.</Text>
      </ScrollView>
    );
  }

  // No source can send ----------------------------------------------------
  if (sources.length === 0) {
    return (
      <ScrollView
        style={styles.container}
        contentContainerStyle={[styles.content, styles.center]}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
        }
      >
        <Text style={styles.emptyTitle}>No sending source</Text>
        <Text style={styles.emptyBody}>
          None of your wallet sources can send tokens yet, so there are no
          transfer limits to configure. Pull to refresh once a source is enabled.
        </Text>
      </ScrollView>
    );
  }

  const dailyUsed = limits?.daily_used_micros ?? 0;
  const dailyRemaining = limits?.daily_remaining_micros ?? null;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
      }
    >
      <Text style={styles.intro}>
        Send limits bound how much this source can transfer. Set a value to 0 to
        remove that ceiling. Limits are enforced by the server on every send.
      </Text>

      {sources.length > 1 ? (
        <>
          <Text style={styles.label}>Source</Text>
          <View style={styles.sourceList}>
            {sources.map((s) => {
              const active = s.source_account_id === sourceId;
              return (
                <Pressable
                  key={s.source_account_id}
                  style={[styles.sourceChip, active && styles.sourceChipActive]}
                  onPress={() => onSelectSource(s)}
                  accessibilityRole="button"
                  accessibilityState={{ selected: active }}
                >
                  <Text style={[styles.sourceLabel, active && styles.sourceLabelActive]}>{s.label}</Text>
                  <Text style={styles.sourceKind}>{s.kind}</Text>
                </Pressable>
              );
            })}
          </View>
        </>
      ) : (
        <View style={styles.singleSource}>
          <Text style={styles.singleSourceLabel}>{selectedSource?.label}</Text>
          <Text style={styles.sourceKind}>{selectedSource?.kind}</Text>
        </View>
      )}

      {policyLoading ? (
        <View style={styles.policyLoading}>
          <ActivityIndicator color={colors.primary} />
        </View>
      ) : limits ? (
        <View style={styles.currentCard}>
          <Text style={styles.currentTitle}>Current limits</Text>
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>Per transfer</Text>
            <Text style={styles.metaValue}>{describeLimit(limits.per_transfer_micros)}</Text>
          </View>
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>Daily (UTC)</Text>
            <Text style={styles.metaValue}>{describeLimit(limits.daily_micros)}</Text>
          </View>
          {limits.daily_micros > 0 ? (
            <>
              <View style={styles.metaRow}>
                <Text style={styles.metaLabel}>Used today</Text>
                <Text style={styles.metaValue}>{formatUsdMicros(dailyUsed)}</Text>
              </View>
              {dailyRemaining !== null ? (
                <View style={styles.metaRow}>
                  <Text style={styles.metaLabel}>Remaining today</Text>
                  <Text style={styles.metaValueStrong}>{formatUsdMicros(dailyRemaining)}</Text>
                </View>
              ) : null}
            </>
          ) : null}
        </View>
      ) : null}

      <Text style={styles.label}>Per-transfer limit</Text>
      <View style={[styles.inputWrap, !perTransferParsed.ok && styles.inputWrapError]}>
        <Text style={styles.dollar}>$</Text>
        <TextInput
          style={styles.amountInput}
          value={perTransferInput}
          onChangeText={(text) => {
            setPerTransferInput(text);
            setSaved(false);
            setError(null);
          }}
          placeholder="0 = no limit"
          placeholderTextColor={colors.muted}
          keyboardType="decimal-pad"
          inputMode="decimal"
          editable={!saving && !policyLoading}
          accessibilityLabel="Per-transfer limit in USD"
        />
      </View>
      <Text style={styles.fieldHint}>
        {perTransferParsed.ok
          ? describeLimit(perTransferParsed.micros) === "No limit"
            ? "No per-transfer ceiling."
            : `Cap each transfer at ${describeLimit(perTransferParsed.micros)}.`
          : perTransferParsed.error}
      </Text>

      <Text style={styles.label}>Daily limit (UTC)</Text>
      <View style={[styles.inputWrap, !dailyParsed.ok && styles.inputWrapError]}>
        <Text style={styles.dollar}>$</Text>
        <TextInput
          style={styles.amountInput}
          value={dailyInput}
          onChangeText={(text) => {
            setDailyInput(text);
            setSaved(false);
            setError(null);
          }}
          placeholder="0 = no limit"
          placeholderTextColor={colors.muted}
          keyboardType="decimal-pad"
          inputMode="decimal"
          editable={!saving && !policyLoading}
          accessibilityLabel="Daily limit in USD"
        />
      </View>
      <Text style={styles.fieldHint}>
        {dailyParsed.ok
          ? describeLimit(dailyParsed.micros) === "No limit"
            ? "No daily ceiling."
            : `Cap total sends per UTC day at ${describeLimit(dailyParsed.micros)}.`
          : dailyParsed.error}
      </Text>

      {error ? <Text style={styles.error}>{error}</Text> : null}
      {saved ? <Text style={styles.savedNote}>Send limits updated.</Text> : null}

      <Pressable
        style={[
          styles.primaryButton,
          (!isDirty || saving || policyLoading || !perTransferParsed.ok || !dailyParsed.ok) &&
            styles.disabled,
        ]}
        onPress={onSave}
        disabled={!isDirty || saving || policyLoading || !perTransferParsed.ok || !dailyParsed.ok}
        accessibilityRole="button"
      >
        {saving ? (
          <ActivityIndicator color={colors.bg} />
        ) : (
          <Text style={styles.primaryButtonText}>Save limits</Text>
        )}
      </Pressable>

      <Pressable
        style={styles.secondaryButton}
        onPress={() => router.push("/wallet")}
        accessibilityRole="button"
      >
        <Text style={styles.secondaryButtonText}>Back to wallet</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingBottom: 48 },
  center: { flexGrow: 1, alignItems: "center", justifyContent: "center" },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 21, marginBottom: 6 },
  label: { color: colors.textSecondary, fontSize: 13, marginTop: 18, marginBottom: 8 },
  sourceList: { gap: 10 },
  sourceChip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  sourceChipActive: { borderColor: colors.primary, backgroundColor: colors.card },
  sourceLabel: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  sourceLabelActive: { color: colors.primary },
  sourceKind: { color: colors.textSecondary, fontSize: 12, marginTop: 2 },
  singleSource: {
    marginTop: 16,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  singleSourceLabel: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  policyLoading: { marginTop: 20, alignItems: "center" },
  currentCard: {
    marginTop: 18,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
  },
  currentTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700", marginBottom: 10 },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 6,
    gap: 12,
  },
  metaLabel: { color: colors.textSecondary, fontSize: 13 },
  metaValue: { color: colors.textPrimary, fontSize: 14, flexShrink: 1, textAlign: "right" },
  metaValueStrong: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  inputWrap: {
    flexDirection: "row",
    alignItems: "center",
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
  },
  inputWrapError: { borderColor: colors.error },
  dollar: { color: colors.textSecondary, fontSize: 18, fontWeight: "600" },
  amountInput: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: 20,
    fontWeight: "600",
    paddingVertical: 12,
    paddingLeft: 4,
  },
  fieldHint: { color: colors.muted, fontSize: 12, marginTop: 6 },
  error: { color: colors.error, fontSize: 14, marginTop: 16 },
  savedNote: { color: colors.success, fontSize: 14, marginTop: 16, fontWeight: "600" },
  primaryButton: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 15,
    alignItems: "center",
    marginTop: 22,
  },
  primaryButtonText: { color: colors.bg, fontSize: 16, fontWeight: "700" },
  secondaryButton: { alignItems: "center", paddingVertical: 14, marginTop: 6 },
  secondaryButtonText: { color: colors.textSecondary, fontSize: 15, fontWeight: "600" },
  disabled: { opacity: 0.5 },
  emptyTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "700", marginBottom: 8 },
  emptyBody: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 21,
    textAlign: "center",
    paddingHorizontal: 20,
  },
  hint: { color: colors.muted, fontSize: 13, marginTop: 12 },
});
