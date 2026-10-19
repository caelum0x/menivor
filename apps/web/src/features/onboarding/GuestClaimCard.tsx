"use client";

import * as React from "react";
import { ArrowRightLeft, CheckCircle2, Info, Loader2, X } from "lucide-react";
import type { Me } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  claimGuestAccount,
  getGuestSnapshot,
  hasUnclaimedGuestSession,
  markGuestSessionSettled,
  type GuestClaimOutcome,
} from "./guest-claim";

type CardState =
  | { readonly phase: "checking" }
  | { readonly phase: "hidden" }
  | { readonly phase: "offer"; readonly guest: Me }
  | { readonly phase: "claiming"; readonly guest: Me }
  | { readonly phase: "done"; readonly outcome: GuestClaimOutcome; readonly guest: Me };

interface GuestClaimCardProps {
  /** Called after a successful claim so the host can reload balances. */
  readonly onClaimed?: () => void;
}

/**
 * Offers to move reels + credits made as a browser guest into the signed-in
 * account. Renders nothing when this browser has no guest session, when the
 * guest account is empty, or once the user has claimed/dismissed it.
 */
export function GuestClaimCard({ onClaimed }: GuestClaimCardProps) {
  const getToken = useApiToken();
  const [state, setState] = React.useState<CardState>({ phase: "checking" });

  React.useEffect(() => {
    let active = true;
    if (!hasUnclaimedGuestSession()) {
      setState({ phase: "hidden" });
      return;
    }
    void getGuestSnapshot().then((guest) => {
      if (!active) return;
      const worthClaiming =
        guest !== null && (guest.jobs_count > 0 || guest.credits > 0);
      setState(worthClaiming ? { phase: "offer", guest } : { phase: "hidden" });
    });
    return () => {
      active = false;
    };
  }, []);

  const claim = React.useCallback(async () => {
    if (state.phase !== "offer") return;
    const guest = state.guest;
    setState({ phase: "claiming", guest });
    const token = await getToken();
    const outcome = await claimGuestAccount(token);
    setState({ phase: "done", outcome, guest });
    if (outcome.kind === "claimed") onClaimed?.();
  }, [getToken, onClaimed, state]);

  const dismiss = React.useCallback(() => {
    markGuestSessionSettled();
    setState({ phase: "hidden" });
  }, []);

  if (state.phase === "checking" || state.phase === "hidden") return null;

  const { guest } = state;
  const summary = `${guest.jobs_count} reel${guest.jobs_count === 1 ? "" : "s"} and ${guest.credits} credit${guest.credits === 1 ? "" : "s"}`;

  if (state.phase === "done") {
    const { outcome } = state;
    return (
      <Card className={outcome.kind === "claimed" ? "border-success/40" : ""}>
        <CardContent className="flex items-start gap-3 p-5">
          {outcome.kind === "claimed" ? (
            <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-hidden />
          ) : (
            <Info className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden />
          )}
          <div className="flex-1 text-sm">
            {outcome.kind === "claimed" && (
              <p>
                Moved {outcome.result.moved_jobs} reel
                {outcome.result.moved_jobs === 1 ? "" : "s"} and{" "}
                {outcome.result.moved_credits} credit
                {outcome.result.moved_credits === 1 ? "" : "s"} into your
                account.
              </p>
            )}
            {outcome.kind === "unsupported" && (
              <p className="text-muted-foreground">
                Moving guest work into an account isn&apos;t available on this
                server yet. Your guest {summary} stay saved in this browser —
                sign out to keep using them.
              </p>
            )}
            {outcome.kind === "error" && (
              <p className="text-destructive" role="alert">
                {outcome.message}
              </p>
            )}
          </div>
          {outcome.kind !== "claimed" && (
            <Button variant="ghost" size="sm" onClick={dismiss} aria-label="Dismiss">
              <X className="size-4" aria-hidden />
            </Button>
          )}
        </CardContent>
      </Card>
    );
  }

  const busy = state.phase === "claiming";
  return (
    <Card className="border-primary/40 bg-primary/5">
      <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <ArrowRightLeft className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
          <div>
            <p className="font-medium">Keep what you made as a guest</p>
            <p className="text-sm text-muted-foreground">
              This browser has {summary} from before you signed in. Move them
              into your account so they follow you to every device.
            </p>
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button size="sm" onClick={() => void claim()} disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {busy ? "Moving…" : "Move to my account"}
          </Button>
          <Button size="sm" variant="ghost" onClick={dismiss} disabled={busy}>
            Keep separate
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
