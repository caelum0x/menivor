/**
 * Shared credit pool panel for a single workspace. Shows the pool balance (GET
 * /workspaces/{id}/credits, any member may read) and — for owners/admins — a
 * grant form (POST /workspaces/{id}/credits/grant) to top the pool up. The
 * balance re-syncs from the server after a successful grant.
 *
 * This is the team-plan counterpart to a personal credit balance: members can
 * charge job creation to this pool from the Create screen. Auth flows through
 * the shared api client as `x-api-key`; this panel owns its own loading + error
 * state.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { getWorkspaceCredits, grantWorkspaceCredits } from "@/lib/api";
import type { WorkspaceCredits } from "@/lib/types";

import { describeError } from "@/components/me/errors";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

interface WorkspaceCreditsSectionProps {
  workspaceId: string;
  token: string | undefined;
  /** When true, render the owner/admin grant form (spending only needs membership). */
  canGrant: boolean;
}

/** Parses the grant amount into a positive integer, or returns an error message. */
function parseAmount(raw: string): { amount: number } | { error: string } {
  const trimmed = raw.trim();
  if (!trimmed) return { error: "Enter an amount to grant." };
  const value = Number(trimmed);
  if (!Number.isFinite(value) || !Number.isInteger(value)) {
    return { error: "Amount must be a whole number." };
  }
  if (value <= 0) return { error: "Amount must be greater than zero." };
  return { amount: value };
}

export function WorkspaceCreditsSection({
  workspaceId,
  token,
  canGrant,
}: WorkspaceCreditsSectionProps) {
  const fetcher = useCallback(
    () => getWorkspaceCredits(workspaceId, { token }),
    [workspaceId, token],
  );
  const { status, data, error, reload, setData } =
    useResource<WorkspaceCredits>(fetcher);

  const [amount, setAmount] = useState("");
  const [granting, setGranting] = useState(false);
  const [grantError, setGrantError] = useState<string | null>(null);

  const onGrant = useCallback(async () => {
    const parsed = parseAmount(amount);
    if ("error" in parsed) {
      setGrantError(parsed.error);
      return;
    }
    setGranting(true);
    setGrantError(null);
    try {
      const updated = await grantWorkspaceCredits(
        workspaceId,
        { amount: parsed.amount },
        { token },
      );
      setData(() => updated);
      setAmount("");
    } catch (err) {
      setGrantError(describeError(err, "Couldn't grant credits."));
    } finally {
      setGranting(false);
    }
  }, [amount, workspaceId, token, setData]);

  const canSubmit = !!amount.trim() && !granting;

  return (
    <Section title="SHARED CREDITS">
      <SectionState status={status} error={error} onRetry={reload}>
        <View style={styles.stack}>
          <View style={styles.balanceCard}>
            <Text style={styles.balanceValue}>{data?.balance ?? 0}</Text>
            <Text style={styles.balanceLabel}>
              credits in the shared pool
            </Text>
          </View>

          {canGrant ? (
            <View style={styles.grantCard}>
              <Text style={styles.label}>Grant credits</Text>
              <View style={styles.grantRow}>
                <TextInput
                  style={styles.input}
                  value={amount}
                  onChangeText={(text) => {
                    setAmount(text);
                    if (grantError) setGrantError(null);
                  }}
                  placeholder="e.g. 50"
                  placeholderTextColor={colors.muted}
                  keyboardType="number-pad"
                  editable={!granting}
                />
                <Pressable
                  style={[styles.button, !canSubmit && styles.buttonDisabled]}
                  onPress={() => void onGrant()}
                  disabled={!canSubmit}
                  accessibilityRole="button"
                  accessibilityLabel="Grant credits to the shared pool"
                  accessibilityState={{ disabled: !canSubmit }}
                >
                  {granting ? (
                    <ActivityIndicator color={colors.textPrimary} />
                  ) : (
                    <Text style={styles.buttonText}>Grant</Text>
                  )}
                </Pressable>
              </View>
              {grantError ? (
                <Text style={styles.error}>{grantError}</Text>
              ) : null}
            </View>
          ) : (
            <Text style={styles.hint}>
              Members can charge new reels to this pool. Only owners and admins
              can add credits.
            </Text>
          )}
        </View>
      </SectionState>
    </Section>
  );
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  balanceCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    alignItems: "center",
    gap: 4,
  },
  balanceValue: { color: colors.accent, fontSize: 32, fontWeight: "800" },
  balanceLabel: { color: colors.muted, fontSize: 13 },
  grantCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 10,
  },
  label: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  grantRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  input: {
    flex: 1,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    paddingHorizontal: 20,
    alignItems: "center",
    justifyContent: "center",
    minWidth: 88,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.textPrimary, fontWeight: "700", fontSize: 15 },
  error: { color: colors.error, fontSize: 13 },
  hint: { color: colors.muted, fontSize: 13, lineHeight: 18 },
});
