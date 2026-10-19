/**
 * Hosted credit packs with their per-reel price, for builds that may sell
 * outside the app stores (web and internal builds; `externalCheckoutAvailable`).
 * Store builds use StoreCreditPacks instead, priced by the store.
 *
 * Prices and credit counts come from GET /credit-packs; buying opens the
 * hosted checkout and credits are granted by the server on payment
 * confirmation, never on the device.
 */

import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { useRouter } from "expo-router";

import { Icon } from "@/components/ui/Icon";
import { openCheckoutUrl } from "@/components/billing/open-checkout";
import {
  listCreditPacks,
  startWebCreditPackCheckout,
  type CreditPackCatalog,
} from "@/lib/credit-packs";
import {
  PACK_TRUST_NOTE,
  lowestPerReelIndex,
  perReelLabel,
  reelsLabel,
} from "@/src/shared/billing/per-reel";
import { isAbortError } from "@/src/shared/api";
import { CREATOR_CONTRACT_ROUTE } from "@/src/shared/legal/legal-links";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

export interface CreditPackPricingProps {
  readonly token: string | undefined;
}

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export function CreditPackPricing({ token }: CreditPackPricingProps) {
  const router = useRouter();
  const [catalog, setCatalog] = useState<CreditPackCatalog | null>(null);
  const [error, setError] = useState("");
  const [buying, setBuying] = useState<string | null>(null);
  const [buyError, setBuyError] = useState("");

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setError("");
      try {
        setCatalog(await listCreditPacks({}, { token, signal }));
      } catch (err) {
        if (isAbortError(err)) return;
        setError(messageOf(err, "Couldn't load credit packs."));
      }
    },
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const buy = async (packId: string) => {
    setBuying(packId);
    setBuyError("");
    try {
      const checkout = await startWebCreditPackCheckout(packId, { token });
      await openCheckoutUrl(checkout.checkout_url);
    } catch (err) {
      setBuyError(messageOf(err, "Checkout could not be opened."));
    } finally {
      setBuying(null);
    }
  };

  const packs = catalog?.packs ?? [];
  const inputs = packs.map((pack) => ({ price: pack.price_usd, credits: pack.credits, currencyCode: "USD" }));
  const best = lowestPerReelIndex(inputs);

  return (
    <View style={styles.card}>
      <Text style={styles.title}>Credit packs: what one reel costs</Text>
      <Text style={styles.body}>
        One credit makes one finished 9:16 reel with the script, voiceover, presenter, captions and
        render included. Reel length doesn&apos;t change the price.
      </Text>
      <View style={styles.row}>
        <Icon name="shield-checkmark-outline" size={16} color={colors.success} />
        <Text style={[styles.body, styles.flex]}>{PACK_TRUST_NOTE}</Text>
      </View>

      {!catalog && !error ? <ActivityIndicator color={colors.accent} /> : null}
      {error ? (
        <View style={styles.row}>
          <Text style={[styles.error, styles.flex]}>{error}</Text>
          <Pressable onPress={() => void load()} accessibilityRole="button" hitSlop={8}>
            <Text style={styles.link}>Retry</Text>
          </Pressable>
        </View>
      ) : null}
      {catalog && packs.length === 0 ? (
        <Text style={styles.body}>No credit packs are on sale right now.</Text>
      ) : null}

      {packs.map((pack, index) => {
        const perReel = perReelLabel(inputs[index] ?? { price: 0, credits: 0, currencyCode: "USD" });
        const canBuy = catalog?.checkout_open === true && pack.web_checkout_available;
        return (
          <View key={pack.id} style={[styles.pack, index === best && styles.packBest]}>
            <View style={styles.flex}>
              <Text style={styles.packTitle}>{pack.label || `${pack.credits} credits`}</Text>
              <Text style={styles.body}>
                ${pack.price_usd.toFixed(2)} · {reelsLabel(pack.credits)}
              </Text>
              {perReel ? (
                <View style={styles.row}>
                  <View style={styles.chip}>
                    <Text style={styles.chipText}>{perReel}</Text>
                  </View>
                  {index === best ? <Text style={styles.best}>Lowest per reel</Text> : null}
                </View>
              ) : null}
            </View>
            {canBuy ? (
              <Pressable
                style={[styles.buy, buying !== null && styles.disabled]}
                onPress={() => void buy(pack.id)}
                disabled={buying !== null}
                accessibilityRole="button"
                accessibilityLabel={`Buy ${pack.credits} credits for $${pack.price_usd.toFixed(2)}`}
              >
                {buying === pack.id ? (
                  <ActivityIndicator color={colors.onAccent} size="small" />
                ) : (
                  <Text style={styles.buyText}>Buy</Text>
                )}
              </Pressable>
            ) : null}
          </View>
        );
      })}
      {catalog && !catalog.checkout_open && packs.length > 0 ? (
        <Text style={styles.body}>Checkout is not open yet. Your current balance keeps working.</Text>
      ) : null}
      {buyError ? <Text style={styles.error}>{buyError}</Text> : null}
      <Text style={styles.micro}>
        List prices in USD. Checkout shows the final price, including any tax, before you pay.
      </Text>
      <Pressable onPress={() => router.push(CREATOR_CONTRACT_ROUTE)} accessibilityRole="link" hitSlop={8}>
        <Text style={styles.link}>Read the Creator Contract</Text>
      </Pressable>
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
  title: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700" },
  body: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  micro: { color: colors.textFaint, fontSize: typeScale.micro, lineHeight: 16 },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  flex: { flex: 1 },
  pack: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  packBest: { borderColor: colors.accent },
  packTitle: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700" },
  chip: {
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.accent,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    marginTop: spacing.xs,
  },
  chipText: { color: colors.accent, fontSize: typeScale.micro, fontWeight: "700" },
  best: { color: colors.textPrimary, fontSize: typeScale.micro, fontWeight: "700", marginTop: spacing.xs },
  buy: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    minWidth: 64,
    alignItems: "center",
  },
  buyText: { color: colors.onAccent, fontSize: typeScale.body, fontWeight: "700" },
  disabled: { opacity: 0.6 },
  error: { color: colors.danger, fontSize: typeScale.caption },
  link: { color: colors.accent, fontSize: typeScale.caption, fontWeight: "700" },
});
