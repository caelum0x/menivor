/**
 * Owner/admin-only "Buy team credits" panel for a single workspace. Lists the
 * purchasable credit packs (GET /billing/plans) and the enabled payment
 * providers (GET /billing/providers — Stripe / iyzico / Creem / Polar) and, on
 * tap, starts a hosted checkout for the workspace's SHARED pool via the selected
 * provider — createCheckout carries `workspace_id`, so the backend fulfills the
 * webhook via `CreditRepository.workspace_grant` (idempotent) instead of
 * granting to the buyer personally. The returned `checkout_url` is opened via
 * the shared `openCheckoutUrl` helper (in-app browser, system-browser fallback).
 *
 * Purely a UI affordance: the backend independently authorizes the purchase by
 * the caller's workspace role. This panel owns its own loading + error state and
 * never handles any secret — auth flows through the shared api client as
 * `x-api-key`.
 */

import { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { createCheckout, getProviders, listPlans } from "@/lib/api";
import type { PaymentProvider, Plan } from "@/lib/types";

import {
  externalCheckoutAvailable,
  openCheckoutUrl,
} from "@/components/billing/open-checkout";
import { StoreBillingNotice } from "@/components/billing/StoreBillingNotice";
import { ProviderChips } from "@/components/billing/ProviderChips";
import { defaultProvider, providerHint } from "@/components/billing/providers";
import { describeError } from "@/components/me/errors";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

interface BuyTeamCreditsButtonProps {
  workspaceId: string;
  token: string | undefined;
}

/** Best-effort human label for a pack: name, else a credits-derived fallback. */
function planLabel(plan: Plan): string {
  if (plan.name && plan.name.trim()) return plan.name.trim();
  if (typeof plan.credits === "number") return `${plan.credits} credits`;
  return plan.plan_key;
}

/** Optional secondary line: "N credits · $price" from whatever the API supplies. */
function planDetail(plan: Plan): string {
  const parts: string[] = [];
  if (typeof plan.credits === "number") parts.push(`${plan.credits} credits`);
  if (plan.price && plan.price.trim()) parts.push(plan.price.trim());
  return parts.join(" · ");
}

/**
 * Store builds cannot sell credits through a hosted checkout (App Store 3.1.1 /
 * Play payments policy); they show the in-app Pro offer instead.
 */
export function BuyTeamCreditsButton(props: BuyTeamCreditsButtonProps) {
  if (!externalCheckoutAvailable()) {
    return <StoreBillingNotice subject="Team credit purchases" />;
  }
  return <BuyTeamCreditsFlow {...props} />;
}

function BuyTeamCreditsFlow({
  workspaceId,
  token,
}: BuyTeamCreditsButtonProps) {
  const plansFetcher = useCallback(() => listPlans({ token }), [token]);
  const { status, data, error, reload } = useResource<Plan[]>(plansFetcher);

  const providersFetcher = useCallback(() => getProviders({ token }), [token]);
  const { data: providersData } = useResource<PaymentProvider[]>(
    providersFetcher,
  );

  const [busyPlanKey, setBusyPlanKey] = useState<string | null>(null);
  const [buyError, setBuyError] = useState<string | null>(null);
  const [provider, setProvider] = useState<PaymentProvider | string | null>(
    null,
  );

  const plans = data ?? [];
  const providers = providersData ?? [];

  // Pre-select a provider once the enabled set loads (prefer Stripe). Keyed on
  // the stable resource reference (not the per-render array), never clobbers an
  // explicit choice that is still enabled, and re-picks if the set changes.
  useEffect(() => {
    const enabled = providersData ?? [];
    setProvider((current) =>
      current && enabled.includes(current as PaymentProvider)
        ? current
        : defaultProvider(enabled),
    );
  }, [providersData]);

  const onBuy = useCallback(
    async (plan: Plan) => {
      if (!provider) {
        setBuyError("No payment method is available right now.");
        return;
      }
      setBusyPlanKey(plan.plan_key);
      setBuyError(null);
      try {
        const result = await createCheckout(
          {
            plan_key: plan.plan_key,
            provider: provider as PaymentProvider,
            workspace_id: workspaceId,
          },
          { token },
        );
        if (!result.checkout_url) {
          throw new Error("The checkout URL was missing from the response.");
        }
        await openCheckoutUrl(result.checkout_url);
      } catch (err) {
        setBuyError(describeError(err, "Couldn't start checkout."));
      } finally {
        setBusyPlanKey(null);
      }
    },
    [workspaceId, token, provider],
  );

  return (
    <Section title="BUY TEAM CREDITS">
      <SectionState status={status} error={error} onRetry={reload}>
        <View style={styles.stack}>
          <Text style={styles.hint}>
            Purchase a credit pack for this workspace&apos;s shared pool. Credits
            are added to the team pool, not your personal balance.
          </Text>

          {providers.length > 0 ? (
            <View style={styles.providerBlock}>
              <Text style={styles.providerLabel}>Payment method</Text>
              <ProviderChips
                providers={providers}
                selected={provider}
                onSelect={setProvider}
                disabled={busyPlanKey !== null}
              />
              {provider ? (
                <Text style={styles.hint}>{providerHint(provider)}</Text>
              ) : null}
            </View>
          ) : null}

          {plans.length === 0 ? (
            <Text style={styles.hint}>No credit packs are available.</Text>
          ) : (
            <View style={styles.list}>
              {plans.map((plan) => {
                const busy = busyPlanKey === plan.plan_key;
                const disabled = busyPlanKey !== null || !provider;
                const detail = planDetail(plan);
                return (
                  <Pressable
                    key={plan.plan_key}
                    style={[styles.packButton, disabled && styles.disabled]}
                    onPress={() => void onBuy(plan)}
                    disabled={disabled}
                    accessibilityRole="button"
                    accessibilityLabel={`Buy ${planLabel(plan)} for the team`}
                    accessibilityState={{ disabled, busy }}
                  >
                    <View style={styles.packText}>
                      <Text style={styles.packName}>{planLabel(plan)}</Text>
                      {detail ? (
                        <Text style={styles.packDetail}>{detail}</Text>
                      ) : null}
                    </View>
                    <Text style={styles.packCta}>
                      {busy ? "Opening…" : "Buy"}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          )}

          {buyError ? <Text style={styles.error}>{buyError}</Text> : null}
        </View>
      </SectionState>
    </Section>
  );
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  hint: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  providerBlock: { gap: 8 },
  providerLabel: {
    color: colors.textSecondary,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
  list: { gap: 10 },
  packButton: {
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
  packText: { flex: 1, gap: 2 },
  packName: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  packDetail: { color: colors.muted, fontSize: 13 },
  packCta: { color: colors.accent, fontSize: 15, fontWeight: "700" },
  error: { color: colors.error, fontSize: 13 },
});
