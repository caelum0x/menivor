/**
 * Route: /wallet/top-up — add USD credit to the wallet.
 *
 * Server-authoritative flow (no local money math):
 *   1. Pick a preset OR type a custom amount (validated with parseUsdMicros).
 *   2. POST /wallet/purchase-quotes → purchaseQuote returns the exact
 *      credit + fee + tax + total breakdown, rendered via TopUpQuoteSheet.
 *   3. Confirm → POST /wallet/checkout → createWalletCheckout with a stable
 *      Idempotency-Key; the hosted checkout_url is opened in the browser.
 *
 * LAUNCH GATE: checkout is fenced off during pilot — a 403 ApiError is caught
 * and rendered as a calm "not yet enabled" state, never a crash. Credit is
 * granted by the payment webhook, not on this device.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { ApiError } from "@/src/shared/api";
import {
  createWalletCheckout,
  newIdempotencyKey,
  parseUsdMicros,
  purchaseQuote,
  type PurchaseQuote,
} from "@/lib/wallet";
import { TopUpQuoteSheet } from "@/src/features/wallet-publish";
import {
  externalCheckoutAvailable,
  openCheckoutUrl,
} from "@/components/billing/open-checkout";
import { StoreBillingNotice } from "@/components/billing/StoreBillingNotice";
import { StoreCreditPacks } from "@/components/billing/StoreCreditPacks";
import { LaunchStatusBanner } from "@/components/launch/LaunchStatusBanner";
import { useLaunchStatus } from "@/src/shared/hooks";
import { colors as storeNoticeColors } from "@/src/shared/theme";

const storeNoticeBg = storeNoticeColors.bg;

const PRESET_AMOUNTS: readonly string[] = ["5", "10", "25", "50", "100"];

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

/** Normalize + validate a decimal USD string; returns the amount or null. */
function validAmount(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return parseUsdMicros(trimmed) === null ? null : trimmed;
}

/**
 * Store builds cannot sell digital goods through a hosted web checkout
 * (App Store 3.1.1 / Play payments policy); they sell consumable credit packs
 * through the store (StoreCreditPacks) next to the in-app Pro offer instead.
 * Web and internal builds keep the full checkout flow.
 */
export default function WalletTopUpScreen() {
  if (!externalCheckoutAvailable()) {
    return (
      <ScrollView
        style={{ flex: 1, backgroundColor: storeNoticeBg }}
        contentContainerStyle={{ padding: 16, gap: 16 }}
      >
        <StoreCreditPacks />
        <StoreBillingNotice
          subject="Credit top-ups"
          title="Menivor Pro"
          body="Pro is the in-app subscription: it unlocks export, the clean MP4, public share links and scheduled publishing. Generation itself spends wallet credits."
        />
      </ScrollView>
    );
  }
  return <WalletTopUpFlow />;
}

function WalletTopUpFlow() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const launch = useLaunchStatus(token);

  const [selected, setSelected] = useState<string | null>(null);
  const [custom, setCustom] = useState("");
  const [quote, setQuote] = useState<PurchaseQuote | null>(null);
  const [idemKey, setIdemKey] = useState("");
  const [quoting, setQuoting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [gated, setGated] = useState(false);

  const requestQuote = useCallback(
    async (amount: string) => {
      setQuote(null);
      setError(null);
      setGated(false);
      setQuoting(true);
      try {
        const result = await purchaseQuote(amount, { token });
        setQuote(result);
        setIdemKey(newIdempotencyKey());
      } catch (err) {
        setError(errorMessage(err, "Couldn't fetch a quote. Try again."));
      } finally {
        setQuoting(false);
      }
    },
    [token],
  );

  const onPreset = useCallback(
    (value: string) => {
      setSelected(value);
      setCustom("");
      void requestQuote(value);
    },
    [requestQuote],
  );

  const onCustomQuote = useCallback(() => {
    const amount = validAmount(custom);
    if (!amount) {
      setError("Enter a valid amount, e.g. 15 or 15.50.");
      return;
    }
    setSelected(null);
    void requestQuote(amount);
  }, [custom, requestQuote]);

  const dismissQuote = useCallback(() => {
    setQuote(null);
    setSelected(null);
    setError(null);
  }, []);

  const activeAmount = selected ?? validAmount(custom);

  const onConfirm = useCallback(async () => {
    if (!activeAmount || !idemKey) return;
    setSubmitting(true);
    setError(null);
    try {
      const intent = await createWalletCheckout(
        { amount_usd: activeAmount },
        idemKey,
        { token },
      );
      if (intent.checkout_url) {
        await openCheckoutUrl(intent.checkout_url);
      } else {
        Alert.alert(
          "Top-up started",
          "Your checkout intent was created. Credit is added once payment confirms.",
        );
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setGated(true);
      } else {
        setError(errorMessage(err, "Couldn't start checkout. Try again."));
      }
    } finally {
      setSubmitting(false);
    }
  }, [activeAmount, idemKey, token]);

  if (gated) {
    return (
      <View style={[styles.container, styles.center]}>
        <Text style={styles.gatedTitle}>Top-up isn&apos;t enabled yet</Text>
        <Text style={styles.gatedBody}>
          Wallet top-up is being switched on gradually. Your balance and usage keep
          working — check back soon to add credit.
        </Text>
        <Pressable
          style={styles.gatedButton}
          onPress={() => {
            setGated(false);
            setQuote(null);
            setSelected(null);
          }}
          accessibilityRole="button"
        >
          <Text style={styles.gatedButtonText}>Back</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <LaunchStatusBanner status={launch.status} gate="checkout" />
      <Text style={styles.intro}>
        Choose how much credit to add. The exact fee, tax and total are quoted by
        the server on the next step.
      </Text>

      <View style={styles.chips}>
        {PRESET_AMOUNTS.map((value) => {
          const active = selected === value;
          return (
            <Pressable
              key={value}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => onPreset(value)}
              disabled={quoting || submitting}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              accessibilityLabel={`Add $${value}`}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>${value}</Text>
            </Pressable>
          );
        })}
      </View>

      <Text style={styles.customLabel}>Or enter a custom amount</Text>
      <View style={styles.customRow}>
        <View style={styles.inputWrap}>
          <Text style={styles.dollar}>$</Text>
          <TextInput
            style={styles.input}
            value={custom}
            onChangeText={(text) => {
              setCustom(text);
              setSelected(null);
            }}
            placeholder="0.00"
            placeholderTextColor={colors.muted}
            keyboardType="decimal-pad"
            inputMode="decimal"
            editable={!quoting && !submitting}
            accessibilityLabel="Custom top-up amount in USD"
            returnKeyType="done"
            onSubmitEditing={onCustomQuote}
          />
        </View>
        <Pressable
          style={[styles.quoteButton, (quoting || submitting) && styles.quoteButtonDisabled]}
          onPress={onCustomQuote}
          disabled={quoting || submitting}
          accessibilityRole="button"
        >
          <Text style={styles.quoteButtonText}>Quote</Text>
        </Pressable>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {quoting ? (
        <ActivityIndicator color={colors.primary} style={styles.spinner} />
      ) : quote ? (
        <TopUpQuoteSheet
          quote={quote}
          submitting={submitting}
          onConfirm={() => void onConfirm()}
          onDismiss={dismissQuote}
        />
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: 32 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20, marginBottom: 16 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 20 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 18,
    paddingVertical: 12,
    minWidth: 72,
    alignItems: "center",
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textPrimary, fontSize: 16, fontWeight: "600" },
  chipTextActive: { color: colors.bg },
  customLabel: { color: colors.textSecondary, fontSize: 13, marginBottom: 8 },
  customRow: { flexDirection: "row", gap: 10, alignItems: "center" },
  inputWrap: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
  },
  dollar: { color: colors.textSecondary, fontSize: 18, fontWeight: "600" },
  input: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: "600",
    paddingVertical: 12,
    paddingLeft: 4,
  },
  quoteButton: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingHorizontal: 20,
    paddingVertical: 13,
    alignItems: "center",
  },
  quoteButtonDisabled: { opacity: 0.5 },
  quoteButtonText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  spinner: { marginTop: 20 },
  error: { color: colors.error, fontSize: 14, marginTop: 14 },
  gatedTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: "700",
    marginBottom: 10,
    textAlign: "center",
  },
  gatedBody: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 21,
    textAlign: "center",
    marginBottom: 22,
  },
  gatedButton: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 28,
    paddingVertical: 12,
  },
  gatedButtonText: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
});
