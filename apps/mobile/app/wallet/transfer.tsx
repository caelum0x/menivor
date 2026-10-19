/**
 * Route: /wallet/transfer — send Mint-backed AI tokens to a public handle.
 *
 * A staged, server-authoritative transfer flow (no local money math, no secrets):
 *   1. GET /wallet/sources          → getWalletSources (pick a can-send source)
 *   2. GET /wallet/saved-recipients → getSavedRecipients (tap to prefill)
 *   3. GET /wallet/recipients/{h}   → resolveTransferRecipient (verify handle)
 *   4. POST /wallet/transfer-challenges → createTransferChallenge (binds the
 *      exact source + recipient + amount; carries an expiry)
 *   5. POST /wallet/transfers       → sendWalletTransfer with a stable
 *      Idempotency-Key so an ambiguous retry never sends twice.
 *
 * Amounts are validated client-side against the source's per-transfer /
 * remaining-daily limits before a challenge is requested (the backend enforces
 * them authoritatively too). Every stage owns its loading / error state.
 */

import { useCallback, useState } from "react";
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
  createTransferChallenge,
  getSavedRecipients,
  getWalletSources,
  newTransferIdempotencyKey,
  parseUsdMicros,
  resolveTransferRecipient,
  sendWalletTransfer,
  type WalletSavedRecipient,
  type WalletSource,
  type WalletTransferChallenge,
  type WalletTransferRecipient,
  type WalletTransferResult,
} from "@/lib/wallet";
import { formatDate } from "@/components/wallet/format";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

/** Result statuses that prove the transfer did not settle (no tokens moved). */
const FAILED_TRANSFER_STATUSES: ReadonlySet<string> = new Set([
  "failed",
  "rejected",
  "cancelled",
  "canceled",
  "expired",
]);

/** Client-side guard mirroring the source limits (server still enforces). */
function amountExceedsLimits(micros: number, source: WalletSource): string | null {
  const { per_transfer_micros, daily_remaining_micros } = source.limits;
  if (per_transfer_micros > 0 && micros > per_transfer_micros) {
    return `Above the per-transfer limit of ${formatUsdMicros(per_transfer_micros)}.`;
  }
  if (daily_remaining_micros !== null && micros > daily_remaining_micros) {
    return `Above today's remaining limit of ${formatUsdMicros(daily_remaining_micros)}.`;
  }
  return null;
}

export default function WalletTransferScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [sources, setSources] = useState<readonly WalletSource[]>([]);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [saved, setSaved] = useState<readonly WalletSavedRecipient[]>([]);
  const [handle, setHandle] = useState("");
  const [recipient, setRecipient] = useState<WalletTransferRecipient | null>(null);
  const [amount, setAmount] = useState("");
  const [challenge, setChallenge] = useState<WalletTransferChallenge | null>(null);
  const [result, setResult] = useState<WalletTransferResult | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedSource = sources.find((s) => s.source_account_id === sourceId) ?? null;

  const loadSaved = useCallback(
    async (accountId: string) => {
      try {
        const rows = await getSavedRecipients(accountId, { token });
        setSaved(rows);
      } catch {
        // Saved recipients are a convenience; a failure must not block sending.
        setSaved([]);
      }
    },
    [token],
  );

  const load = useCallback(async () => {
    setError(null);
    try {
      const rows = await getWalletSources({ token });
      const sendable = rows.filter((s) => s.can_send);
      setSources(sendable);
      const first = sendable[0]?.source_account_id ?? null;
      setSourceId((current) => current ?? first);
      const active = stillSelected(sendable, sourceId) ?? first;
      if (active) await loadSaved(active);
    } catch (err) {
      setError(errorMessage(err, "Failed to load your wallet sources."));
    }
  }, [token, sourceId, loadSaved]);

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
    (id: string) => {
      setSourceId(id);
      setRecipient(null);
      setChallenge(null);
      void loadSaved(id);
    },
    [loadSaved],
  );

  const onResolve = useCallback(async () => {
    const trimmed = handle.trim();
    if (!trimmed) {
      setError("Enter a recipient handle.");
      return;
    }
    setResolving(true);
    setError(null);
    setChallenge(null);
    try {
      const found = await resolveTransferRecipient(trimmed, { token });
      if (!found.can_receive) {
        setRecipient(null);
        setError(`${found.display_name} can't receive tokens right now.`);
        return;
      }
      setRecipient(found);
    } catch (err) {
      setRecipient(null);
      setError(errorMessage(err, "Couldn't find that handle."));
    } finally {
      setResolving(false);
    }
  }, [handle, token]);

  const onReview = useCallback(async () => {
    if (!selectedSource || !recipient) return;
    const micros = parseUsdMicros(amount);
    if (micros === null) {
      setError("Enter a valid amount, e.g. 5 or 5.25.");
      return;
    }
    const limitError = amountExceedsLimits(micros, selectedSource);
    if (limitError) {
      setError(limitError);
      return;
    }
    setReviewing(true);
    setError(null);
    try {
      const ch = await createTransferChallenge(
        {
          source_account_id: selectedSource.source_account_id,
          recipient_handle: recipient.handle,
          amount_micros: micros,
        },
        newTransferIdempotencyKey(),
        { token },
      );
      setChallenge(ch);
    } catch (err) {
      setError(errorMessage(err, "Couldn't prepare the transfer. Try again."));
    } finally {
      setReviewing(false);
    }
  }, [amount, recipient, selectedSource, token]);

  const performSend = useCallback(async () => {
    if (!selectedSource || !recipient || !challenge) return;
    setSending(true);
    setError(null);
    try {
      const res = await sendWalletTransfer(
        {
          source_account_id: selectedSource.source_account_id,
          challenge_id: challenge.challenge_id,
          recipient_handle: recipient.handle,
          amount_micros: challenge.amount_micros,
        },
        newTransferIdempotencyKey(),
        { token },
      );
      if (FAILED_TRANSFER_STATUSES.has(res.status.toLowerCase())) {
        setError(`Transfer failed (${res.status}). No tokens were sent.`);
        setChallenge(null);
        return;
      }
      setResult(res);
      setChallenge(null);
    } catch (err) {
      setError(errorMessage(err, "The transfer couldn't be completed."));
    } finally {
      setSending(false);
    }
  }, [challenge, recipient, selectedSource, token]);

  const onConfirmSend = useCallback(() => {
    if (!challenge || !recipient) return;
    Alert.alert(
      "Send tokens?",
      `Send ${formatUsdMicros(challenge.amount_micros)} to ${recipient.display_name} (@${recipient.handle}).`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Send", style: "default", onPress: () => void performSend() },
      ],
    );
  }, [challenge, recipient, performSend]);

  const reset = useCallback(() => {
    setResult(null);
    setRecipient(null);
    setChallenge(null);
    setHandle("");
    setAmount("");
    setError(null);
  }, []);

  if (loading && sources.length === 0) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.primary} size="large" />
      </View>
    );
  }

  // Success state ---------------------------------------------------------
  if (result) {
    return (
      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        <View style={styles.successCard}>
          <Text style={styles.successTitle}>Sent {result.amount_usd}</Text>
          <Text style={styles.successBody}>
            To {result.recipient.display_name} (@{result.recipient.handle})
          </Text>
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>Status</Text>
            <Text style={styles.metaValue}>{result.status}</Text>
          </View>
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>Transfer ID</Text>
            <Text style={styles.metaValue} numberOfLines={1}>{result.transfer_id}</Text>
          </View>
          {result.completed_at ? (
            <View style={styles.metaRow}>
              <Text style={styles.metaLabel}>Completed</Text>
              <Text style={styles.metaValue}>{formatDate(result.completed_at)}</Text>
            </View>
          ) : null}
          {result.sender_balance ? (
            <View style={styles.metaRow}>
              <Text style={styles.metaLabel}>New balance</Text>
              <Text style={styles.metaValue}>
                {formatUsdMicros(result.sender_balance.available_micros)}
              </Text>
            </View>
          ) : null}
          {result.idempotent_replay ? (
            <Text style={styles.replayNote}>This was a safe replay — no double send.</Text>
          ) : null}
        </View>
        <Pressable style={styles.primaryButton} onPress={reset} accessibilityRole="button">
          <Text style={styles.primaryButtonText}>Send another</Text>
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

  // No sendable source ----------------------------------------------------
  if (sources.length === 0) {
    return (
      <ScrollView
        style={styles.container}
        contentContainerStyle={[styles.content, styles.center]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
      >
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Text style={styles.emptyTitle}>No sending source</Text>
        <Text style={styles.emptyBody}>
          None of your wallet sources can send tokens yet. Pull to refresh once a
          source is enabled.
        </Text>
      </ScrollView>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
    >
      {sources.length > 1 ? (
        <>
          <Text style={styles.label}>From</Text>
          <View style={styles.sourceList}>
            {sources.map((s) => {
              const active = s.source_account_id === sourceId;
              return (
                <Pressable
                  key={s.source_account_id}
                  style={[styles.sourceChip, active && styles.sourceChipActive]}
                  onPress={() => onSelectSource(s.source_account_id)}
                  accessibilityRole="button"
                  accessibilityState={{ selected: active }}
                >
                  <Text style={[styles.sourceLabel, active && styles.sourceLabelActive]}>{s.label}</Text>
                  <Text style={[styles.sourceKind, active && styles.sourceKindActive]}>{s.kind}</Text>
                </Pressable>
              );
            })}
          </View>
        </>
      ) : null}

      {selectedSource && selectedSource.limits.daily_remaining_micros !== null ? (
        <Text style={styles.limitNote}>
          {formatUsdMicros(selectedSource.limits.daily_remaining_micros)} remaining today
        </Text>
      ) : null}

      <Text style={styles.label}>Recipient handle</Text>
      <View style={styles.inlineRow}>
        <TextInput
          style={styles.textInput}
          value={handle}
          onChangeText={(text) => {
            setHandle(text);
            setRecipient(null);
            setChallenge(null);
          }}
          placeholder="@handle or address"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          autoCorrect={false}
          editable={!resolving && !sending}
          returnKeyType="search"
          onSubmitEditing={() => void onResolve()}
          accessibilityLabel="Recipient handle"
        />
        <Pressable
          style={[styles.inlineButton, (resolving || sending) && styles.disabled]}
          onPress={() => void onResolve()}
          disabled={resolving || sending}
          accessibilityRole="button"
        >
          {resolving ? (
            <ActivityIndicator color={colors.bg} size="small" />
          ) : (
            <Text style={styles.inlineButtonText}>Check</Text>
          )}
        </Pressable>
      </View>

      {saved.length > 0 ? (
        <View style={styles.savedWrap}>
          <Text style={styles.savedTitle}>Saved</Text>
          <View style={styles.savedRow}>
            {saved.map((r) => (
              <Pressable
                key={r.saved_recipient_id}
                style={styles.savedChip}
                onPress={() => {
                  setHandle(r.handle);
                  setRecipient(null);
                  setChallenge(null);
                }}
                accessibilityRole="button"
              >
                <Text style={styles.savedChipText}>
                  {r.label || r.display_name || `@${r.handle}`}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>
      ) : null}

      {recipient ? (
        <View style={styles.recipientCard}>
          <Text style={styles.recipientName}>{recipient.display_name}</Text>
          <Text style={styles.recipientHandle}>@{recipient.handle} · {recipient.kind}</Text>
        </View>
      ) : null}

      {recipient ? (
        <>
          <Text style={styles.label}>Amount</Text>
          <View style={styles.inputWrap}>
            <Text style={styles.dollar}>$</Text>
            <TextInput
              style={styles.amountInput}
              value={amount}
              onChangeText={(text) => {
                setAmount(text);
                setChallenge(null);
              }}
              placeholder="0.00"
              placeholderTextColor={colors.muted}
              keyboardType="decimal-pad"
              inputMode="decimal"
              editable={!reviewing && !sending}
              accessibilityLabel="Amount in USD"
            />
          </View>
        </>
      ) : null}

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {challenge ? (
        <View style={styles.reviewCard}>
          <Text style={styles.reviewTitle}>Confirm transfer</Text>
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>Amount</Text>
            <Text style={styles.metaValueStrong}>{formatUsdMicros(challenge.amount_micros)}</Text>
          </View>
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>To</Text>
            <Text style={styles.metaValue}>{challenge.recipient.display_name}</Text>
          </View>
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>From</Text>
            <Text style={styles.metaValue}>{challenge.source.label}</Text>
          </View>
          <Pressable
            style={[styles.primaryButton, sending && styles.disabled]}
            onPress={onConfirmSend}
            disabled={sending}
            accessibilityRole="button"
          >
            {sending ? (
              <ActivityIndicator color={colors.bg} />
            ) : (
              <Text style={styles.primaryButtonText}>Send now</Text>
            )}
          </Pressable>
        </View>
      ) : recipient ? (
        <Pressable
          style={[styles.primaryButton, (reviewing || sending) && styles.disabled]}
          onPress={() => void onReview()}
          disabled={reviewing || sending}
          accessibilityRole="button"
        >
          {reviewing ? (
            <ActivityIndicator color={colors.bg} />
          ) : (
            <Text style={styles.primaryButtonText}>Review transfer</Text>
          )}
        </Pressable>
      ) : null}
    </ScrollView>
  );
}

/** Pick the still-present selected source id, else null (helper for reload). */
function stillSelected(
  sendable: readonly WalletSource[],
  current: string | null,
): string | null {
  if (current && sendable.some((s) => s.source_account_id === current)) return current;
  return null;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingBottom: 48 },
  center: { flexGrow: 1, alignItems: "center", justifyContent: "center" },
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
  sourceKindActive: { color: colors.textSecondary },
  limitNote: { color: colors.muted, fontSize: 12, marginTop: 10 },
  inlineRow: { flexDirection: "row", gap: 10, alignItems: "center" },
  textInput: {
    flex: 1,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: colors.textPrimary,
    fontSize: 16,
  },
  inlineButton: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingHorizontal: 20,
    paddingVertical: 13,
    minWidth: 76,
    alignItems: "center",
  },
  inlineButtonText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  disabled: { opacity: 0.5 },
  savedWrap: { marginTop: 14 },
  savedTitle: { color: colors.textSecondary, fontSize: 12, marginBottom: 8 },
  savedRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  savedChip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  savedChipText: { color: colors.textPrimary, fontSize: 13, fontWeight: "500" },
  recipientCard: {
    marginTop: 16,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  recipientName: { color: colors.textPrimary, fontSize: 16, fontWeight: "600" },
  recipientHandle: { color: colors.textSecondary, fontSize: 13, marginTop: 3 },
  inputWrap: {
    flexDirection: "row",
    alignItems: "center",
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
  },
  dollar: { color: colors.textSecondary, fontSize: 18, fontWeight: "600" },
  amountInput: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: 20,
    fontWeight: "600",
    paddingVertical: 12,
    paddingLeft: 4,
  },
  error: { color: colors.error, fontSize: 14, marginTop: 16 },
  reviewCard: {
    marginTop: 20,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
  },
  reviewTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "700", marginBottom: 12 },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 6,
    gap: 12,
  },
  metaLabel: { color: colors.textSecondary, fontSize: 13 },
  metaValue: { color: colors.textPrimary, fontSize: 14, flexShrink: 1, textAlign: "right" },
  metaValueStrong: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  primaryButton: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 15,
    alignItems: "center",
    marginTop: 20,
  },
  primaryButtonText: { color: colors.bg, fontSize: 16, fontWeight: "700" },
  secondaryButton: { alignItems: "center", paddingVertical: 14, marginTop: 6 },
  secondaryButtonText: { color: colors.textSecondary, fontSize: 15, fontWeight: "600" },
  successCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 16,
    padding: 20,
  },
  successTitle: { color: colors.success, fontSize: 24, fontWeight: "800" },
  successBody: { color: colors.textPrimary, fontSize: 15, marginTop: 6, marginBottom: 14 },
  replayNote: { color: colors.textSecondary, fontSize: 12, marginTop: 12, fontStyle: "italic" },
  emptyTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "700", marginBottom: 8 },
  emptyBody: { color: colors.textSecondary, fontSize: 14, lineHeight: 21, textAlign: "center", paddingHorizontal: 20 },
});
