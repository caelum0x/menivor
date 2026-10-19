"use client";

import * as React from "react";
import { usePlans } from "@/src/features/plans/use-plans";
import { planErrorMessage, startPlanCheckout } from "@/src/features/plans/api";
import { accessErrorMessage, startPackCheckout } from "@/src/shared/access/api";
import { eventKey, hasShown, isExhausted, markShown } from "./exhaustion";
import { paywallOffers, type PaywallOffers } from "./offer";

export interface PaywallMomentState {
  readonly open: boolean;
  readonly offers: PaywallOffers;
  readonly busy: "pack" | "monthly" | null;
  readonly error: string;
  readonly buyPack: () => Promise<void>;
  readonly buyMonthly: () => Promise<void>;
  readonly dismiss: () => void;
}

/**
 * Opens once per exhaustion event when `ready` (the run is terminal with a
 * finished reel) and the account is out of free reels.
 */
export function usePaywallMoment(jobIds: readonly string[], ready: boolean): PaywallMomentState {
  const { catalog, mine, getToken } = usePlans();
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState<"pack" | "monthly" | null>(null);
  const [error, setError] = React.useState("");
  const decided = React.useRef("");
  const key = eventKey(jobIds);

  React.useEffect(() => {
    if (!ready || jobIds.length === 0 || mine === undefined) return;
    if (decided.current === key) return;
    decided.current = key;
    if (!isExhausted(mine) || hasShown(key)) return;
    markShown(key);
    setOpen(true);
  }, [ready, mine, key, jobIds.length]);

  const offers = React.useMemo(() => paywallOffers(catalog), [catalog]);

  const buyPack = React.useCallback(async () => {
    if (!offers.pack) return;
    setError("");
    setBusy("pack");
    try {
      const token = await getToken();
      const { checkout_url: url } = await startPackCheckout(offers.pack.planKey, { token });
      window.location.assign(url);
    } catch (err) {
      setError(accessErrorMessage(err));
      setBusy(null);
    }
  }, [offers.pack, getToken]);

  const buyMonthly = React.useCallback(async () => {
    if (!offers.monthly) return;
    setError("");
    setBusy("monthly");
    try {
      const token = await getToken();
      const { checkout_url: url } = await startPlanCheckout(offers.monthly.planKey, "month", { token });
      window.location.assign(url);
    } catch (err) {
      setError(planErrorMessage(err));
      setBusy(null);
    }
  }, [offers.monthly, getToken]);

  const dismiss = React.useCallback(() => setOpen(false), []);
  return { open, offers, busy, error, buyPack, buyMonthly, dismiss };
}
