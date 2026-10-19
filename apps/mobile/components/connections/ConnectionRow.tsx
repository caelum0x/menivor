/**
 * A single social-provider row on the Connections screen. Shows the provider,
 * its connection status, and — when connected — the token-free account id,
 * granted scopes and connected date, with Connect / Reconnect / Disconnect
 * affordances. Presentational: the parent owns the network calls.
 *
 * SECURITY: a {@link Connection} never carries an access/refresh token, so this
 * row can only ever render the safe provider / account-id / status / scopes /
 * timestamps.
 */

import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { Connection, SocialProvider } from "@/lib/types";

import { colors } from "@/components/me/theme";

import {
  formatDate,
  isExpired,
  parseScopes,
  providerLabel,
  statusLabel,
} from "./format";

interface ConnectionRowProps {
  provider: SocialProvider | string;
  /** The caller's connection for this provider, or undefined when not linked. */
  connection: Connection | undefined;
  /** True while a connect/disconnect for this provider is in flight. */
  busy: boolean;
  onConnect: (provider: SocialProvider | string) => void;
  onDisconnect: (provider: SocialProvider | string) => void;
}

export function ConnectionRow({
  provider,
  connection,
  busy,
  onConnect,
  onDisconnect,
}: ConnectionRowProps) {
  const label = providerLabel(provider);
  const connected = !!connection;
  const expired = connected && isExpired(connection?.status);
  const scopes = connected ? parseScopes(connection?.scopes) : [];
  const connectedAt = connected ? formatDate(connection?.connected_at) : "";
  const accountId = (connection?.external_account_id ?? "").trim();

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <View style={styles.titleWrap}>
          <Text style={styles.title}>{label}</Text>
          {connected ? (
            <View
              style={[styles.badge, expired ? styles.badgeWarn : styles.badgeOk]}
              accessibilityLabel={statusLabel(connection?.status)}
            >
              <Text
                style={[
                  styles.badgeText,
                  expired ? styles.badgeWarnText : styles.badgeOkText,
                ]}
              >
                {statusLabel(connection?.status)}
              </Text>
            </View>
          ) : (
            <Text style={styles.notConnected}>Not connected</Text>
          )}
        </View>

        {busy ? (
          <ActivityIndicator color={colors.accent} size="small" />
        ) : null}
      </View>

      {connected ? (
        <View style={styles.meta}>
          {accountId ? (
            <Text style={styles.metaLine} numberOfLines={1}>
              Account {accountId}
            </Text>
          ) : null}
          {connectedAt ? (
            <Text style={styles.metaLine} numberOfLines={1}>
              Connected {connectedAt}
            </Text>
          ) : null}
          {scopes.length > 0 ? (
            <Text style={styles.metaLine} numberOfLines={2}>
              Scopes: {scopes.join(", ")}
            </Text>
          ) : null}
        </View>
      ) : (
        <Text style={styles.hint}>
          Connect your {label} account to publish finished reels straight to it.
        </Text>
      )}

      <View style={styles.actions}>
        {connected ? (
          <>
            {expired ? (
              <Pressable
                style={[styles.btn, styles.btnPrimary]}
                onPress={() => onConnect(provider)}
                disabled={busy}
                accessibilityRole="button"
                accessibilityLabel={`Reconnect ${label}`}
                accessibilityState={{ disabled: busy }}
              >
                <Text style={styles.btnPrimaryText}>Reconnect</Text>
              </Pressable>
            ) : null}
            <Pressable
              style={[styles.btn, styles.btnDanger]}
              onPress={() => onDisconnect(provider)}
              disabled={busy}
              accessibilityRole="button"
              accessibilityLabel={`Disconnect ${label}`}
              accessibilityState={{ disabled: busy }}
            >
              <Text style={styles.btnDangerText}>Disconnect</Text>
            </Pressable>
          </>
        ) : (
          <Pressable
            style={[styles.btn, styles.btnPrimary]}
            onPress={() => onConnect(provider)}
            disabled={busy}
            accessibilityRole="button"
            accessibilityLabel={`Connect ${label}`}
            accessibilityState={{ disabled: busy }}
          >
            <Text style={styles.btnPrimaryText}>Connect</Text>
          </Pressable>
        )}
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
    gap: 10,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  titleWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    flexShrink: 1,
  },
  title: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  notConnected: { color: colors.muted, fontSize: 12 },
  badge: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  badgeOk: { backgroundColor: colors.cardAlt, borderColor: colors.success },
  badgeWarn: { backgroundColor: colors.cardAlt, borderColor: colors.error },
  badgeText: { fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },
  badgeOkText: { color: colors.success },
  badgeWarnText: { color: colors.error },
  meta: { gap: 3 },
  metaLine: { color: colors.textSecondary, fontSize: 12 },
  hint: { color: colors.muted, fontSize: 12, lineHeight: 17 },
  actions: { flexDirection: "row", gap: 10 },
  btn: {
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 9,
    borderWidth: 1,
  },
  btnPrimary: { backgroundColor: colors.primary, borderColor: colors.primary },
  btnPrimaryText: { color: colors.textPrimary, fontWeight: "700", fontSize: 14 },
  btnDanger: { backgroundColor: "transparent", borderColor: colors.error },
  btnDangerText: { color: colors.error, fontWeight: "600", fontSize: 14 },
});
