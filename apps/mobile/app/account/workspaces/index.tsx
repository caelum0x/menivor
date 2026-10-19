/**
 * Team & Workspaces hub (canonical; legacy /team and /team-roles redirect into
 * its subroutes).
 *
 * Links to the two management subroutes — /account/workspaces/members
 * (invite, change roles, remove members) and /account/workspaces/roles
 * (effective permissions + audit trail) — and hosts the workspace switcher:
 *
 * Lists the workspaces the caller belongs to, marks + persists the ACTIVE one
 * (used by the account settings + developer screens to scope subscription and
 * webhook reads), shows the active workspace's shared credit pool, and lets an
 * owner/admin create a new workspace or leave one (with confirmation).
 *
 * Every mutation is authorized server-side by the caller's role; the client
 * mirrors `my_role` only to gate affordances. Auth flows through the shared
 * `x-api-key` client via the session token — no secrets live here.
 *
 * NAV MANIFEST (for the integration agent to wire into navigation):
 *   - { route: "/account/workspaces", title: "Workspaces" }
 *   - { route: "/account/settings", title: "Account & Settings" }
 *   - { route: "/account/developer-keys", title: "Developer & API Keys" }
 */

import * as React from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { Stack, useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { Icon } from "@/components/ui/Icon";
import {
  createWorkspace,
  getWorkspaceCredits,
  isAbortError,
  leaveWorkspace,
} from "@/lib/api";
import { useActiveWorkspace } from "@/lib/active-workspace";
import type { Workspace } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

export default function WorkspacesScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const state = useActiveWorkspace(token);

  const [creating, setCreating] = React.useState(false);
  const [name, setName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [actionError, setActionError] = React.useState("");
  const [credits, setCredits] = React.useState<number | null>(null);

  // Load the active workspace's shared credit pool whenever it changes.
  React.useEffect(() => {
    if (!state.active) {
      setCredits(null);
      return;
    }
    const controller = new AbortController();
    setCredits(null);
    getWorkspaceCredits(state.active.id, { token, signal: controller.signal })
      .then((res) => setCredits(res.balance))
      .catch((err: unknown) => {
        if (!isAbortError(err)) setCredits(null);
      });
    return () => controller.abort();
  }, [state.active, token]);

  const onCreate = React.useCallback(async (): Promise<void> => {
    const trimmed = name.trim();
    if (trimmed.length === 0) {
      setActionError("Enter a workspace name.");
      return;
    }
    setBusy(true);
    setActionError("");
    try {
      const created = await createWorkspace({ name: trimmed }, { token });
      setName("");
      setCreating(false);
      await state.select(created.id);
      state.reload();
    } catch (err: unknown) {
      setActionError(
        err instanceof Error ? err.message : "Could not create the workspace.",
      );
    } finally {
      setBusy(false);
    }
  }, [name, token, state]);

  const onLeave = React.useCallback(
    (workspace: Workspace): void => {
      Alert.alert(
        "Leave workspace",
        `Leave "${workspace.name}"? You will lose access to its shared credits and jobs. This cannot be undone from here.`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Leave",
            style: "destructive",
            onPress: () => {
              setActionError("");
              leaveWorkspace(workspace.id, { token })
                .then(() => state.reload())
                .catch((err: unknown) => {
                  setActionError(
                    err instanceof Error
                      ? err.message
                      : "Could not leave the workspace.",
                  );
                });
            },
          },
        ],
      );
    },
    [token, state],
  );

  const refreshing = state.status === "loading" && state.workspaces.length > 0;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={state.reload}
          tintColor={colors.accent}
        />
      }
    >
      <Stack.Screen options={{ title: "Team & Workspaces" }} />

      <Text style={styles.intro}>
        Switch between your teams. The active workspace scopes the subscription,
        shared credits, and webhooks shown across your account.
      </Text>

      <Pressable
        style={styles.hubLink}
        onPress={() => router.push("/account/workspaces/members")}
        accessibilityRole="button"
        accessibilityLabel="Members and invites"
      >
        <View style={styles.flex}>
          <Text style={styles.name}>Members & invites</Text>
          <Text style={styles.meta}>
            Invite teammates by email, change their roles, or remove them
          </Text>
        </View>
        <Icon name="chevron-forward" style={styles.chevron} />
      </Pressable>
      <Pressable
        style={styles.hubLink}
        onPress={() => router.push("/account/workspaces/roles")}
        accessibilityRole="button"
        accessibilityLabel="Roles, permissions and audit trail"
      >
        <View style={styles.flex}>
          <Text style={styles.name}>Roles & audit trail</Text>
          <Text style={styles.meta}>
            See your effective permissions and review every role change
          </Text>
        </View>
        <Icon name="chevron-forward" style={styles.chevron} />
      </Pressable>

      {state.status === "loading" && state.workspaces.length === 0 ? (
        <ActivityIndicator color={colors.accent} style={styles.spacer} />
      ) : state.status === "error" ? (
        <View style={styles.card}>
          <Text style={styles.error}>{state.error}</Text>
          <Pressable style={styles.retryButton} onPress={state.reload}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : state.workspaces.length === 0 ? (
        <View style={styles.card}>
          <Text style={styles.emptyTitle}>No workspaces yet</Text>
          <Text style={styles.meta}>
            Create a workspace to share credits and collaborate with a team.
          </Text>
        </View>
      ) : (
        state.workspaces.map((workspace) => {
          const isActive = workspace.id === state.activeId;
          const canLeave = true;
          return (
            <View
              key={workspace.id}
              style={[styles.card, isActive && styles.cardActive]}
            >
              <View style={styles.rowBetween}>
                <Text style={styles.name} numberOfLines={1}>
                  {workspace.name || "Untitled workspace"}
                </Text>
                {isActive ? (
                  <Text style={styles.activeTag}>Active</Text>
                ) : null}
              </View>
              <Text style={styles.meta}>
                {formatRole(String(workspace.my_role))}
                {typeof workspace.member_count === "number"
                  ? ` · ${workspace.member_count} member${
                      workspace.member_count === 1 ? "" : "s"
                    }`
                  : ""}
              </Text>
              {isActive && credits !== null ? (
                <Text style={styles.credits}>
                  {credits.toLocaleString()} shared credits
                </Text>
              ) : null}

              <View style={styles.actionRow}>
                {isActive ? (
                  <Pressable
                    style={[styles.smallButton, styles.smallButtonPrimary]}
                    onPress={() => router.push("/account/settings")}
                  >
                    <Text style={styles.smallButtonPrimaryText}>
                      View settings
                    </Text>
                  </Pressable>
                ) : (
                  <Pressable
                    style={[styles.smallButton, styles.smallButtonPrimary]}
                    onPress={() => void state.select(workspace.id)}
                  >
                    <Text style={styles.smallButtonPrimaryText}>
                      Set active
                    </Text>
                  </Pressable>
                )}
                {canLeave ? (
                  <Pressable
                    style={[styles.smallButton, styles.smallButtonDanger]}
                    onPress={() => onLeave(workspace)}
                    accessibilityRole="button"
                    accessibilityLabel={`Leave ${workspace.name}`}
                  >
                    <Text style={styles.smallButtonDangerText}>Leave</Text>
                  </Pressable>
                ) : null}
              </View>
            </View>
          );
        })
      )}

      {actionError ? <Text style={styles.error}>{actionError}</Text> : null}

      {creating ? (
        <View style={styles.card}>
          <Text style={styles.heading}>New workspace</Text>
          <TextInput
            style={styles.input}
            placeholder="Workspace name"
            placeholderTextColor={colors.muted}
            value={name}
            onChangeText={setName}
            autoFocus
            maxLength={120}
          />
          <View style={styles.actionRow}>
            <Pressable
              style={[styles.button, styles.flex, busy && styles.disabled]}
              disabled={busy}
              onPress={() => void onCreate()}
            >
              <Text style={styles.buttonText}>
                {busy ? "Creating…" : "Create"}
              </Text>
            </Pressable>
            <Pressable
              style={[styles.smallButton, styles.smallButtonGhost]}
              disabled={busy}
              onPress={() => {
                setCreating(false);
                setName("");
                setActionError("");
              }}
            >
              <Text style={styles.smallButtonGhostText}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <Pressable
          style={styles.button}
          onPress={() => {
            setActionError("");
            setCreating(true);
          }}
        >
          <Text style={styles.buttonText}>Create workspace</Text>
        </Pressable>
      )}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

function formatRole(role: string): string {
  if (!role) return "Member";
  return role.charAt(0).toUpperCase() + role.slice(1);
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 16,
  },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  cardActive: { borderColor: colors.accent },
  hubLink: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  chevron: { color: colors.muted, fontSize: 24, fontWeight: "300" },
  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  name: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "600",
    flexShrink: 1,
    paddingRight: 8,
  },
  activeTag: {
    color: colors.accent,
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  meta: { color: colors.muted, fontSize: 12, marginTop: 4 },
  credits: { color: colors.textSecondary, fontSize: 13, marginTop: 6 },
  emptyTitle: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "600",
    marginBottom: 6,
  },
  heading: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "600",
    marginBottom: 10,
  },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    color: colors.textPrimary,
    padding: 10,
    marginBottom: 10,
  },
  actionRow: { flexDirection: "row", gap: 8, marginTop: 10, alignItems: "center" },
  flex: { flex: 1 },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    padding: 12,
    alignItems: "center",
  },
  buttonText: { color: colors.bg, fontWeight: "700" },
  smallButton: {
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderWidth: 1,
  },
  smallButtonPrimary: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  smallButtonPrimaryText: { color: colors.bg, fontSize: 13, fontWeight: "700" },
  smallButtonDanger: { borderColor: colors.error, backgroundColor: "transparent" },
  smallButtonDangerText: { color: colors.error, fontSize: 13, fontWeight: "600" },
  smallButtonGhost: { borderColor: colors.border, backgroundColor: "transparent" },
  smallButtonGhostText: {
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: "600",
  },
  retryButton: {
    marginTop: 10,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  retryText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  error: { color: colors.error, fontSize: 13, marginBottom: 12 },
  disabled: { opacity: 0.5 },
  spacer: { height: 40 },
});
