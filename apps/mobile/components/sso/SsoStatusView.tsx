/**
 * The ENTERPRISE Identity & SSO status view for a single workspace (Epic 2).
 *
 * READ-MOSTLY: it surfaces whether SSO is configured + enabled and summarises the
 * workspace's login security policy. The one mutation offered on mobile is the
 * owner/admin enable toggle; there is NO certificate entry on mobile (the IdP
 * signing cert / OIDC secret are configured from the web admin and are never
 * returned by the API).
 *
 * Every decision here is a UI affordance only — the backend gates all of these on
 * the `workspace.settings` permission and scopes each read/write to THIS
 * workspace (tenant isolation). The connection/policy reads themselves 403 for a
 * non-admin, so we gate the whole surface on the caller's effective permissions
 * first to render a clear message instead of an error.
 *
 * SAFETY NOTE (enable toggle): the backend `PUT /me/workspaces/{id}/sso` is a full
 * upsert — re-saving without the write-only cert/secret would clear it. Because
 * mobile can't re-supply a cert, toggling a connection that has a stored secret is
 * gated behind an explicit confirmation that spells out the consequence.
 */

import { useCallback, useState } from "react";
import { Alert, Pressable, StyleSheet, Switch, Text, View } from "react-native";
import { Icon } from "@/components/ui/Icon";

import { getMyPermissions } from "@/lib/api";
import {
  getSecurityPolicy,
  getSsoConnection,
  putSsoConnection,
  type SecurityPolicy,
  type SsoConnection,
} from "@/lib/sso";
import type { Permissions, Workspace } from "@/lib/types";

import { describeError } from "@/components/me/errors";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

interface SsoStatusViewProps {
  workspace: Workspace;
  token: string | undefined;
  onBack: () => void;
}

export function SsoStatusView({ workspace, token, onBack }: SsoStatusViewProps) {
  const permsFetcher = useCallback(
    () => getMyPermissions(workspace.id, { token }),
    [workspace.id, token],
  );
  const { status, data: perms, error, reload } =
    useResource<Permissions>(permsFetcher);

  const canManage = !!perms?.permissions.includes("workspace.settings");

  return (
    <View style={styles.container}>
      <Pressable
        style={styles.back}
        onPress={onBack}
        accessibilityRole="button"
        accessibilityLabel="Back to workspaces"
        hitSlop={6}
      >
        <Icon name="chevron-back" style={styles.backText} />
        <Text style={styles.backText}>Workspaces</Text>
      </Pressable>

      <Text style={styles.title}>{workspace.name}</Text>

      <Section title="ENTERPRISE SSO">
        <SectionState status={status} error={error} onRetry={reload}>
          {canManage ? (
            <SsoSettings workspaceId={workspace.id} token={token} />
          ) : (
            <Text style={styles.empty}>
              Enterprise SSO is managed by workspace owners and admins. You don't
              have access to SSO settings for this workspace.
            </Text>
          )}
        </SectionState>
      </Section>
    </View>
  );
}

// ---------------------------------------------------------------------------
// The admin-only body: connection status + enable toggle, then the policy summary.
// Rendered only once we know the caller holds `workspace.settings`, so the reads
// below never 403.
// ---------------------------------------------------------------------------

interface SsoSettingsProps {
  workspaceId: string;
  token: string | undefined;
}

function SsoSettings({ workspaceId, token }: SsoSettingsProps) {
  const connFetcher = useCallback(
    () => getSsoConnection(workspaceId, { token }),
    [workspaceId, token],
  );
  const {
    status: connStatus,
    data: connection,
    error: connError,
    reload: reloadConn,
    setData: setConnection,
  } = useResource<SsoConnection | null>(connFetcher);

  const policyFetcher = useCallback(
    () => getSecurityPolicy(workspaceId, { token }),
    [workspaceId, token],
  );
  const {
    status: policyStatus,
    data: policy,
    error: policyError,
    reload: reloadPolicy,
  } = useResource<SecurityPolicy | null>(policyFetcher);

  const [busy, setBusy] = useState(false);

  const doToggle = useCallback(
    async (conn: SsoConnection, next: boolean) => {
      setBusy(true);
      const previous = conn;
      // Optimistically flip, then confirm with the backend.
      setConnection(() => ({ ...conn, enabled: next }));
      try {
        // Re-send only the existing NON-SECRET fields — the write-only cert /
        // secret are never available on mobile (see the file header's safety note).
        const updated = await putSsoConnection(
          workspaceId,
          {
            protocol: conn.protocol,
            idp_entity_id: conn.idp_entity_id,
            idp_sso_url: conn.idp_sso_url,
            sp_acs_url: conn.sp_acs_url,
            oidc_client_id: conn.oidc_client_id ?? "",
            enabled: next,
          },
          { token },
        );
        setConnection(() => updated);
      } catch (err) {
        setConnection(() => previous);
        Alert.alert("Couldn't update SSO", describeError(err));
      } finally {
        setBusy(false);
      }
    },
    [workspaceId, token, setConnection],
  );

  const onToggle = useCallback(
    (next: boolean) => {
      if (!connection || busy) return;
      if (connection.has_certificate || connection.has_client_secret) {
        Alert.alert(
          next ? "Enable SSO?" : "Disable SSO?",
          "Changing this from the app re-saves the connection without the stored " +
            "IdP certificate/secret, which can't be entered on mobile. You'll need " +
            "to re-upload it from the web admin afterwards. Continue?",
          [
            { text: "Cancel", style: "cancel" },
            {
              text: next ? "Enable" : "Disable",
              style: "destructive",
              onPress: () => void doToggle(connection, next),
            },
          ],
        );
      } else {
        void doToggle(connection, next);
      }
    },
    [connection, busy, doToggle],
  );

  return (
    <View style={styles.body}>
      <SectionState
        status={connStatus}
        error={connError}
        onRetry={reloadConn}
      >
        {connection ? (
          <View style={styles.card}>
            <View style={styles.row}>
              <Text style={styles.rowLabel}>SSO enabled</Text>
              <Switch
                value={connection.enabled}
                onValueChange={onToggle}
                disabled={busy}
                trackColor={{ false: colors.border, true: colors.primary }}
                thumbColor={colors.textPrimary}
              />
            </View>
            <View style={styles.divider} />
            <StatusRow
              label="Protocol"
              value={connection.protocol.toUpperCase()}
            />
            <StatusRow
              label="Signing certificate"
              value={connection.has_certificate ? "Configured" : "Not set"}
            />
            {connection.protocol === "oidc" ? (
              <StatusRow
                label="Client secret"
                value={connection.has_client_secret ? "Configured" : "Not set"}
              />
            ) : null}
            {connection.idp_entity_id ? (
              <StatusRow label="IdP entity" value={connection.idp_entity_id} />
            ) : null}
            <Text style={styles.hint}>
              Certificates and secrets are configured from the web admin — they're
              never entered or shown on mobile.
            </Text>
          </View>
        ) : (
          <Text style={styles.empty}>
            SSO isn't configured for this workspace yet. Set up your identity
            provider from the web admin to enable single sign-on.
          </Text>
        )}
      </SectionState>

      <View style={styles.policyHeader}>
        <Text style={styles.policyHeaderText}>SECURITY POLICY</Text>
      </View>
      <SectionState
        status={policyStatus}
        error={policyError}
        onRetry={reloadPolicy}
      >
        {policy ? (
          <View style={styles.card}>
            <StatusRow
              label="Require SSO"
              value={policy.require_sso ? "On" : "Off"}
            />
            <StatusRow
              label="MFA required"
              value={policy.mfa_required ? "On" : "Off"}
            />
            <StatusRow
              label="Session timeout"
              value={
                policy.session_timeout_min > 0
                  ? `${policy.session_timeout_min} min`
                  : "No limit"
              }
            />
            <ChipRow
              label="Allowed email domains"
              values={policy.allowed_email_domains}
              emptyLabel="Any"
            />
            <ChipRow
              label="IP allowlist"
              values={policy.ip_allowlist}
              emptyLabel="Any"
            />
          </View>
        ) : (
          <Text style={styles.empty}>
            No security policy configured. Defaults apply: no SSO requirement, no
            MFA, no session timeout, and no domain or IP restrictions.
          </Text>
        )}
      </SectionState>
    </View>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

function ChipRow({
  label,
  values,
  emptyLabel,
}: {
  label: string;
  values: readonly string[];
  emptyLabel: string;
}) {
  return (
    <View style={styles.chipRow}>
      <Text style={styles.rowLabel}>{label}</Text>
      {values.length > 0 ? (
        <View style={styles.chips}>
          {values.map((value) => (
            <Text key={value} style={styles.chip}>
              {value}
            </Text>
          ))}
        </View>
      ) : (
        <Text style={styles.rowValue}>{emptyLabel}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 8 },
  back: { alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 2, paddingVertical: 4, marginBottom: 4 },
  backText: { color: colors.accent, fontSize: 14, fontWeight: "600" },
  title: {
    color: colors.textPrimary,
    fontSize: 22,
    fontWeight: "800",
    marginBottom: 12,
  },
  body: { gap: 16 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 12,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  rowLabel: { color: colors.muted, fontSize: 13 },
  rowValue: {
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: "600",
    flexShrink: 1,
    textAlign: "right",
  },
  divider: { height: 1, backgroundColor: colors.border },
  hint: { color: colors.muted, fontSize: 12, lineHeight: 17 },
  policyHeader: { marginTop: 4 },
  policyHeaderText: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
  },
  chipRow: { gap: 8 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    color: colors.textSecondary,
    fontSize: 12,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 6,
    overflow: "hidden",
  },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
});
