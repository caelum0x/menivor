/**
 * Read-only, APPEND-ONLY audit trail for a workspace (GET /me/workspaces/{id}/
 * audit). Only rendered for callers who hold `audit.read` (admin/owner); the
 * backend independently gates the endpoint (403 otherwise) and scopes every row
 * to the tenant, so this view can never surface another workspace's events.
 *
 * Owns its own loading / error state. There is deliberately no create / edit /
 * delete affordance — the trail is tamper-evident by construction.
 */

import { useCallback } from "react";
import { StyleSheet, Text, View } from "react-native";

import { listAuditLog } from "@/lib/api";
import { DEFAULT_AUDIT_LIMIT, type AuditEntry } from "@/lib/types";

import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

interface AuditViewProps {
  workspaceId: string;
  token: string | undefined;
}

/** Best-effort local rendering of an ISO timestamp; blank when absent/unparseable. */
function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

/** A short human summary of an audit row's effect (safe with partial metadata). */
function summarize(entry: AuditEntry): string {
  const meta = entry.metadata ?? {};
  if (
    entry.action === "members.role_changed" &&
    (meta.old_role != null || meta.new_role != null)
  ) {
    return `${String(meta.old_role ?? "?")} → ${String(meta.new_role ?? "?")}`;
  }
  const parts: string[] = [];
  if (entry.target_type) parts.push(String(entry.target_type));
  if (entry.target_id) parts.push(String(entry.target_id));
  return parts.join(" · ");
}

export function AuditView({ workspaceId, token }: AuditViewProps) {
  const fetcher = useCallback(
    () => listAuditLog(workspaceId, { limit: DEFAULT_AUDIT_LIMIT }, { token }),
    [workspaceId, token],
  );
  const { status, data, error, reload } = useResource<AuditEntry[]>(fetcher);
  const entries = data ?? [];

  return (
    <Section title="AUDIT TRAIL">
      <SectionState status={status} error={error} onRetry={reload}>
        {entries.length === 0 ? (
          <Text style={styles.empty}>No audit events yet.</Text>
        ) : (
          <View style={styles.list}>
            {entries.map((entry) => {
              const detail = summarize(entry);
              const when = formatWhen(entry.created_at);
              return (
                <View key={entry.id} style={styles.row}>
                  <View style={styles.headerRow}>
                    <Text style={styles.action} numberOfLines={1}>
                      {entry.action}
                    </Text>
                    {when ? <Text style={styles.when}>{when}</Text> : null}
                  </View>
                  {detail ? <Text style={styles.detail}>{detail}</Text> : null}
                  <Text style={styles.actor} numberOfLines={1}>
                    by {entry.actor_user_id}
                  </Text>
                </View>
              );
            })}
          </View>
        )}
      </SectionState>
    </Section>
  );
}

const styles = StyleSheet.create({
  list: { gap: 10 },
  row: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 4,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  action: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: "700",
    flexShrink: 1,
  },
  when: { color: colors.muted, fontSize: 11 },
  detail: { color: colors.textSecondary, fontSize: 13 },
  actor: { color: colors.muted, fontSize: 11 },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
});
