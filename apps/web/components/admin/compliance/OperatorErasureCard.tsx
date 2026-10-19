"use client";

import * as React from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
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
import type { ErasureRequest } from "@/lib/types";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface OperatorErasureCardProps {
  /** Runs the staff-only erasure of the target user; audited with the operator. */
  onErase: (userId: string) => Promise<ErasureRequest>;
}

type Phase =
  | { status: "idle" }
  | { status: "erasing" }
  | { status: "done"; userId: string }
  | { status: "error"; message: string };

/** The exact phrase the operator must type to arm the irreversible action. */
const CONFIRM_PHRASE = "ERASE";

/**
 * Operator-initiated erasure (platform-admin only). An operator enters a TARGET
 * user id and types an exact phrase to arm the irreversible action; the server
 * re-enforces the `is_staff` gate and audits the erasure with THIS operator as
 * actor. Anonymizes the target's PII in place while preserving financial/audit
 * records. Careful, deliberate UX for a destructive cross-tenant action.
 */
export function OperatorErasureCard({ onErase }: OperatorErasureCardProps) {
  const [userId, setUserId] = React.useState("");
  const [phrase, setPhrase] = React.useState("");
  const [phase, setPhase] = React.useState<Phase>({ status: "idle" });

  const busy = phase.status === "erasing";
  const armed = userId.trim() !== "" && phrase.trim() === CONFIRM_PHRASE;

  const handleErase = React.useCallback(async () => {
    const target = userId.trim();
    if (!target || phrase.trim() !== CONFIRM_PHRASE || busy) return;
    setPhase({ status: "erasing" });
    try {
      await onErase(target);
      setPhase({ status: "done", userId: target });
      setUserId("");
      setPhrase("");
    } catch (err) {
      setPhase({
        status: "error",
        message:
          friendlyErrorMessage(err, "Couldn't erase the target user. Please try again."),
      });
    }
  }, [busy, onErase, phrase, userId]);

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-destructive">
          <AlertTriangle className="size-5" aria-hidden />
          Erase a user
        </CardTitle>
        <CardDescription>
          Permanently anonymize a target user&apos;s personal data on their behalf
          (e.g. an out-of-band erasure request). This is irreversible and audited
          with you as the actor. Financial and audit records are retained.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="erase-user-id">Target user id</Label>
          <Input
            id="erase-user-id"
            value={userId}
            autoComplete="off"
            spellCheck={false}
            disabled={busy}
            placeholder="user_..."
            className="font-mono text-xs"
            onChange={(e) => setUserId(e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="erase-phrase">
            Type <span className="font-mono font-semibold">{CONFIRM_PHRASE}</span>{" "}
            to confirm
          </Label>
          <Input
            id="erase-phrase"
            value={phrase}
            autoComplete="off"
            spellCheck={false}
            disabled={busy}
            placeholder={CONFIRM_PHRASE}
            onChange={(e) => setPhrase(e.target.value)}
          />
        </div>

        {phase.status === "error" && (
          <p
            role="alert"
            className="flex items-center gap-2 text-sm text-destructive"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden />
            {phase.message}
          </p>
        )}
        {phase.status === "done" && (
          <p className="flex items-center gap-2 text-sm text-success">
            <CheckCircle2 className="size-4 shrink-0" aria-hidden />
            User <span className="font-mono">{phase.userId}</span> has been erased.
          </p>
        )}

        <Button
          variant="destructive"
          disabled={!armed || busy}
          onClick={() => void handleErase()}
        >
          {busy ? (
            <>
              <Loader2 className="animate-spin" aria-hidden /> Erasing…
            </>
          ) : (
            "Erase user"
          )}
        </Button>
      </CardContent>
    </Card>
  );
}
