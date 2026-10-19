/**
 * REFERRAL PROGRAM — the caller's referral code, native Share + copy, lifetime
 * reward stats (GET /me/referral) and a redeem form (POST /me/referral/redeem).
 * Caller-scoped via the session `x-api-key`. Pull-to-refresh re-reads the code
 * and stats; redeeming a code reloads them so freshly granted credits show up.
 *
 * Nav manifest entry: { route: "/insights/referral", title: "Referral Program" }
 */

import { useCallback, useEffect, useState } from "react";
import type { ReactElement } from "react";
import {
  ActivityIndicator,
  Clipboard,
  Pressable,
  RefreshControl,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack } from "expo-router";

import { getReferral, isAbortError } from "@/lib/api";
import type { Referral } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

import { RedeemForm } from "@/components/me/RedeemForm";
import { StatCard } from "@/components/me/StatCard";
import { describeError } from "@/components/me/errors";
import { formatCount } from "@/components/me/format";
import { colors } from "@/components/me/theme";

type LoadStatus = "loading" | "ready" | "error";

const HOW_IT_WORKS: readonly string[] = [
  "Share your personal code with a friend.",
  "They enter it when they sign up to Menivor.",
  "You both get bonus render credits once they redeem.",
];

export default function ReferralScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [status, setStatus] = useState<LoadStatus>("loading");
  const [referral, setReferral] = useState<Referral | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    async (signal: AbortSignal, isRefresh: boolean): Promise<void> => {
      if (!isRefresh) setStatus("loading");
      setError("");
      try {
        const result = await getReferral({ token, signal });
        if (signal.aborted) return;
        setReferral(result);
        setStatus("ready");
      } catch (err: unknown) {
        if (signal.aborted || isAbortError(err)) return;
        setError(describeError(err, "Failed to load your referral program."));
        setStatus("error");
      } finally {
        if (!signal.aborted) setRefreshing(false);
      }
    },
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal, false);
    return () => controller.abort();
  }, [load]);

  const onRefresh = useCallback((): void => {
    setRefreshing(true);
    const controller = new AbortController();
    void load(controller.signal, true);
  }, [load]);

  const onRedeemed = useCallback((): void => {
    const controller = new AbortController();
    void load(controller.signal, true);
  }, [load]);

  return (
    <>
      <Stack.Screen options={{ title: "Referral Program", presentation: "card" }} />
      <ScrollView
        style={styles.container}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.accent}
          />
        }
      >
        {status === "loading" ? (
          <View style={styles.center}>
            <ActivityIndicator color={colors.accent} size="large" />
          </View>
        ) : status === "error" ? (
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>{error}</Text>
            <Pressable style={styles.retry} onPress={onRefresh}>
              <Text style={styles.retryText}>Try again</Text>
            </Pressable>
          </View>
        ) : referral ? (
          <View style={styles.stack}>
            <ReferralCard referral={referral} />

            <View style={styles.statsRow}>
              <StatCard
                label="Friends referred"
                value={formatCount(referral.referred_count)}
                accent={colors.success}
              />
              <StatCard
                label="Credits earned"
                value={formatCount(referral.credits_earned)}
                accent={colors.primary}
              />
            </View>

            <View style={styles.howCard}>
              <Text style={styles.howTitle}>How it works</Text>
              {HOW_IT_WORKS.map((step, index) => (
                <View key={step} style={styles.stepRow}>
                  <View style={styles.stepNumber}>
                    <Text style={styles.stepNumberText}>{index + 1}</Text>
                  </View>
                  <Text style={styles.stepText}>{step}</Text>
                </View>
              ))}
            </View>

            <RedeemForm token={token} onRedeemed={onRedeemed} />
          </View>
        ) : null}

        <View style={styles.spacer} />
      </ScrollView>
    </>
  );
}

function ReferralCard({ referral }: { referral: Referral }): ReactElement {
  const [copied, setCopied] = useState(false);

  const onShare = useCallback(async (): Promise<void> => {
    try {
      await Share.share({
        message: `Join me on Menivor and we both get bonus render credits. Use my code: ${referral.code}`,
      });
    } catch {
      // User dismissed the share sheet or it is unavailable; nothing to do.
    }
  }, [referral.code]);

  const onCopy = useCallback((): void => {
    Clipboard.setString(referral.code);
    setCopied(true);
  }, [referral.code]);

  return (
    <View style={styles.card}>
      <Text style={styles.heading}>Invite friends, earn credits</Text>
      <Text style={styles.sub}>
        Share your code below. When a friend signs up and redeems it, you both
        get bonus render credits.
      </Text>

      <Text style={styles.codeLabel}>Your referral code</Text>
      <View style={styles.codeRow}>
        <Text style={styles.code} selectable numberOfLines={1}>
          {referral.code}
        </Text>
        <Pressable style={styles.copyBtn} onPress={onCopy} hitSlop={8}>
          <Text style={styles.copyText}>{copied ? "Copied" : "Copy"}</Text>
        </Pressable>
      </View>

      <Pressable style={styles.shareBtn} onPress={onShare}>
        <Text style={styles.shareText}>Share invite</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20 },
  stack: { gap: 16 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  heading: { color: colors.textPrimary, fontSize: 18, fontWeight: "800" },
  sub: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  codeLabel: {
    color: colors.textSecondary,
    fontSize: 12,
    fontWeight: "600",
    marginTop: 10,
  },
  codeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 12,
  },
  code: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: 20,
    fontWeight: "800",
    letterSpacing: 2,
  },
  copyBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  copyText: { color: colors.textSecondary, fontWeight: "700", fontSize: 13 },
  shareBtn: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: "center",
    marginTop: 12,
  },
  shareText: { color: colors.bg, fontWeight: "800", fontSize: 15 },
  statsRow: { flexDirection: "row", gap: 12 },
  howCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
  },
  howTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  stepRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  stepNumber: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.cardAlt,
    borderColor: colors.primary,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  stepNumberText: { color: colors.accent, fontWeight: "800", fontSize: 13 },
  stepText: { flex: 1, color: colors.textSecondary, fontSize: 14, lineHeight: 19 },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 80 },
  errorBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
    alignItems: "flex-start",
  },
  errorText: { color: colors.error, fontSize: 14 },
  retry: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  retryText: { color: colors.textSecondary, fontWeight: "600" },
  spacer: { height: 40 },
});
