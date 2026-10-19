/**
 * Route: /wallet/plans — workspace plan, usage & subscription management
 * (canonical; the legacy /plan route redirects here).
 *
 * Pick a workspace, see its current plan + entitlements + this period's metered
 * usage, and (for billing managers) subscribe, switch or cancel. Store builds
 * render the read-only Plan & Usage manager with the store-billing notice. Wired to the ENTERPRISE billing API:
 *   - GET  /workspaces                              → listMyWorkspaces
 *   - GET  /me/workspaces/{id}/subscription         → getSubscription
 *   - GET  /me/workspaces/{id}/entitlements         → getEntitlements
 *   - POST /me/workspaces/{id}/subscribe            → subscribeWorkspace
 *   - POST /me/workspaces/{id}/change-plan          → changeWorkspacePlan
 *   - POST /me/workspaces/{id}/cancel               → cancelWorkspaceSubscription
 *
 * No credits/entitlements are granted on-device: `subscribe` opens a hosted
 * Stripe checkout and the webhook fulfils it idempotently. Reads/writes are
 * tenant-scoped + `billing.manage`-gated server-side; a 403 downgrades the
 * screen to read-only rather than crashing. No secrets live here.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useFocusEffect } from "expo-router";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { ApiError } from "@/src/shared/api";
import { listMyWorkspaces } from "@/lib/api";
import type { Workspace } from "@/lib/types";
import {
  cancelWorkspaceSubscription,
  changeWorkspacePlan,
  getEntitlements,
  getSubscription,
  subscribeWorkspace,
  type Entitlements,
  type PlanKey,
  type Subscription,
} from "@/lib/billing";
import {
  PLAN_ORDER,
  entitlementValueLabel,
  featureLabel,
  isDisabledCapability,
  planLabel,
  planRank,
} from "@/components/billing/plan-format";
import { WorkspacePicker } from "@/components/wallet/WorkspacePicker";
import { formatDate, formatStatus } from "@/components/wallet/format";
import {
  externalCheckoutAvailable,
  openCheckoutUrl,
} from "@/components/billing/open-checkout";
import { PlanUsageManager } from "@/components/billing/PlanUsageManager";
import { CreditPackPricing } from "@/components/billing/CreditPackPricing";
import { StoreCreditPacks } from "@/components/billing/StoreCreditPacks";
import { WorkspaceUsageSection } from "@/components/billing/PlanUsageView";
import { colors as storeNoticeColors } from "@/src/shared/theme";

const storeNoticeBg = storeNoticeColors.bg;

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

interface PlanCopy {
  tagline: string;
}

const PLAN_COPY: Record<PlanKey, PlanCopy> = {
  free: { tagline: "Get started with core generation." },
  starter: { tagline: "For solo creators shipping regularly." },
  pro: { tagline: "Priority rendering, more variants, API access." },
  enterprise: { tagline: "SSO, seats and custom limits for teams." },
};

const ACTIVE_STATUSES: readonly string[] = ["active", "trialing"];

/**
 * Store builds cannot sell digital goods through a hosted web checkout
 * (App Store 3.1.1 / Play payments policy); they show the in-app Pro offer
 * instead. Web and internal builds keep the full checkout flow.
 */
export default function WalletPlansScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  if (!externalCheckoutAvailable()) {
    return (
      <ScrollView
        style={{ flex: 1, backgroundColor: storeNoticeBg }}
        contentContainerStyle={{ padding: 20, paddingBottom: 48 }}
        keyboardShouldPersistTaps="handled"
      >
        <PlanUsageManager token={token} />
        <View style={{ height: 20 }} />
        <StoreCreditPacks />
      </ScrollView>
    );
  }
  return <WalletPlansFlow />;
}

function WalletPlansFlow() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [workspaces, setWorkspaces] = useState<readonly Workspace[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [canManage, setCanManage] = useState(true);

  const [loadingWorkspaces, setLoadingWorkspaces] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [usageNonce, setUsageNonce] = useState(0);

  const loadWorkspaces = useCallback(async () => {
    setError(null);
    try {
      const rows = await listMyWorkspaces({ token });
      setWorkspaces(rows);
      setSelectedId((current) => current ?? rows[0]?.id ?? null);
    } catch (err) {
      setError(errorMessage(err, "Failed to load your workspaces."));
    }
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoadingWorkspaces(true);
      loadWorkspaces().finally(() => {
        if (active) setLoadingWorkspaces(false);
      });
      return () => {
        active = false;
      };
    }, [loadWorkspaces]),
  );

  const loadDetail = useCallback(
    async (workspaceId: string) => {
      setError(null);
      setLoadingDetail(true);
      try {
        // Entitlements read needs only membership; subscription read is
        // billing.manage-gated. Fetch both, tolerating a 403 on the sub.
        const [ent, sub] = await Promise.all([
          getEntitlements(workspaceId, { token }),
          getSubscription(workspaceId, { token }).catch((err) => {
            if (err instanceof ApiError && err.status === 403) {
              setCanManage(false);
              return null;
            }
            throw err;
          }),
        ]);
        setEntitlements(ent);
        setSubscription(sub);
        if (!(sub === null)) setCanManage(true);
      } catch (err) {
        setError(errorMessage(err, "Failed to load this workspace's plan."));
      } finally {
        setLoadingDetail(false);
      }
    },
    [token],
  );

  useEffect(() => {
    if (selectedId) {
      setCanManage(true);
      void loadDetail(selectedId);
    }
  }, [selectedId, loadDetail]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await loadWorkspaces();
    if (selectedId) await loadDetail(selectedId);
    setUsageNonce((n) => n + 1);
    setRefreshing(false);
  }, [loadWorkspaces, loadDetail, selectedId]);

  const currentPlanKey = entitlements?.plan_key ?? subscription?.plan_key ?? "free";
  const hasActiveSub =
    subscription !== null && ACTIVE_STATUSES.includes(subscription.status);

  const onSubscribe = useCallback(
    async (planKey: PlanKey) => {
      if (!selectedId) return;
      setActing(planKey);
      setError(null);
      try {
        const res = await subscribeWorkspace(selectedId, { plan_key: planKey }, { token });
        await openCheckoutUrl(res.checkout_url);
      } catch (err) {
        setError(errorMessage(err, "Couldn't start checkout for this plan."));
      } finally {
        setActing(null);
      }
    },
    [selectedId, token],
  );

  const onChange = useCallback(
    (planKey: PlanKey) => {
      if (!selectedId) return;
      Alert.alert(
        "Switch plan?",
        `Change this workspace to ${planLabel(planKey)}. Entitlements update immediately.`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Switch",
            onPress: () => {
              setActing(planKey);
              setError(null);
              changeWorkspacePlan(selectedId, { plan_key: planKey }, { token })
                .then((sub) => {
                  setSubscription(sub);
                  return loadDetail(selectedId);
                })
                .catch((err) => setError(errorMessage(err, "Couldn't switch the plan.")))
                .finally(() => setActing(null));
            },
          },
        ],
      );
    },
    [selectedId, token, loadDetail],
  );

  const onCancel = useCallback(() => {
    if (!selectedId) return;
    Alert.alert(
      "Cancel subscription?",
      "This workspace will fall back to the Free plan at the end of the period.",
      [
        { text: "Keep plan", style: "cancel" },
        {
          text: "Cancel plan",
          style: "destructive",
          onPress: () => {
            setActing("cancel");
            setError(null);
            cancelWorkspaceSubscription(selectedId, { token })
              .then((sub) => {
                setSubscription(sub);
                return loadDetail(selectedId);
              })
              .catch((err) => setError(errorMessage(err, "Couldn't cancel the subscription.")))
              .finally(() => setActing(null));
          },
        },
      ],
    );
  }, [selectedId, token, loadDetail]);

  if (loadingWorkspaces && workspaces.length === 0) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.primary} size="large" />
      </View>
    );
  }

  if (!loadingWorkspaces && workspaces.length === 0) {
    return (
      <ScrollView
        style={styles.container}
        contentContainerStyle={[styles.content, styles.center]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
      >
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Text style={styles.emptyTitle}>No workspaces</Text>
        <Text style={styles.emptyBody}>
          Plans apply to a team workspace. Create one from Team & Workspaces to
          manage a subscription.
        </Text>
        <View style={{ height: 24, alignSelf: "stretch" }} />
        <View style={{ alignSelf: "stretch" }}>
          <CreditPackPricing token={token} />
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
    >
      <WorkspacePicker
        workspaces={workspaces}
        selectedId={selectedId}
        onSelect={(id) => setSelectedId(id)}
      />

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {loadingDetail && !entitlements ? (
        <ActivityIndicator color={colors.primary} style={styles.detailSpinner} />
      ) : (
        <>
          <View style={styles.currentCard}>
            <Text style={styles.currentLabel}>Current plan</Text>
            <Text style={styles.currentPlan}>{planLabel(currentPlanKey)}</Text>
            {subscription ? (
              <View style={styles.currentMetaRow}>
                <Text style={styles.currentMeta}>{formatStatus(subscription.status)}</Text>
                {subscription.current_period_end ? (
                  <Text style={styles.currentMeta}>
                    · renews {formatDate(subscription.current_period_end)}
                  </Text>
                ) : null}
                {subscription.seats > 0 ? (
                  <Text style={styles.currentMeta}>· {subscription.seats} seats</Text>
                ) : null}
              </View>
            ) : (
              <Text style={styles.currentMeta}>No paid subscription</Text>
            )}
          </View>

          {entitlements && Object.keys(entitlements.entitlements).length > 0 ? (
            <View style={styles.entCard}>
              <Text style={styles.sectionTitle}>What&apos;s included</Text>
              {Object.entries(entitlements.entitlements).map(([key, value]) => (
                <View key={key} style={styles.entRow}>
                  <Text style={styles.entKey}>{featureLabel(key)}</Text>
                  <Text
                    style={[styles.entValue, isDisabledCapability(value) && styles.entValueOff]}
                  >
                    {entitlementValueLabel(value)}
                  </Text>
                </View>
              ))}
            </View>
          ) : null}

          {selectedId ? (
            <WorkspaceUsageSection
              key={`${selectedId}:${usageNonce}`}
              workspaceId={selectedId}
              token={token}
            />
          ) : null}

          {!canManage ? (
            <Text style={styles.readOnly}>
              You can view this plan but need the billing role to change it.
            </Text>
          ) : null}

          <CreditPackPricing token={token} />

          <Text style={styles.sectionTitle}>Plans</Text>
          {PLAN_ORDER.map((planKey) => {
            const isCurrent = planKey === (currentPlanKey as PlanKey);
            const isUpgrade = planRank(planKey) > planRank(currentPlanKey);
            const busy = acting === planKey;
            return (
              <View key={planKey} style={[styles.planCard, isCurrent && styles.planCardCurrent]}>
                <View style={styles.planHead}>
                  <Text style={styles.planName}>{planLabel(planKey)}</Text>
                  {isCurrent ? <Text style={styles.planBadge}>Current</Text> : null}
                </View>
                <Text style={styles.planTagline}>{PLAN_COPY[planKey].tagline}</Text>

                {canManage && !isCurrent ? (
                  planKey === "free" ? (
                    hasActiveSub ? (
                      <Pressable
                        style={[styles.planAction, styles.planActionGhost, busy && styles.disabled]}
                        onPress={onCancel}
                        disabled={acting !== null}
                        accessibilityRole="button"
                      >
                        <Text style={styles.planActionGhostText}>Downgrade to Free</Text>
                      </Pressable>
                    ) : null
                  ) : (
                    <Pressable
                      style={[styles.planAction, busy && styles.disabled]}
                      onPress={() =>
                        hasActiveSub ? onChange(planKey) : void onSubscribe(planKey)
                      }
                      disabled={acting !== null}
                      accessibilityRole="button"
                    >
                      {busy ? (
                        <ActivityIndicator color={colors.bg} size="small" />
                      ) : (
                        <Text style={styles.planActionText}>
                          {hasActiveSub ? (isUpgrade ? "Upgrade" : "Switch") : "Subscribe"}
                        </Text>
                      )}
                    </Pressable>
                  )
                ) : null}
              </View>
            );
          })}

          {canManage && hasActiveSub ? (
            <Pressable
              style={[styles.cancelButton, acting === "cancel" && styles.disabled]}
              onPress={onCancel}
              disabled={acting !== null}
              accessibilityRole="button"
            >
              {acting === "cancel" ? (
                <ActivityIndicator color={colors.error} size="small" />
              ) : (
                <Text style={styles.cancelText}>Cancel subscription</Text>
              )}
            </Pressable>
          ) : null}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingBottom: 48 },
  center: { flexGrow: 1, alignItems: "center", justifyContent: "center" },
  error: { color: colors.error, fontSize: 14, marginTop: 14 },
  detailSpinner: { marginTop: 32 },
  currentCard: {
    marginTop: 18,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
  },
  currentLabel: { color: colors.textSecondary, fontSize: 13 },
  currentPlan: { color: colors.textPrimary, fontSize: 24, fontWeight: "800", marginTop: 4 },
  currentMetaRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 },
  currentMeta: { color: colors.textSecondary, fontSize: 13 },
  entCard: {
    marginTop: 16,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
  },
  entRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 7,
    gap: 12,
  },
  entKey: { color: colors.textSecondary, fontSize: 14, flexShrink: 1 },
  entValue: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  entValueOff: { color: colors.muted, fontWeight: "400" },
  readOnly: { color: colors.muted, fontSize: 13, marginTop: 16, fontStyle: "italic" },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "700",
    marginTop: 24,
    marginBottom: 10,
  },
  planCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
    marginBottom: 12,
  },
  planCardCurrent: { borderColor: colors.primary },
  planHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  planName: { color: colors.textPrimary, fontSize: 17, fontWeight: "700" },
  planBadge: {
    color: colors.bg,
    backgroundColor: colors.primary,
    fontSize: 11,
    fontWeight: "700",
    overflow: "hidden",
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  planTagline: { color: colors.textSecondary, fontSize: 13, marginTop: 6, lineHeight: 19 },
  planAction: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 14,
  },
  planActionText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  planActionGhost: {
    backgroundColor: "transparent",
    borderColor: colors.border,
    borderWidth: 1,
  },
  planActionGhostText: { color: colors.textSecondary, fontSize: 15, fontWeight: "600" },
  disabled: { opacity: 0.5 },
  cancelButton: { alignItems: "center", paddingVertical: 16, marginTop: 8 },
  cancelText: { color: colors.error, fontSize: 15, fontWeight: "600" },
  emptyTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "700", marginBottom: 8 },
  emptyBody: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 21,
    textAlign: "center",
    paddingHorizontal: 20,
  },
});
