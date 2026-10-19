"use client";

import * as React from "react";
import { Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { signUpHref } from "@/lib/auth-redirect";
import { cn } from "@/lib/utils";
import {
  changePlan,
  formatUsd,
  pickPlan,
  planErrorMessage,
  savingsVsPacks,
  startPlanCheckout,
  type MonthlyCatalog,
  type MonthlyPlan,
  type MyPlan,
  type PlanInterval,
} from "./api";
import { usePlans } from "./use-plans";

export type UpsellReason = "after_reel" | "low_credits" | "out_of_credits";

/** The after-reel pitch waits until the user has this many finished reels. */
export const UPSELL_AFTER_REELS = 3;
/** A dismissed after-reel pitch stays hidden this long. */
export const UPSELL_SNOOZE_MS = 14 * 24 * 60 * 60 * 1000;
const DISMISS_KEY = "menivor.plan-upsell.after-reel.dismissed-at";

/** Pure: is a dismissal stored at `raw` still in effect at `now`? */
export function isSnoozed(raw: string | null, now: number): boolean {
  const at = raw ? Number(raw) : NaN;
  return Number.isFinite(at) && now - at < UPSELL_SNOOZE_MS;
}

function readSnoozed(): boolean {
  try {
    return isSnoozed(window.localStorage.getItem(DISMISS_KEY), Date.now());
  } catch {
    return false;
  }
}

function writeSnoozed(): void {
  try {
    window.localStorage.setItem(DISMISS_KEY, String(Date.now()));
  } catch {
    // Storage blocked: the dismissal still holds for this page view.
  }
}

const HEADLINES: Record<UpsellReason, string> = {
  after_reel: "Keep making reels every month, for less per reel.",
  low_credits: "You are almost out of reels.",
  out_of_credits: "Not enough reels left. Keep going with a monthly plan.",
};

/** Pure: what the upsell should offer, or `null` to render nothing. */
export function upsellOffer(
  catalog: MonthlyCatalog,
  mine: MyPlan | null | undefined,
  reason: UpsellReason,
): { readonly kind: "subscribe" | "upgrade"; readonly plan: MonthlyPlan } | null {
  const current = mine?.plan ?? null;
  if (current) {
    // Subscribers only see an upgrade when they are running low.
    if (reason === "after_reel" || !mine?.recommended_plan) return null;
    const next = catalog.plans.find((p) => p.plan_key === mine.recommended_plan);
    return next && next.available[current.interval] ? { kind: "upgrade", plan: next } : null;
  }
  if (reason === "low_credits" && mine && !mine.low_credits) return null;
  // After a reel: only once the user has real finished reels to show for it.
  if (reason === "after_reel" && (mine?.reels_rendered ?? 0) < UPSELL_AFTER_REELS) return null;
  const plan = pickPlan(catalog, mine?.recommended_plan);
  return plan.available.month ? { kind: "subscribe", plan } : null;
}

/**
 * One-click monthly-plan upsell for the moments it helps: right after a
 * finished reel, when credits run low, and on "not enough credits". Shows the
 * exact price, the per-reel saving over packs and the renewal terms; renders
 * nothing when no plan is on sale.
 */
export function PlanUpsell({
  reason,
  className,
  refreshKey,
  fallback = null,
}: Readonly<{
  reason: UpsellReason;
  className?: string;
  /** Change it (e.g. the number of finished reels) to re-read the user's counts. */
  refreshKey?: number;
  /** Rendered instead when there is no plan to pitch, so a screen keeps one action. */
  fallback?: React.ReactNode;
}>) {
  const { catalog, mine, signedIn, getToken, setMine, refresh } = usePlans();
  const [busy, setBusy] = React.useState<PlanInterval | "upgrade" | null>(null);
  const [error, setError] = React.useState("");
  const dismissible = reason === "after_reel";
  const [dismissed, setDismissed] = React.useState(false);

  React.useEffect(() => {
    if (dismissible) setDismissed(readSnoozed());
  }, [dismissible]);

  const firstRefresh = React.useRef(true);
  React.useEffect(() => {
    if (firstRefresh.current) {
      firstRefresh.current = false;
      return;
    }
    refresh();
  }, [refreshKey, refresh]);

  const offer = dismissed ? null : upsellOffer(catalog, mine, reason);
  if (!offer) return <>{fallback}</>;
  const oneAction = reason === "after_reel";

  const dismiss = () => {
    writeSnoozed();
    setDismissed(true);
  };
  const { plan } = offer;

  const subscribe = async (interval: PlanInterval) => {
    setError("");
    if (!signedIn) {
      window.location.assign(signUpHref("/pricing"));
      return;
    }
    setBusy(interval);
    try {
      const token = await getToken();
      const { checkout_url: url } = await startPlanCheckout(plan.plan_key, interval, { token });
      window.location.assign(url);
    } catch (err) {
      setError(planErrorMessage(err));
      setBusy(null);
    }
  };

  const upgrade = async () => {
    setError("");
    setBusy("upgrade");
    try {
      const token = await getToken();
      setMine(await changePlan(plan.plan_key, { token }));
    } catch (err) {
      setError(planErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const saving = savingsVsPacks(plan, "month", catalog.best_pack_per_reel_cents);
  const monthly = formatUsd(plan.monthly_cents);

  return (
    <div
      className={cn(
        "relative flex flex-col gap-3 rounded-lg border border-primary/40 bg-primary/5 p-4",
        dismissible && "pr-10",
        className,
      )}
      data-testid="plan-upsell"
    >
      {dismissible ? (
        <button
          type="button"
          onClick={dismiss}
          aria-label="Not now"
          className="absolute right-2 top-2 rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <X className="size-4" aria-hidden />
        </button>
      ) : null}
      <div className="space-y-1">
        <p className="text-sm font-medium">
          {offer.kind === "upgrade"
            ? `Need more reels? ${plan.name} gives you ${plan.monthly_reels} a month.`
            : reason === "after_reel" && mine?.reels_rendered
              ? `You have made ${mine.reels_rendered} reels. ${HEADLINES.after_reel}`
              : HEADLINES[reason]}
        </p>
        <p className="text-sm text-muted-foreground">
          {plan.name}: {plan.monthly_reels} reels every month for {monthly}/month,{" "}
          {formatUsd(plan.per_reel_cents.month)} per reel
          {saving > 0 ? `, ${saving}% less than credit packs` : ""}.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {offer.kind === "upgrade" ? (
          <Button type="button" size="sm" disabled={busy !== null} onClick={() => void upgrade()}>
            {busy === "upgrade" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
            Upgrade to {plan.name}, {monthly}/month
          </Button>
        ) : (
          <>
            <Button type="button" size="sm" disabled={busy !== null} onClick={() => void subscribe("month")}>
              {busy === "month" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
              Start {plan.name}, {monthly}/month
            </Button>
            {plan.available.year && !oneAction ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy !== null}
                onClick={() => void subscribe("year")}
              >
                {busy === "year" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
                Yearly {formatUsd(plan.yearly_cents)} (2 months free)
              </Button>
            ) : null}
          </>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {offer.kind === "upgrade"
          ? "The price difference for this period is charged now and the extra reels are added right away. Same renewal date."
          : "Renews automatically until you cancel. Cancel in one click from Billing and keep your reels until the period ends. Included reels do not roll over; credit packs never expire."}
      </p>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
