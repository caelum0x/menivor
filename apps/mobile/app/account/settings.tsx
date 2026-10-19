/**
 * Account & settings (account/dev cluster).
 *
 * Three caller-scoped sections, each with its own load/error state:
 *   - ACCOUNT: the signed-in identity (email, credit balance, jobs run) from
 *     GET /me, plus a sign-out control.
 *   - PUBLIC PROFILE: the editable handle / display name / bio backed by
 *     GET /creators/{id} + PATCH /me/profile (validated server-side).
 *   - SUBSCRIPTION: the ACTIVE workspace's plan + status + renewal + entitlements
 *     from GET /me/workspaces/{id}/subscription and .../entitlements, with a
 *     cancel action (owner/admin, gated by `billing.manage` server-side).
 *
 * It also surfaces the account HUBS (Insights, Wallet, Team, Privacy & data)
 * and a prominent, always-visible "Delete account" entry that deep-links to the
 * GDPR erasure flow — required so account deletion is discoverable per App Store
 * review guideline 5.1.1(v). The erasure / export / consent calls themselves are
 * wired in `lib/compliance.ts` and driven from the linked Privacy & Data screen
 * (POST /me/erase, POST /me/data-export, GET/PUT /me/consent).
 *
 * Auth flows through the shared `x-api-key` client via the session token — no
 * secrets live here.
 *
 * NAV MANIFEST:
 *   { route: "/account/settings", title: "Account & Settings" }
 * Links out to (already registered elsewhere):
 *   { route: "/insights",        title: "Insights" }
 *   { route: "/wallet",          title: "Wallet" }
 *   { route: "/account/workspaces", title: "Team & Workspaces" }
 *   { route: "/account/privacy", title: "Privacy & Data" }
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

import { StatCard } from "@/components/me/StatCard";
import { colors } from "@/components/me/theme";
import {
  getCreatorProfile,
  isAbortError,
  me as fetchMe,
  updateMyProfile,
} from "@/lib/api";
import { useActiveWorkspace } from "@/lib/active-workspace";
import {
  cancelWorkspaceSubscription,
  getEntitlements,
  getSubscription,
  type Entitlements,
  type Subscription,
} from "@/lib/billing";
import type { CreatorProfile, Me, ProfileUpdateRequest } from "@/lib/types";
import { useConfirmSignOut, useSession } from "@/src/shared/auth";
import { openLegalDocument } from "@/src/shared/legal/open-legal";
import { isRouteAvailable } from "@/src/shared/release/surface";
import { ProMembershipCard } from "@/src/shared/billing";

type LoadStatus = "loading" | "ready" | "error";

export default function AccountSettingsScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const workspace = useActiveWorkspace(token);

  const [nonce, setNonce] = React.useState(0);
  const reloadAll = React.useCallback(() => {
    setNonce((n) => n + 1);
    workspace.reload();
  }, [workspace]);

  // --- Account (GET /me) ----------------------------------------------------
  const [account, setAccount] = React.useState<Me | null>(null);
  const [accountStatus, setAccountStatus] =
    React.useState<LoadStatus>("loading");
  const [accountError, setAccountError] = React.useState("");

  // --- Public profile (GET /creators/{id}, PATCH /me/profile) ---------------
  const [profile, setProfile] = React.useState<CreatorProfile | null>(null);
  const [profileStatus, setProfileStatus] =
    React.useState<LoadStatus>("loading");
  const [profileError, setProfileError] = React.useState("");
  const [handle, setHandle] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [bio, setBio] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [saveMessage, setSaveMessage] = React.useState("");

  React.useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setAccountStatus("loading");
    setProfileStatus("loading");
    setAccountError("");
    setProfileError("");

    (async () => {
      let userId = "";
      try {
        const profileMe = await fetchMe({ token, signal: controller.signal });
        if (!active) return;
        setAccount(profileMe);
        setAccountStatus("ready");
        userId = profileMe.user_id;
      } catch (err: unknown) {
        if (!active || isAbortError(err)) return;
        setAccountError(
          err instanceof Error ? err.message : "Account is unavailable.",
        );
        setAccountStatus("error");
      }

      if (!userId) {
        if (active) {
          setProfileError("Sign in to edit your public profile.");
          setProfileStatus("error");
        }
        return;
      }

      try {
        const creator = await getCreatorProfile(userId, {
          token,
          signal: controller.signal,
        });
        if (!active) return;
        setProfile(creator);
        setHandle(creator.handle ?? "");
        setDisplayName(creator.display_name ?? "");
        setBio(creator.bio ?? "");
        setProfileStatus("ready");
      } catch (err: unknown) {
        if (!active || isAbortError(err)) return;
        setProfileError(
          err instanceof Error ? err.message : "Profile is unavailable.",
        );
        setProfileStatus("error");
      }
    })();

    return () => {
      active = false;
      controller.abort();
    };
  }, [token, nonce]);

  const dirty =
    profile !== null &&
    (handle.trim() !== (profile.handle ?? "") ||
      displayName.trim() !== (profile.display_name ?? "") ||
      bio !== (profile.bio ?? ""));

  const onSaveProfile = React.useCallback(async (): Promise<void> => {
    if (!profile) return;
    setSaving(true);
    setProfileError("");
    setSaveMessage("");
    const body: ProfileUpdateRequest = {
      handle: handle.trim(),
      display_name: displayName.trim(),
      bio,
    };
    try {
      const updated = await updateMyProfile(body, { token });
      setProfile(updated);
      setHandle(updated.handle ?? "");
      setDisplayName(updated.display_name ?? "");
      setBio(updated.bio ?? "");
      setSaveMessage("Profile saved.");
    } catch (err: unknown) {
      setProfileError(
        err instanceof Error ? err.message : "Could not save the profile.",
      );
    } finally {
      setSaving(false);
    }
  }, [profile, handle, displayName, bio, token]);

  const onSignOut = useConfirmSignOut();

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={false}
          onRefresh={reloadAll}
          tintColor={colors.accent}
        />
      }
    >
      <Stack.Screen options={{ title: "Account & Settings" }} />

      {/* ACCOUNT ------------------------------------------------------------ */}
      <Text style={styles.sectionTitle}>Account</Text>
      {accountStatus === "loading" ? (
        <ActivityIndicator color={colors.accent} style={styles.spacer} />
      ) : accountStatus === "error" ? (
        <InlineError message={accountError} onRetry={reloadAll} />
      ) : account ? (
        <>
          <View style={styles.card}>
            <Text style={styles.emailLabel}>Signed in as</Text>
            <Text style={styles.email} selectable numberOfLines={1}>
              {account.email || "Device account"}
            </Text>
          </View>
          <View style={styles.statRow}>
            <View style={styles.flex}>
              <StatCard
                label="Credits"
                value={account.credits.toLocaleString()}
                accent={colors.accent}
              />
            </View>
            <View style={styles.flex}>
              <StatCard
                label="Reels created"
                value={account.jobs_count.toLocaleString()}
              />
            </View>
          </View>
        </>
      ) : null}

      {/* PUBLIC PROFILE ---------------------------------------------------- */}
      <Text style={styles.sectionTitle}>Public profile</Text>
      {profileStatus === "loading" ? (
        <ActivityIndicator color={colors.accent} style={styles.spacer} />
      ) : profileStatus === "error" ? (
        <InlineError message={profileError} onRetry={reloadAll} />
      ) : (
        <View style={styles.card}>
          <Text style={styles.fieldLabel}>Handle</Text>
          <TextInput
            style={styles.input}
            placeholder="your-handle"
            placeholderTextColor={colors.muted}
            value={handle}
            onChangeText={setHandle}
            autoCapitalize="none"
            autoCorrect={false}
            maxLength={64}
          />
          <Text style={styles.fieldLabel}>Display name</Text>
          <TextInput
            style={styles.input}
            placeholder="Display name"
            placeholderTextColor={colors.muted}
            value={displayName}
            onChangeText={setDisplayName}
            maxLength={200}
          />
          <Text style={styles.fieldLabel}>Bio</Text>
          <TextInput
            style={[styles.input, styles.multiline]}
            placeholder="Tell viewers about your channel"
            placeholderTextColor={colors.muted}
            value={bio}
            onChangeText={setBio}
            multiline
            maxLength={2000}
          />
          {profile ? (
            <Text style={styles.meta}>
              {profile.follower_count.toLocaleString()} followers ·{" "}
              {profile.published_template_count.toLocaleString()} published
            </Text>
          ) : null}
          <Pressable
            style={[
              styles.button,
              (!dirty || saving) && styles.disabled,
              styles.saveButton,
            ]}
            disabled={!dirty || saving}
            onPress={() => void onSaveProfile()}
          >
            <Text style={styles.buttonText}>
              {saving ? "Saving…" : "Save profile"}
            </Text>
          </Pressable>
          {saveMessage ? (
            <Text style={styles.success}>{saveMessage}</Text>
          ) : null}
          {profileError ? (
            <Text style={styles.error}>{profileError}</Text>
          ) : null}
        </View>
      )}

      {/* SUBSCRIPTION ------------------------------------------------------ */}
      <Text style={styles.sectionTitle}>Subscription</Text>
      {isRouteAvailable("/account/workspaces") ? (
        <SubscriptionSection
          token={token}
          workspaceId={workspace.activeId}
          workspaceName={workspace.active?.name ?? null}
          workspaceStatus={workspace.status}
          onManageWorkspaces={() => router.push("/account/workspaces")}
        />
      ) : (
        // Store builds: Menivor Pro is an in-app subscription (App Store / Play).
        <ProMembershipCard />
      )}

      {/* HUBS -------------------------------------------------------------- */}
      <Text style={styles.sectionTitle}>Hubs</Text>
      {isRouteAvailable("/insights") ? (
        <HubLink
          title="Insights"
          subtitle="Your creator stats, analytics, presets and referrals"
          onPress={() => router.push("/insights")}
        />
      ) : null}
      <HubLink
        title="Credits & Pro"
        subtitle="Balance, credit packs, history and your plan"
        onPress={() => router.push("/wallet")}
      />
      {isRouteAvailable("/account/workspaces") ? (
        <HubLink
          title="Team & workspaces"
          subtitle="Members, roles and invitations for shared workspaces"
          onPress={() => router.push("/account/workspaces")}
        />
      ) : null}
      <HubLink
        title="Privacy & data"
        subtitle="Export your data, manage consent and delete your account"
        onPress={() => router.push("/privacy")}
      />
      {isRouteAvailable("/account/developer-keys") ? (
        <HubLink
          title="Developer & API keys"
          subtitle="Manage API keys, webhooks, and resale gateway keys"
          onPress={() => router.push("/account/developer-keys")}
        />
      ) : null}

      {/* HELP & LEGAL ------------------------------------------------------ */}
      <Text style={styles.sectionTitle}>Help & legal</Text>
      <HubLink
        title="Support"
        subtitle="Get help with a job, export, purchase, or account"
        onPress={() => router.push("/support")}
      />
      <HubLink
        title="Terms of Service"
        subtitle="The terms that govern your use of Menivor"
        onPress={() => openLegalDocument("terms", router)}
      />
      <HubLink
        title="Privacy Policy"
        subtitle="What we collect, why, and your rights"
        onPress={() => openLegalDocument("privacy", router)}
      />

      {/* DANGER ZONE ------------------------------------------------------- */}
      <Text style={styles.sectionTitle}>Danger zone</Text>
      <View style={[styles.card, styles.dangerCard]}>
        <Text style={styles.dangerTitle}>Delete account</Text>
        <Text style={styles.dangerBody}>
          Permanently and irreversibly delete your account. Your personal
          information is anonymized; records we're legally required to keep no
          longer identify you. You can export a copy of your data first.
        </Text>
        <Pressable
          style={styles.deleteButton}
          onPress={() => router.push("/privacy")}
          accessibilityRole="button"
          accessibilityLabel="Delete account"
        >
          <Text style={styles.deleteButtonText}>Delete account…</Text>
        </Pressable>
      </View>

      {/* SIGN OUT ---------------------------------------------------------- */}
      <Pressable style={styles.signOutButton} onPress={onSignOut}>
        <Text style={styles.signOutText}>Sign out</Text>
      </Pressable>

      <View style={styles.spacer} />
    </ScrollView>
  );
}

interface SubscriptionSectionProps {
  token: string | undefined;
  workspaceId: string | null;
  workspaceName: string | null;
  workspaceStatus: "loading" | "ready" | "error";
  onManageWorkspaces: () => void;
}

function SubscriptionSection({
  token,
  workspaceId,
  workspaceName,
  workspaceStatus,
  onManageWorkspaces,
}: SubscriptionSectionProps): React.ReactElement {
  const [status, setStatus] = React.useState<LoadStatus>("loading");
  const [error, setError] = React.useState("");
  const [subscription, setSubscription] = React.useState<Subscription | null>(
    null,
  );
  const [entitlements, setEntitlements] = React.useState<Entitlements | null>(
    null,
  );
  const [nonce, setNonce] = React.useState(0);
  const [cancelling, setCancelling] = React.useState(false);
  const reload = React.useCallback(() => setNonce((n) => n + 1), []);

  React.useEffect(() => {
    if (workspaceStatus === "loading") return;
    if (!workspaceId) {
      setStatus("ready");
      setSubscription(null);
      setEntitlements(null);
      return;
    }
    let active = true;
    const controller = new AbortController();
    setStatus("loading");
    setError("");
    (async () => {
      try {
        const [sub, ent] = await Promise.all([
          getSubscription(workspaceId, { token, signal: controller.signal }),
          getEntitlements(workspaceId, { token, signal: controller.signal }),
        ]);
        if (!active) return;
        setSubscription(sub);
        setEntitlements(ent);
        setStatus("ready");
      } catch (err: unknown) {
        if (!active || isAbortError(err)) return;
        setError(
          err instanceof Error
            ? err.message
            : "Subscription details are unavailable.",
        );
        setStatus("error");
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [workspaceId, workspaceStatus, token, nonce]);

  const onCancel = React.useCallback((): void => {
    if (!workspaceId) return;
    Alert.alert(
      "Cancel subscription",
      "Cancel this workspace's subscription? It will revert to the free plan.",
      [
        { text: "Keep plan", style: "cancel" },
        {
          text: "Cancel plan",
          style: "destructive",
          onPress: () => {
            setCancelling(true);
            setError("");
            cancelWorkspaceSubscription(workspaceId, { token })
              .then(() => reload())
              .catch((err: unknown) => {
                setError(
                  err instanceof Error
                    ? err.message
                    : "Could not cancel the subscription.",
                );
              })
              .finally(() => setCancelling(false));
          },
        },
      ],
    );
  }, [workspaceId, token, reload]);

  if (workspaceStatus === "loading" || status === "loading") {
    return <ActivityIndicator color={colors.accent} style={styles.spacer} />;
  }
  if (!workspaceId) {
    return (
      <View style={styles.card}>
        <Text style={styles.meta}>
          No active workspace. Create or switch to one to manage a subscription.
        </Text>
        <Pressable style={styles.retryButton} onPress={onManageWorkspaces}>
          <Text style={styles.retryText}>Manage workspaces</Text>
        </Pressable>
      </View>
    );
  }
  if (status === "error") {
    return <InlineError message={error} onRetry={reload} />;
  }

  const planKey =
    subscription?.plan_key || entitlements?.plan_key || "free";
  const active =
    subscription?.status === "active" || subscription?.status === "trialing";
  const entitlementRows = entitlements
    ? Object.entries(entitlements.entitlements)
    : [];

  return (
    <View style={styles.card}>
      <View style={styles.rowBetween}>
        <Text style={styles.planName}>{formatPlan(planKey)}</Text>
        <Text
          style={[
            styles.planStatus,
            active ? styles.planStatusActive : styles.planStatusMuted,
          ]}
        >
          {formatStatus(subscription?.status ?? "free")}
        </Text>
      </View>
      {workspaceName ? (
        <Text style={styles.meta}>{workspaceName}</Text>
      ) : null}
      {subscription ? (
        <>
          <Text style={styles.meta}>
            {formatInterval(subscription.interval)} ·{" "}
            {subscription.seats} seat{subscription.seats === 1 ? "" : "s"}
          </Text>
          {subscription.current_period_end ? (
            <Text style={styles.meta}>
              Renews {formatDate(subscription.current_period_end)}
            </Text>
          ) : null}
        </>
      ) : (
        <Text style={styles.meta}>
          No paid subscription — using base/free entitlements.
        </Text>
      )}

      {entitlementRows.length > 0 ? (
        <View style={styles.entitlements}>
          <Text style={styles.fieldLabel}>Plan features</Text>
          {entitlementRows.slice(0, 8).map(([key, value]) => (
            <View key={key} style={styles.entitlementRow}>
              <Text style={styles.entitlementKey} numberOfLines={1}>
                {formatEntitlementKey(key)}
              </Text>
              <Text style={styles.entitlementValue}>
                {formatEntitlementValue(value)}
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      {subscription && active ? (
        <Pressable
          style={[styles.cancelButton, cancelling && styles.disabled]}
          disabled={cancelling}
          onPress={onCancel}
        >
          <Text style={styles.cancelText}>
            {cancelling ? "Cancelling…" : "Cancel subscription"}
          </Text>
        </Pressable>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

interface HubLinkProps {
  title: string;
  subtitle: string;
  onPress: () => void;
}

function HubLink({
  title,
  subtitle,
  onPress,
}: HubLinkProps): React.ReactElement {
  return (
    <Pressable
      style={styles.link}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={title}
    >
      <Text style={styles.linkTitle}>{title}</Text>
      <Text style={styles.linkSubtitle}>{subtitle}</Text>
    </Pressable>
  );
}

function InlineError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}): React.ReactElement {
  return (
    <View style={styles.card}>
      <Text style={styles.error}>{message}</Text>
      <Pressable style={styles.retryButton} onPress={onRetry}>
        <Text style={styles.retryText}>Try again</Text>
      </Pressable>
    </View>
  );
}

function formatPlan(planKey: string): string {
  if (!planKey) return "Free";
  return planKey.charAt(0).toUpperCase() + planKey.slice(1);
}

function formatStatus(status: string): string {
  switch (status) {
    case "active":
      return "Active";
    case "trialing":
      return "Trial";
    case "past_due":
      return "Past due";
    case "canceled":
      return "Canceled";
    case "free":
      return "Free";
    default:
      return status;
  }
}

function formatInterval(interval: string): string {
  if (interval === "year") return "Annual";
  if (interval === "month") return "Monthly";
  return interval || "Monthly";
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatEntitlementKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatEntitlementValue(value: number | boolean | string): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    return value < 0 ? "Unlimited" : value.toLocaleString();
  }
  return String(value);
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: "700",
    marginTop: 20,
    marginBottom: 12,
  },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  emailLabel: { color: colors.muted, fontSize: 12, marginBottom: 4 },
  email: { color: colors.textPrimary, fontSize: 16, fontWeight: "600" },
  statRow: { flexDirection: "row", gap: 12, marginBottom: 12 },
  flex: { flex: 1 },
  fieldLabel: {
    color: colors.textSecondary,
    fontSize: 12,
    fontWeight: "600",
    marginBottom: 6,
  },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    color: colors.textPrimary,
    padding: 10,
    marginBottom: 12,
  },
  multiline: { minHeight: 80, textAlignVertical: "top" },
  meta: { color: colors.muted, fontSize: 12, marginTop: 4 },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    padding: 12,
    alignItems: "center",
  },
  saveButton: { marginTop: 4 },
  buttonText: { color: colors.bg, fontWeight: "700" },
  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  planName: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  planStatus: { fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
  planStatusActive: { color: colors.success },
  planStatusMuted: { color: colors.muted },
  entitlements: { marginTop: 12 },
  entitlementRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderTopColor: colors.border,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  entitlementKey: { color: colors.textSecondary, fontSize: 13, flexShrink: 1 },
  entitlementValue: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: "600",
    paddingLeft: 12,
  },
  cancelButton: {
    marginTop: 14,
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  cancelText: { color: colors.error, fontSize: 13, fontWeight: "600" },
  link: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginTop: 8,
    marginBottom: 12,
  },
  linkTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  linkSubtitle: { color: colors.muted, fontSize: 12, marginTop: 4 },
  dangerCard: { borderColor: colors.error },
  dangerTitle: {
    color: colors.error,
    fontSize: 15,
    fontWeight: "700",
    marginBottom: 6,
  },
  dangerBody: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 19,
    marginBottom: 12,
  },
  deleteButton: {
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  deleteButtonText: { color: colors.error, fontSize: 14, fontWeight: "700" },
  signOutButton: {
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 4,
  },
  signOutText: { color: colors.error, fontSize: 14, fontWeight: "600" },
  retryButton: {
    marginTop: 10,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  retryText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  success: { color: colors.success, fontSize: 13, marginTop: 8 },
  error: { color: colors.error, fontSize: 13, marginTop: 8 },
  disabled: { opacity: 0.5 },
  spacer: { height: 40 },
});
