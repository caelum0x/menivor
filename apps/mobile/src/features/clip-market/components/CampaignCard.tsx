/**
 * CampaignCard — one campaign row on the Marketplace: title, CPM, live spend vs
 * budget, and the moderation / submit actions. Purely presentational: it renders
 * server data and raises callbacks; all network work lives in the screen.
 */

import * as React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import {
  formatUsdMicros,
  type Campaign,
  type CampaignStatus,
} from "@/lib/clipmarket";

import { statusActions } from "../logic";

export interface CampaignCardProps {
  campaign: Campaign;
  busy?: boolean;
  onSetStatus: (campaign: Campaign, status: CampaignStatus) => void;
  onSubmitClip: (campaign: Campaign) => void;
}

export function CampaignCard({
  campaign,
  busy = false,
  onSetStatus,
  onSubmitClip,
}: CampaignCardProps) {
  const actions = statusActions(campaign.status);

  return (
    <View style={styles.card} testID={`campaign-${campaign.id}`}>
      <View style={styles.headerRow}>
        <Text style={styles.name} numberOfLines={1}>
          {campaign.title || "Untitled campaign"}
        </Text>
        <View style={styles.statusPill}>
          <Text style={styles.statusText}>{campaign.status}</Text>
        </View>
      </View>

      <Text style={styles.meta}>{formatUsdMicros(campaign.cpm_micros)} CPM</Text>
      <Text style={styles.spend}>
        {formatUsdMicros(campaign.spent_micros)} /{" "}
        {formatUsdMicros(campaign.budget_micros)} spent
      </Text>

      <View style={styles.actions}>
        <Pressable
          style={[styles.action, styles.submit, busy && styles.disabled]}
          onPress={() => onSubmitClip(campaign)}
          disabled={busy}
          accessibilityRole="button"
          testID={`submit-${campaign.id}`}
        >
          <Text style={styles.submitText}>Submit clip</Text>
        </Pressable>

        {actions.map((a) => (
          <Pressable
            key={a.status}
            style={[styles.action, styles.moderate, busy && styles.disabled]}
            onPress={() => onSetStatus(campaign, a.status)}
            disabled={busy}
            accessibilityRole="button"
            testID={`status-${a.status}-${campaign.id}`}
          >
            <Text style={styles.moderateText}>{a.label}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 6,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  name: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "700",
    flexShrink: 1,
  },
  statusPill: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  statusText: { color: colors.textSecondary, fontSize: 11, fontWeight: "700" },
  meta: { color: colors.textSecondary, fontSize: 13 },
  spend: { color: colors.muted, fontSize: 12 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 },
  action: {
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  submit: { backgroundColor: colors.primary },
  submitText: { color: colors.bg, fontSize: 13, fontWeight: "700" },
  moderate: {
    borderColor: colors.border,
    borderWidth: 1,
    backgroundColor: colors.cardAlt,
  },
  moderateText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  disabled: { opacity: 0.5 },
});
