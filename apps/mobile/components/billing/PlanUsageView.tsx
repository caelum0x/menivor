/**
 * The ENTERPRISE Plan & Usage detail view for a single workspace (Epic 3 Billing
 * Platform).
 *
 * READ-MOSTLY: it surfaces the workspace's CURRENT PLAN, the plan's ENTITLEMENTS
 * bundle, and this month's metered USAGE vs each plan limit (a progress bar per
 * capped metric, an "Unlimited" treatment otherwise). The one action offered is
 * the UPGRADE CTA: it starts a Stripe hosted checkout for a richer tier and opens
 * it in the browser — no credits/entitlements are granted here (the backend
 * fulfils the purchase idempotently on the provider webhook).
 *
 * TENANT ISOLATION: entitlements + usage are workspace-membership reads, so any
 * member sees them for THIS workspace only. Starting/managing a subscription is
 * gated on `billing.manage`; we resolve the caller's effective permissions first
 * and only render the upgrade CTA (and fetch the billing.manage-only
 * subscription detail) when they hold it — a non-manager sees a clear note
 * instead of a 403. No secrets live here; auth flows through the shared api
 * client as `x-api-key`.
 */

import { useCallback, useState } from "react";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";
import { Icon } from "@/components/ui/Icon";

import { getMyPermissions } from "@/lib/api";
import {
  getEntitlements,
  getSubscription,
  getWorkspaceUsage,
  subscribeWorkspace,
  type Entitlements,
  type PlanKey,
  type Subscription,
  type Usage,
} from "@/lib/billing";
import type { Permissions, Workspace } from "@/lib/types";

import {
  externalCheckoutAvailable,
  openCheckoutUrl,
} from "@/components/billing/open-checkout";
import { StoreBillingNotice } from "@/components/billing/StoreBillingNotice";
import {
  entitlementValueLabel,
  featureLabel,
  formatInt,
  formatPeriod,
  isDisabledCapability,
  metricRatio,
  planLabel,
  upgradeTargets,
} from "@/components/billing/plan-format";
import { describeError } from "@/components/me/errors";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

interface PlanUsageViewProps {
  workspace: Workspace;
  token: string | undefined;
  onBack: () => void;
}

export function PlanUsageView({ workspace, token, onBack }: PlanUsageViewProps) {
  const permsFetcher = useCallback(
    () => getMyPermissions(workspace.id, { token }),
    [workspace.id, token],
  );
  const { status, data: perms, error, reload } =
    useResource<Permissions>(permsFetcher);

  const canManage = !!perms?.permissions.includes("billing.manage");

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

      <SectionState status={status} error={error} onRetry={reload}>
        <PlanUsageBody
          workspaceId={workspace.id}
          token={token}
          canManage={canManage}
        />
      </SectionState>
    </View>
  );
}

// ---------------------------------------------------------------------------
// The body: current plan + entitlements + usage, then (for managers) the
// upgrade CTA. Rendered once we know the caller's permissions.
// ---------------------------------------------------------------------------

interface PlanUsageBodyProps {
  workspaceId: string;
  token: string | undefined;
  canManage: boolean;
}

function PlanUsageBody({ workspaceId, token, canManage }: PlanUsageBodyProps) {
  const entFetcher = useCallback(
    () => getEntitlements(workspaceId, { token }),
    [workspaceId, token],
  );
  const {
    status: entStatus,
    data: entitlements,
    error: entError,
    reload: reloadEnt,
  } = useResource<Entitlements>(entFetcher);

  const usageFetcher = useCallback(
    () => getWorkspaceUsage(workspaceId, undefined, { token }),
    [workspaceId, token],
  );
  const {
    status: usageStatus,
    data: usage,
    error: usageError,
    reload: reloadUsage,
  } = useResource<Usage>(usageFetcher);

  const planKey = entitlements?.plan_key ?? null;

  return (
    <View style={styles.body}>
      <Section title="CURRENT PLAN">
        <SectionState status={entStatus} error={entError} onRetry={reloadEnt}>
          {entitlements ? (
            <CurrentPlanCard
              planKey={entitlements.plan_key}
              workspaceId={workspaceId}
              token={token}
              canManage={canManage}
            />
          ) : null}
        </SectionState>
      </Section>

      <Section title="PLAN ENTITLEMENTS">
        <SectionState status={entStatus} error={entError} onRetry={reloadEnt}>
          {entitlements ? (
            <EntitlementsCard entitlements={entitlements.entitlements} />
          ) : null}
        </SectionState>
      </Section>

      <Section title="USAGE THIS PERIOD">
        <SectionState
          status={usageStatus}
          error={usageError}
          onRetry={reloadUsage}
        >
          {usage ? <UsageCard usage={usage} /> : null}
        </SectionState>
      </Section>

      {canManage && !externalCheckoutAvailable() ? (
        <StoreBillingNotice subject="Workspace plan upgrades" />
      ) : canManage ? (
        <UpgradeSection
          workspaceId={workspaceId}
          token={token}
          currentPlan={planKey}
        />
      ) : (
        <Text style={styles.note}>
          Plans and billing are managed by workspace owners and admins. You can
          see your plan and usage here, but you don&apos;t have access to change
          the plan for this workspace.
        </Text>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Standalone "usage this period" section for one workspace. Used by the
// canonical plans screen (/wallet/plans) so plan management and metered usage
// live on one screen. Workspace-membership read; explicit loading/error states.
// ---------------------------------------------------------------------------

export function WorkspaceUsageSection({
  workspaceId,
  token,
}: {
  workspaceId: string;
  token: string | undefined;
}) {
  const usageFetcher = useCallback(
    () => getWorkspaceUsage(workspaceId, undefined, { token }),
    [workspaceId, token],
  );
  const { status, data: usage, error, reload } =
    useResource<Usage>(usageFetcher);

  return (
    <Section title="USAGE THIS PERIOD">
      <SectionState status={status} error={error} onRetry={reload}>
        {usage ? <UsageCard usage={usage} /> : null}
      </SectionState>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Current plan card. Shows the plan badge for everyone; managers also see the
// live subscription status/renewal (a `billing.manage`-only read).
// ---------------------------------------------------------------------------

function CurrentPlanCard({
  planKey,
  workspaceId,
  token,
  canManage,
}: {
  planKey: string;
  workspaceId: string;
  token: string | undefined;
  canManage: boolean;
}) {
  const subFetcher = useCallback(
    () => getSubscription(workspaceId, { token }),
    [workspaceId, token],
  );
  // Only managers may read the subscription; skip the fetch otherwise so a
  // member never triggers a 403 for a detail they can't see anyway.
  const { data: subscription } = useResource<Subscription | null>(
    useCallback(
      () => (canManage ? subFetcher() : Promise.resolve(null)),
      [canManage, subFetcher],
    ),
  );

  return (
    <View style={styles.card}>
      <View style={styles.planRow}>
        <Text style={styles.planName}>{planLabel(planKey)}</Text>
        <View style={styles.planBadge}>
          <Text style={styles.planBadgeText}>PLAN</Text>
        </View>
      </View>
      {subscription ? (
        <View style={styles.subDetails}>
          <StatRow label="Status" value={subscriptionStatusLabel(subscription)} />
          {subscription.interval ? (
            <StatRow label="Billing" value={intervalLabel(subscription.interval)} />
          ) : null}
          {typeof subscription.seats === "number" && subscription.seats > 0 ? (
            <StatRow label="Seats" value={formatInt(subscription.seats)} />
          ) : null}
          {subscription.current_period_end ? (
            <StatRow
              label="Renews"
              value={formatDate(subscription.current_period_end)}
            />
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

function subscriptionStatusLabel(sub: Subscription): string {
  const status = (sub.status || "").trim();
  switch (status) {
    case "active":
      return "Active";
    case "trialing":
      return "Trialing";
    case "past_due":
      return "Past due";
    case "canceled":
      return "Canceled";
    default:
      return status
        ? status.charAt(0).toUpperCase() + status.slice(1)
        : "Active";
  }
}

function intervalLabel(interval: string): string {
  const key = interval.trim().toLowerCase();
  if (key === "month") return "Monthly";
  if (key === "year") return "Yearly";
  return key ? key.charAt(0).toUpperCase() + key.slice(1) : "—";
}

/** Format an ISO timestamp as "Aug 2026" without relying on Hermes `Intl`. */
function formatDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})/.exec(iso.trim());
  if (match) return formatPeriod(`${match[1]}-${match[2]}`) || iso;
  return iso;
}

// ---------------------------------------------------------------------------
// Entitlements card: one row per feature (numeric limits + capabilities).
// ---------------------------------------------------------------------------

function EntitlementsCard({
  entitlements,
}: {
  entitlements: Record<string, number | boolean | string>;
}) {
  const keys = Object.keys(entitlements);
  if (keys.length === 0) {
    return (
      <Text style={styles.empty}>
        No entitlements are published for this plan.
      </Text>
    );
  }
  return (
    <View style={styles.card}>
      {keys.map((key) => {
        const value = entitlements[key];
        return (
          <View style={styles.row} key={key}>
            <Text style={styles.rowLabel}>{featureLabel(key)}</Text>
            <Text
              style={[
                styles.rowValue,
                isDisabledCapability(value) && styles.rowValueMuted,
              ]}
              numberOfLines={1}
            >
              {entitlementValueLabel(value)}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Usage card: a metered row per plan-capped metric with a progress bar, plus
// any additional metered metrics the plan does not cap.
// ---------------------------------------------------------------------------

function UsageCard({ usage }: { usage: Usage }) {
  const period = formatPeriod(usage.period);
  // Prefer the overage rows (they carry used + limit + overage). Fold in any
  // metered metric that has no overage row so nothing is hidden.
  const covered = new Set(usage.overage.map((o) => o.metric));
  const extras = Object.keys(usage.usage)
    .filter((metric) => !covered.has(metric))
    .map((metric) => ({
      metric,
      used: usage.usage[metric],
      limit: null as number | null,
      overage: 0,
    }));
  const rows = [...usage.overage, ...extras];

  if (rows.length === 0) {
    return (
      <View style={styles.card}>
        <Text style={styles.empty}>
          No metered usage recorded for {period || "this period"} yet.
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.card}>
      {period ? <Text style={styles.periodLabel}>{period}</Text> : null}
      {rows.map((row) => (
        <MetricBar
          key={row.metric}
          metric={row.metric}
          used={row.used}
          limit={row.limit}
          overage={row.overage}
        />
      ))}
    </View>
  );
}

/** Colour the bar red near/over the limit, amber past 70%, else green. */
function barColor(ratio: number): string {
  if (ratio >= 0.9) return colors.error;
  if (ratio >= 0.7) return colors.accent;
  return colors.success;
}

function MetricBar({
  metric,
  used,
  limit,
  overage,
}: {
  metric: string;
  used: number;
  limit: number | null;
  overage: number;
}) {
  const ratio = metricRatio(used, limit);
  const label = featureLabel(metric);
  const usedLabel =
    ratio === null
      ? `${formatInt(used)} used · Unlimited`
      : `${formatInt(used)} / ${formatInt(limit as number)} used`;

  return (
    <View style={styles.metric}>
      <View style={styles.metricHead}>
        <Text style={styles.metricName} numberOfLines={1}>
          {label}
        </Text>
        {overage > 0 ? (
          <Text style={styles.overageBadge}>{`+${formatInt(overage)} over`}</Text>
        ) : null}
      </View>

      {ratio === null ? (
        <View style={styles.unlimitedBadge}>
          <Text style={styles.unlimitedText}>No cap</Text>
        </View>
      ) : (
        <View
          style={styles.track}
          accessibilityRole="progressbar"
          accessibilityValue={{ min: 0, max: 100, now: Math.round(ratio * 100) }}
        >
          <View
            style={[
              styles.fill,
              {
                width: `${Math.max(2, Math.round(ratio * 100))}%`,
                backgroundColor: barColor(ratio),
              },
            ]}
          />
        </View>
      )}

      <Text style={styles.metricUsage} numberOfLines={1}>
        {usedLabel}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Upgrade CTA (managers only): a button per richer tier that starts a Stripe
// checkout and opens it. No entitlements are granted here.
// ---------------------------------------------------------------------------

function UpgradeSection({
  workspaceId,
  token,
  currentPlan,
}: {
  workspaceId: string;
  token: string | undefined;
  currentPlan: string | null;
}) {
  const targets = upgradeTargets(currentPlan);
  const [busyPlan, setBusyPlan] = useState<PlanKey | null>(null);
  const [ctaError, setCtaError] = useState<string | null>(null);

  const onUpgrade = useCallback(
    async (planKey: PlanKey) => {
      setBusyPlan(planKey);
      setCtaError(null);
      try {
        const result = await subscribeWorkspace(
          workspaceId,
          { plan_key: planKey, provider: "stripe" },
          { token },
        );
        if (!result.checkout_url) {
          throw new Error("The checkout URL was missing from the response.");
        }
        await openCheckoutUrl(result.checkout_url);
      } catch (err) {
        const message = describeError(err, "Couldn't start checkout.");
        setCtaError(message);
        Alert.alert("Couldn't start upgrade", message);
      } finally {
        setBusyPlan(null);
      }
    },
    [workspaceId, token],
  );

  if (targets.length === 0) {
    return (
      <Section title="UPGRADE">
        <Text style={styles.empty}>
          You&apos;re on the top plan. Contact us to tailor an enterprise
          agreement.
        </Text>
      </Section>
    );
  }

  return (
    <Section title="UPGRADE">
      <View style={styles.stack}>
        <Text style={styles.hint}>
          Move this workspace to a richer plan. Checkout opens in your browser;
          the new plan takes effect once payment is confirmed.
        </Text>
        <View style={styles.list}>
          {targets.map((planKey) => {
            const busy = busyPlan === planKey;
            const disabled = busyPlan !== null;
            return (
              <Pressable
                key={planKey}
                style={[styles.upgradeButton, disabled && styles.disabled]}
                onPress={() => void onUpgrade(planKey)}
                disabled={disabled}
                accessibilityRole="button"
                accessibilityLabel={`Upgrade to ${planLabel(planKey)}`}
                accessibilityState={{ disabled, busy }}
              >
                <Text style={styles.upgradeName}>{planLabel(planKey)}</Text>
                <Text style={styles.upgradeCta}>
                  {busy ? "Opening…" : "Upgrade"}
                </Text>
              </Pressable>
            );
          })}
        </View>
        {ctaError ? <Text style={styles.error}>{ctaError}</Text> : null}
      </View>
    </Section>
  );
}

// ---------------------------------------------------------------------------

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue} numberOfLines={1}>
        {value}
      </Text>
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
  body: { gap: 4 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 12,
  },
  planRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  planName: { color: colors.textPrimary, fontSize: 20, fontWeight: "800" },
  planBadge: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  planBadgeText: {
    color: colors.accent,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1,
  },
  subDetails: { gap: 10 },
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
  rowValueMuted: { color: colors.muted, fontWeight: "500" },
  periodLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.6,
  },
  metric: { gap: 6 },
  metricHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  metricName: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: "700",
    flexShrink: 1,
  },
  overageBadge: {
    color: colors.error,
    fontSize: 12,
    fontWeight: "700",
  },
  track: {
    height: 8,
    borderRadius: 999,
    backgroundColor: colors.cardAlt,
    overflow: "hidden",
  },
  fill: { height: "100%", borderRadius: 999 },
  unlimitedBadge: {
    alignSelf: "flex-start",
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  unlimitedText: {
    color: colors.textSecondary,
    fontSize: 11,
    fontWeight: "600",
    letterSpacing: 0.3,
  },
  metricUsage: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  stack: { gap: 12 },
  hint: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  list: { gap: 10 },
  upgradeButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    paddingHorizontal: 16,
    gap: 12,
  },
  disabled: { opacity: 0.5 },
  upgradeName: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  upgradeCta: { color: colors.accent, fontSize: 15, fontWeight: "700" },
  error: { color: colors.error, fontSize: 13 },
  note: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
});
