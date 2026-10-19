/**
 * In-app (App Store / Play) generation-credit packs for store builds.
 *
 * Server-authoritative: the backend lists which store products it honours and
 * how many credits each grants, the store sheet takes payment, and the backend
 * verifies the transaction with RevenueCat before crediting the wallet. The
 * device never grants credits. When the backend has no store-credit rail the
 * section explains that and renders no buy buttons, so nobody can pay for
 * credits that cannot be delivered.
 *
 * Every pack shows its per-reel price (store price / credits, one credit per
 * reel) and the Creator Contract promises: credits never expire, failed
 * renders are refunded automatically.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { useRouter } from "expo-router";

import { Icon } from "@/components/ui/Icon";
import { useSession } from "@/src/shared/auth";
import { useRevenueCat } from "@/src/shared/billing";
import {
  StorePurchaseCancelledError,
  getStoreCreditProducts,
  purchaseStoreCreditProduct,
  type StoreCreditProduct,
  type StoreCreditPurchase,
} from "@/src/shared/billing/revenuecat-adapter";
import {
  addPendingStoreCredit,
  isDefinitiveRedeemRejection,
  listStoreCreditPacks,
  loadPendingStoreCredits,
  redeemStoreCreditPurchase,
  removePendingStoreCredit,
  type StoreCreditPack,
} from "@/src/shared/billing/store-credits";
import {
  PACK_TRUST_NOTE,
  lowestPerReelIndex,
  perReelLabel,
  reelsLabel,
} from "@/src/shared/billing/per-reel";
import { CREATOR_CONTRACT_ROUTE } from "@/src/shared/legal/legal-links";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

interface PackRow {
  pack: StoreCreditPack;
  product: StoreCreditProduct;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "unavailable"; reason: string }
  | { kind: "ready"; rows: PackRow[] }
  | { kind: "error"; message: string };

const READY_STATUSES = new Set(["active", "inactive", "stale"]);

function messageOf(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message.replace(/^[A-Za-z0-9_-]{8,}:\s+/, "");
  }
  return fallback;
}

export interface StoreCreditPacksProps {
  /** Called after credits land, so the parent can refresh a balance. */
  readonly onCredited?: (creditsGranted: number) => void;
}

export function StoreCreditPacks({ onCredited }: StoreCreditPacksProps) {
  const router = useRouter();
  const { apiKey } = useSession();
  const { snapshot } = useRevenueCat();
  const token = apiKey ?? undefined;
  const accountId = snapshot.appUserId;
  const storeReady = accountId !== null && READY_STATUSES.has(snapshot.status);

  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [pending, setPending] = useState<StoreCreditPurchase[]>([]);
  const [busyProduct, setBusyProduct] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const retryingRef = useRef(false);

  const redeem = useCallback(
    async (purchase: StoreCreditPurchase): Promise<boolean> => {
      if (!accountId) return false;
      try {
        const result = await redeemStoreCreditPurchase(purchase, { token });
        setPending(await removePendingStoreCredit(accountId, purchase.transactionId));
        const granted = Math.max(0, Math.round(result.credits_granted ?? 0));
        setNotice(
          result.already_redeemed
            ? "This purchase was already added to your wallet."
            : `${granted} credits added to your wallet.`,
        );
        onCredited?.(granted);
        return true;
      } catch (err) {
        if (isDefinitiveRedeemRejection(err)) {
          setPending(await removePendingStoreCredit(accountId, purchase.transactionId));
          setError(
            `The purchase could not be credited: ${messageOf(err, "rejected")}. ` +
              `Contact support with transaction ${purchase.transactionId}.`,
          );
        } else {
          setError(
            "Payment went through, but the credits could not be confirmed yet. " +
              "They will be added automatically when you retry.",
          );
        }
        return false;
      }
    },
    [accountId, onCredited, token],
  );

  const retryPending = useCallback(async () => {
    if (!accountId || retryingRef.current) return;
    retryingRef.current = true;
    try {
      const rows = await loadPendingStoreCredits(accountId);
      setPending(rows);
      for (const row of rows) {
        await redeem(row);
      }
    } finally {
      retryingRef.current = false;
    }
  }, [accountId, redeem]);

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    setError(null);
    if (!token) {
      setState({ kind: "unavailable", reason: "Sign in to buy credits." });
      return;
    }
    if (!storeReady) {
      setState({
        kind: "unavailable",
        reason:
          snapshot.status === "loading"
            ? "Connecting to the store..."
            : "In-app purchases are not available on this device right now.",
      });
      return;
    }
    try {
      const packs = await listStoreCreditPacks({ token });
      if (packs === null || packs.length === 0) {
        setState({
          kind: "unavailable",
          reason: "Credit packs are not on sale in the app yet. Your current balance keeps working.",
        });
        return;
      }
      const products = await getStoreCreditProducts(packs.map((pack) => pack.product_id));
      const byId = new Map(products.map((product) => [product.productId, product]));
      const rows = packs
        .map((pack) => {
          const product = byId.get(pack.product_id);
          return product ? { pack, product } : null;
        })
        .filter((row): row is PackRow => row !== null)
        .sort((a, b) => a.pack.credits - b.pack.credits);
      setState(
        rows.length > 0
          ? { kind: "ready", rows }
          : {
              kind: "unavailable",
              reason: "Credit packs are not available in your store region yet.",
            },
      );
    } catch (err) {
      setState({ kind: "error", message: messageOf(err, "Couldn't load credit packs.") });
    }
  }, [snapshot.status, storeReady, token]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (storeReady && token) void retryPending();
  }, [retryPending, storeReady, token]);

  const onBuy = useCallback(
    async (row: PackRow) => {
      if (!accountId) return;
      setBusyProduct(row.product.productId);
      setError(null);
      setNotice(null);
      try {
        const purchase = await purchaseStoreCreditProduct(row.product.productId);
        // Persist before redeeming so a crash or network loss cannot lose it.
        setPending(await addPendingStoreCredit(accountId, purchase));
        await redeem(purchase);
      } catch (err) {
        if (!(err instanceof StorePurchaseCancelledError)) {
          setError(messageOf(err, "The purchase did not complete."));
        }
      } finally {
        setBusyProduct(null);
      }
    },
    [accountId, redeem],
  );

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Icon name="flash-outline" size={20} color={colors.accent} />
        <Text style={styles.title}>Generation credits</Text>
      </View>
      <Text style={styles.body}>
        One credit makes one finished reel. Credits also pay for B-roll, voice
        and clipping. Packs are one-time purchases through your store account.
      </Text>
      <View style={styles.trustRow}>
        <Icon name="shield-checkmark-outline" size={16} color={colors.success} />
        <Text style={[styles.body, styles.flex]}>{PACK_TRUST_NOTE}</Text>
      </View>
      <Pressable
        onPress={() => router.push(CREATOR_CONTRACT_ROUTE)}
        accessibilityRole="link"
        hitSlop={8}
      >
        <Text style={styles.link}>Read the Creator Contract</Text>
      </Pressable>

      {state.kind === "loading" ? (
        <ActivityIndicator color={colors.accent} style={styles.spinner} />
      ) : null}
      {state.kind === "unavailable" ? <Text style={styles.body}>{state.reason}</Text> : null}
      {state.kind === "error" ? (
        <View style={styles.row}>
          <Text style={[styles.error, styles.flex]}>{state.message}</Text>
          <Pressable onPress={() => void load()} accessibilityRole="button" style={styles.linkBtn}>
            <Text style={styles.link}>Retry</Text>
          </Pressable>
        </View>
      ) : null}
      {state.kind === "ready"
        ? state.rows.map((row, index, rows) => {
            const busy = busyProduct === row.product.productId;
            const perReel = perReelLabel({
              price: row.product.price,
              credits: row.pack.credits,
              currencyCode: row.product.currencyCode,
            });
            const bestValue =
              index ===
              lowestPerReelIndex(
                rows.map((r) => ({
                  price: r.product.price,
                  credits: r.pack.credits,
                  currencyCode: r.product.currencyCode,
                })),
              );
            return (
              <Pressable
                key={row.product.productId}
                style={[styles.pack, (busyProduct !== null) && styles.disabled]}
                onPress={() => void onBuy(row)}
                disabled={busyProduct !== null}
                accessibilityRole="button"
                accessibilityLabel={`Buy ${row.pack.credits} credits for ${row.product.priceString}${
                  perReel ? `, ${perReel}` : ""
                }`}
              >
                <View style={styles.flex}>
                  <Text style={styles.packTitle}>
                    {row.pack.label?.trim() || `${row.pack.credits} credits`}
                  </Text>
                  <Text style={styles.packMeta}>
                    {row.pack.credits} credits · {reelsLabel(row.pack.credits)} · never expire
                  </Text>
                  {perReel ? (
                    <View style={styles.chipRow}>
                      <View style={styles.perReelChip}>
                        <Text style={styles.perReelText}>{perReel}</Text>
                      </View>
                      {bestValue ? <Text style={styles.bestValue}>Lowest per reel</Text> : null}
                    </View>
                  ) : null}
                </View>
                {busy ? (
                  <ActivityIndicator color={colors.onAccent} />
                ) : (
                  <Text style={styles.price}>{row.product.priceString}</Text>
                )}
              </Pressable>
            );
          })
        : null}

      {pending.length > 0 ? (
        <View style={styles.row}>
          <Text style={[styles.body, styles.flex]}>
            {pending.length === 1
              ? "1 paid purchase is waiting to be credited."
              : `${pending.length} paid purchases are waiting to be credited.`}
          </Text>
          <Pressable
            onPress={() => void retryPending()}
            accessibilityRole="button"
            style={styles.linkBtn}
          >
            <Text style={styles.link}>Retry now</Text>
          </Pressable>
        </View>
      ) : null}
      {notice ? <Text style={styles.success}>{notice}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  title: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700" },
  body: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  spinner: { marginVertical: spacing.md },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  flex: { flex: 1 },
  pack: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: 12,
    paddingHorizontal: spacing.lg,
    gap: spacing.md,
  },
  packTitle: { color: colors.onAccent, fontSize: typeScale.body, fontWeight: "700" },
  packMeta: { color: colors.onAccent, fontSize: typeScale.micro, opacity: 0.75 },
  chipRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.xs },
  perReelChip: {
    alignSelf: "flex-start",
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.onAccent,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  perReelText: { color: colors.onAccent, fontSize: typeScale.micro, fontWeight: "700" },
  bestValue: { color: colors.onAccent, fontSize: typeScale.micro, fontWeight: "700" },
  trustRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  price: { color: colors.onAccent, fontSize: typeScale.body, fontWeight: "700" },
  disabled: { opacity: 0.6 },
  linkBtn: { paddingVertical: spacing.xs, paddingHorizontal: spacing.sm },
  link: { color: colors.accent, fontSize: typeScale.caption, fontWeight: "700" },
  success: { color: colors.success, fontSize: typeScale.caption },
  error: { color: colors.danger, fontSize: typeScale.caption },
});
