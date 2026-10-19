"use client";

import * as React from "react";
import { useClerk } from "@/components/auth/clerk-safe";
import { AlertCircle, AlertTriangle, Loader2, Trash2 } from "lucide-react";
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
import { useAccountErasure } from "@/lib/use-account-erasure";

/** The exact phrase the user must type to arm the irreversible action. */
const CONFIRM_PHRASE = "DELETE";

/**
 * "Delete my account" (GDPR Art. 17, right to erasure) — a deliberately
 * multi-step, destructive control. The user must first reveal the confirmation
 * panel, then type an exact phrase before the action arms. Erasure ANONYMIZES
 * the caller's OWN PII in place (financial/audit records are preserved) and is
 * IRREVERSIBLE. The server only ever erases the resolved caller — this control
 * can never target another account. On success the caller is signed out.
 */
export function DeleteAccountCard() {
  const { status, errorMessage, erase } = useAccountErasure();
  const { signOut } = useClerk();
  const [confirming, setConfirming] = React.useState(false);
  const [phrase, setPhrase] = React.useState("");

  const busy = status === "erasing";
  const armed = phrase.trim() === CONFIRM_PHRASE;
  const done = status === "done";

  const handleErase = React.useCallback(async () => {
    if (!armed || busy) return;
    try {
      await erase();
      // Account is now anonymized — end the session and return to the door.
      await signOut({ redirectUrl: "/" });
    } catch {
      // Error surfaced via the hook's `errorMessage`; the session is kept.
    }
  }, [armed, busy, erase, signOut]);

  if (done) {
    return (
      <Card className="border-destructive/40">
        <CardContent className="py-8 text-center">
          <p className="text-sm font-medium">Your account has been erased.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Signing you out…
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-destructive">
          <AlertTriangle className="size-5" aria-hidden />
          Delete my account
        </CardTitle>
        <CardDescription>
          Permanently anonymize your personal data. Your name, email, and handle
          are replaced with a tombstone and your credentials are revoked. This
          <strong> cannot be undone.</strong> Financial and audit records are
          retained only as required by law.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!confirming ? (
          <Button
            variant="outline"
            className="border-destructive/50 text-destructive hover:bg-destructive/10"
            onClick={() => setConfirming(true)}
          >
            <Trash2 aria-hidden /> Delete my account…
          </Button>
        ) : (
          <div className="space-y-4 rounded-lg border border-destructive/40 bg-destructive/5 p-4">
            <div className="space-y-2">
              <Label htmlFor="erase-confirm">
                Type <span className="font-mono font-semibold">{CONFIRM_PHRASE}</span>{" "}
                to confirm
              </Label>
              <Input
                id="erase-confirm"
                value={phrase}
                autoComplete="off"
                spellCheck={false}
                disabled={busy}
                placeholder={CONFIRM_PHRASE}
                onChange={(e) => setPhrase(e.target.value)}
              />
            </div>

            {status === "error" && (
              <p
                role="alert"
                className="flex items-center gap-2 text-sm text-destructive"
              >
                <AlertCircle className="size-4 shrink-0" aria-hidden />
                {errorMessage}
              </p>
            )}

            <div className="flex flex-wrap gap-2">
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
                  <>
                    <Trash2 aria-hidden /> Permanently delete my account
                  </>
                )}
              </Button>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setConfirming(false);
                  setPhrase("");
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
