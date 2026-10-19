/**
 * Menivor Pro sheet: Menivor's own subscription screen. Every price shown is
 * the store's localised `priceString` from the current RevenueCat offering;
 * nothing is priced or discounted in the app. Restore and the auto-renew terms
 * are always visible (App Store 3.1.2).
 */
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Icon, type IconName } from "@/components/ui/Icon";
import { SubscriptionDisclosure } from "@/src/shared/legal";
import { palette } from "@/src/shared/theme/tokens";
import { ReelArt, frameDepth, goldPressDepth } from "@/src/ui/menivor";

import {
  StorePurchaseCancelledError,
  getProPackages,
  purchaseProPackage,
  type ProPackageOption,
} from "./revenuecat-adapter";

export interface MenivorProSheetProps {
  readonly visible: boolean;
  /** Called after a purchase or restore completes, and on close. */
  readonly onClose: () => void;
  readonly onPurchased: () => void;
  readonly onRestore: () => Promise<{ status: string }>;
}

const BENEFITS: readonly { icon: IconName; text: string }[] = [
  { icon: "download-outline", text: "Export and save every finished reel" },
  { icon: "cut-outline", text: "Timeline edits and trims exported as new reels" },
  { icon: "share-outline", text: "Share straight from a reel to any app on your phone" },
];

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; packages: ProPackageOption[] }
  | { kind: "error"; message: string };

export function MenivorProSheet({ visible, onClose, onPurchased, onRestore }: MenivorProSheetProps) {
  const insets = useSafeAreaInsets();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<"buy" | "restore" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    setMessage(null);
    try {
      const packages = await getProPackages();
      setState({ kind: "ready", packages });
      setSelected((current) => current ?? packages[0]?.identifier ?? null);
    } catch (error) {
      setState({
        kind: "error",
        message: error instanceof Error ? error.message : "Plans could not be loaded.",
      });
    }
  }, []);

  useEffect(() => {
    if (visible) void load();
  }, [load, visible]);

  const buy = async () => {
    if (!selected) return;
    setBusy("buy");
    setMessage(null);
    try {
      await purchaseProPackage(selected);
      onPurchased();
    } catch (error) {
      if (!(error instanceof StorePurchaseCancelledError)) {
        setMessage(error instanceof Error ? error.message : "The purchase did not complete.");
      }
    } finally {
      setBusy(null);
    }
  };

  const restore = async () => {
    setBusy("restore");
    setMessage(null);
    try {
      const restored = await onRestore();
      if (restored.status === "active") onPurchased();
      else setMessage("No Menivor Pro subscription was found for this store account.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nothing to restore for this account.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={[styles.root, { paddingBottom: insets.bottom + 12 }]}>
        <View style={styles.header}>
          <Pressable
            onPress={onClose}
            hitSlop={12}
            style={styles.close}
            accessibilityRole="button"
            accessibilityLabel="Close"
          >
            <Icon name="close" size={22} color={palette.paper} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.content}>
          <View style={styles.strip} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            {["Travel", "Cooking", "Fitness"].map((niche, i) => (
              <ReelArt
                key={niche}
                seed={niche}
                niche={niche}
                showText={false}
                style={[styles.stripTile, i === 1 && styles.stripTileCenter]}
              />
            ))}
          </View>
          <Text style={styles.kicker}>MENIVOR PRO</Text>
          <Text style={styles.title} accessibilityRole="header">
            Keep every reel you make.
          </Text>
          <View style={styles.benefits}>
            {BENEFITS.map((benefit) => (
              <View key={benefit.text} style={styles.benefit}>
                <Icon name={benefit.icon} size={18} color={palette.accent} />
                <Text style={styles.benefitText}>{benefit.text}</Text>
              </View>
            ))}
          </View>

          {state.kind === "loading" ? (
            <ActivityIndicator color={palette.accent} style={styles.loading} />
          ) : state.kind === "error" ? (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{state.message}</Text>
              <Pressable onPress={() => void load()} accessibilityRole="button">
                <Text style={styles.link}>Try again</Text>
              </Pressable>
            </View>
          ) : state.packages.length === 0 ? (
            <Text style={styles.errorText}>
              Pro plans are not available in your store right now. Please try again later.
            </Text>
          ) : (
            <View style={styles.plans} accessibilityRole="radiogroup">
              {state.packages.map((pkg) => {
                const on = pkg.identifier === selected;
                return (
                  <Pressable
                    key={pkg.identifier}
                    onPress={() => setSelected(pkg.identifier)}
                    style={[styles.plan, on && styles.planOn, { boxShadow: frameDepth }]}
                    accessibilityRole="radio"
                    accessibilityState={{ selected: on }}
                    accessibilityLabel={`${pkg.priceString}${pkg.period ? ` per ${pkg.period}` : ""}`}
                  >
                    <View style={[styles.radio, on && styles.radioOn]} />
                    <Text style={styles.planPeriod}>
                      {pkg.period ? `Every ${pkg.period}` : pkg.title}
                    </Text>
                    <Text style={styles.planPrice}>{pkg.priceString}</Text>
                  </Pressable>
                );
              })}
            </View>
          )}

          {message ? <Text style={styles.errorText}>{message}</Text> : null}

          <SubscriptionDisclosure textColor={palette.paperFaint} linkTint={palette.accent} />
        </ScrollView>

        <View style={styles.footer}>
          <Pressable
            onPress={() => void buy()}
            disabled={!selected || busy !== null || state.kind !== "ready"}
            style={({ pressed }) => [
              styles.cta,
              { boxShadow: goldPressDepth(pressed) },
              (!selected || state.kind !== "ready") && styles.dim,
            ]}
            accessibilityRole="button"
          >
            {busy === "buy" ? (
              <ActivityIndicator color={palette.accentInk} />
            ) : (
              <Text style={styles.ctaText}>Continue</Text>
            )}
          </Pressable>
          <Pressable onPress={() => void restore()} disabled={busy !== null} accessibilityRole="button" hitSlop={8}>
            {busy === "restore" ? (
              <ActivityIndicator color={palette.paperMuted} />
            ) : (
              <Text style={styles.link}>Restore purchases</Text>
            )}
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: palette.ink },
  header: { flexDirection: "row", justifyContent: "flex-end", paddingHorizontal: 16, paddingTop: 14 },
  close: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: palette.surfaceAlt,
  },
  content: { paddingHorizontal: 22, paddingBottom: 24, gap: 14 },
  strip: { flexDirection: "row", justifyContent: "center", gap: 10, marginBottom: 6 },
  stripTile: { width: 78, height: 138, borderRadius: 14, marginTop: 14, opacity: 0.85 },
  stripTileCenter: { marginTop: 0, opacity: 1 },
  kicker: { color: palette.paperMuted, fontSize: 11, fontWeight: "700", letterSpacing: 2.4, textAlign: "center" },
  title: { color: palette.paper, fontSize: 30, fontWeight: "800", letterSpacing: -1, textAlign: "center" },
  benefits: { gap: 10, marginVertical: 6 },
  benefit: { flexDirection: "row", alignItems: "center", gap: 12 },
  benefitText: { color: palette.paper, fontSize: 15, flex: 1, lineHeight: 21 },
  loading: { marginVertical: 24 },
  plans: { gap: 10 },
  plan: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 16,
    borderRadius: 18,
    backgroundColor: palette.surface,
    borderWidth: 1,
    borderColor: palette.border,
  },
  planOn: { borderColor: palette.accent },
  radio: { width: 18, height: 18, borderRadius: 9, borderWidth: 2, borderColor: palette.paperFaint },
  radioOn: { borderColor: palette.accent, backgroundColor: palette.accent },
  planPeriod: { color: palette.paper, fontSize: 15, fontWeight: "700", flex: 1, textTransform: "capitalize" },
  planPrice: { color: palette.paper, fontSize: 17, fontWeight: "800" },
  errorBox: { gap: 8, alignItems: "center" },
  errorText: { color: palette.paperMuted, fontSize: 14, lineHeight: 20, textAlign: "center" },
  footer: { paddingHorizontal: 22, gap: 12, alignItems: "center" },
  cta: {
    alignSelf: "stretch",
    minHeight: 54,
    borderRadius: 16,
    backgroundColor: palette.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  ctaText: { color: palette.accentInk, fontSize: 17, fontWeight: "800" },
  dim: { opacity: 0.5 },
  link: { color: palette.paperMuted, fontSize: 14, fontWeight: "600", textDecorationLine: "underline" },
});
