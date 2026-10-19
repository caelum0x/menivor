/**
 * The caller-scoped developer-portal summary card (GET /me/developer): a
 * READ-only footprint of the caller's API keys (counts + this month's request
 * usage), their webhook subscriptions (counts across their workspaces), the number
 * of workspaces they belong to, and the static integration metadata (API base URL,
 * OpenAPI/docs links, version). SECRET-FREE — no key, hash, or signing secret.
 */

import { StyleSheet, Text, View } from "react-native";

import type { DeveloperPortal } from "@/lib/developer";

import { StatCard } from "@/components/me/StatCard";
import { colors } from "@/components/me/theme";

import { count } from "./format";

interface PortalSummaryProps {
  portal: DeveloperPortal;
}

export function PortalSummary({ portal }: PortalSummaryProps) {
  const { api_keys, webhooks } = portal;
  return (
    <View style={styles.container}>
      <View style={styles.grid}>
        <StatCard
          label="API keys"
          value={count(api_keys.total)}
          hint={`${count(api_keys.active)} active`}
          accent={colors.accent}
        />
        <StatCard
          label="Requests this month"
          value={count(api_keys.requests_this_month)}
          hint={api_keys.period_ym || undefined}
        />
        <StatCard
          label="Webhooks"
          value={count(webhooks.total)}
          hint={`${count(webhooks.active)} enabled`}
          accent={colors.accent}
        />
        <StatCard
          label="Workspaces"
          value={count(portal.workspaces)}
          hint="You belong to"
        />
      </View>

      <View style={styles.metaCard}>
        <MetaRow label="API base" value={portal.api_base_url || "—"} mono />
        {portal.api_version ? (
          <MetaRow label="Version" value={portal.api_version} />
        ) : null}
        <MetaRow label="OpenAPI" value={portal.openapi_url || "—"} mono />
        <MetaRow label="Docs" value={portal.docs_url || "—"} mono />
      </View>
    </View>
  );
}

function MetaRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <View style={styles.metaRow}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text
        style={[styles.metaValue, mono && styles.mono]}
        numberOfLines={1}
        selectable
      >
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 12 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  metaCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 10,
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  metaLabel: { color: colors.muted, fontSize: 13 },
  metaValue: {
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: "600",
    flexShrink: 1,
    textAlign: "right",
  },
  mono: { fontFamily: "monospace", fontSize: 12 },
});
