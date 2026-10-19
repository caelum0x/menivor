"use client";

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  TicketCheck,
} from "lucide-react";
import { ApiError, redeemReferral } from "@/lib/api";
import type { RedeemResult } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface RedeemFormProps {
  /**
   * Called after a code is successfully redeemed so the parent can refresh the
   * credit balance. Receives the backend redeem result.
   */
  readonly onRedeemed: (result: RedeemResult) => void;
}

type SubmitState = "idle" | "submitting" | "success" | "error";

/**
 * Form to redeem another user's referral code via POST /me/referral/redeem.
 * Surfaces submitting, success, and error states, and notifies the parent on
 * success so credits can be refreshed.
 */
export function RedeemForm({ onRedeemed }: RedeemFormProps) {
  const getToken = useApiToken();
  const [code, setCode] = React.useState("");
  const [state, setState] = React.useState<SubmitState>("idle");
  const [message, setMessage] = React.useState<string>("");
  const [granted, setGranted] = React.useState<number | null>(null);

  const onSubmit = React.useCallback(
    async (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const trimmed = code.trim();
      if (!trimmed) {
        setState("error");
        setMessage("Enter a referral code to redeem.");
        return;
      }

      setState("submitting");
      setMessage("");
      setGranted(null);
      try {
        const token = await getToken();
        const result = await redeemReferral(trimmed, { token });
        if (!result.ok) {
          setState("error");
          setMessage(
            result.message || result.error || "That code couldn't be redeemed.",
          );
          return;
        }
        setState("success");
        setGranted(
          typeof result.referee_grant === "number"
            ? result.referee_grant
            : null,
        );
        setMessage(
          result.message ||
            (typeof result.referee_balance === "number"
              ? `New balance: ${result.referee_balance} credits.`
              : "Referral code redeemed."),
        );
        setCode("");
        onRedeemed(result);
      } catch (err) {
        const text =
          friendlyErrorMessage(err, "Something went wrong redeeming the code.");
        setState("error");
        setMessage(text);
      }
    },
    [code, getToken, onRedeemed],
  );

  const submitting = state === "submitting";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TicketCheck className="size-5 text-primary" aria-hidden />
          Redeem a code
        </CardTitle>
        <CardDescription>
          Got a code from a friend? Redeem it to add bonus credits to your
          account.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <form onSubmit={(e) => void onSubmit(e)} className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="redeem-code">Referral code</Label>
            <div className="flex items-center gap-2">
              <Input
                id="redeem-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="e.g. REELXY42"
                autoComplete="off"
                spellCheck={false}
                disabled={submitting}
                className="font-mono uppercase tracking-wide"
                aria-invalid={state === "error"}
              />
              <Button type="submit" disabled={submitting || !code.trim()}>
                {submitting ? (
                  <>
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                    Redeeming
                  </>
                ) : (
                  "Redeem"
                )}
              </Button>
            </div>
          </div>
        </form>

        {state === "success" && (
          <StatusNote tone="success">
            <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              {granted !== null && granted > 0
                ? `Redeemed! +${granted} credit${granted === 1 ? "" : "s"} added. `
                : "Redeemed! "}
              {message}
            </span>
          </StatusNote>
        )}

        {state === "error" && (
          <StatusNote tone="error">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>{message}</span>
          </StatusNote>
        )}
      </CardContent>
    </Card>
  );
}

function StatusNote({
  tone,
  children,
}: Readonly<{ tone: "success" | "error"; children: React.ReactNode }>) {
  const styles =
    tone === "success"
      ? "border-success/40 bg-success/5 text-success"
      : "border-destructive/40 bg-destructive/5 text-destructive";
  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex items-start gap-2 rounded-md border p-3 text-sm ${styles}`}
    >
      {children}
    </div>
  );
}
