/**
 * REFERRAL section of the Me tab. Fetches GET /me/referral, shows the caller's
 * code with a native Share sheet (React Native `Share`), lifetime stats, and a
 * redeem form (POST /me/referral/redeem). Redeeming reloads the stats.
 */

import { useCallback } from "react";
import { Share, StyleSheet, Text, View } from "react-native";

import { getReferral } from "@/lib/api";
import type { Referral } from "@/lib/types";

import { RedeemForm } from "./RedeemForm";
import { Section, SectionState } from "./Section";
import { formatCount } from "./format";
import { colors } from "./theme";
import { useResource } from "./use-resource";

interface ReferralSectionProps {
  token: string | undefined;
}

export function ReferralSection({ token }: ReferralSectionProps) {
  const fetcher = useCallback(() => getReferral({ token }), [token]);
  const { status, data, error, reload } = useResource<Referral>(fetcher);

  return (
    <Section title="REFERRAL">
      <SectionState status={status} error={error} onRetry={reload}>
        {data ? (
          <View style={styles.stack}>
            <ReferralCard referral={data} />
            <RedeemForm token={token} onRedeemed={reload} />
          </View>
        ) : null}
      </SectionState>
    </Section>
  );
}

function ReferralCard({ referral }: { referral: Referral }) {
  const onShare = useCallback(async () => {
    try {
      await Share.share({
        message: `Join me on Menivor and we both get bonus render credits. Use my code: ${referral.code}`,
      });
    } catch {
      // User dismissed the share sheet or it is unavailable; nothing to do.
    }
  }, [referral.code]);

  return (
    <View style={styles.card}>
      <Text style={styles.heading}>Invite friends, earn credits</Text>
      <Text style={styles.sub}>
        Share your code. When a friend signs up and redeems it, you both get
        bonus render credits.
      </Text>

      <Text style={styles.codeLabel}>Your referral code</Text>
      <View style={styles.codeRow}>
        <Text style={styles.code} selectable numberOfLines={1}>
          {referral.code}
        </Text>
        <Text style={styles.shareBtn} onPress={onShare}>
          Share
        </Text>
      </View>

      <View style={styles.statsRow}>
        <Stat label="Friends referred" value={formatCount(referral.referred_count)} />
        <Stat label="Credits earned" value={formatCount(referral.credits_earned)} />
      </View>
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  heading: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  sub: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  codeLabel: { color: colors.textSecondary, fontSize: 12, fontWeight: "600", marginTop: 6 },
  codeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  code: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: "700",
    letterSpacing: 2,
  },
  shareBtn: {
    color: colors.accent,
    fontWeight: "700",
    fontSize: 15,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  statsRow: { flexDirection: "row", gap: 12, marginTop: 8 },
  stat: {
    flex: 1,
    backgroundColor: colors.cardAlt,
    borderRadius: 10,
    padding: 12,
    gap: 2,
  },
  statLabel: { color: colors.muted, fontSize: 12 },
  statValue: { color: colors.textPrimary, fontSize: 20, fontWeight: "700" },
});
