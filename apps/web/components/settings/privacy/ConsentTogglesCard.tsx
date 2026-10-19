"use client";

import * as React from "react";
import { AlertCircle, CheckCircle2, Loader2, ShieldCheck } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { ConsentKind } from "@/lib/types";
import { useMyConsents } from "@/lib/use-my-consents";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface ConsentOption {
  kind: ConsentKind;
  label: string;
  description: string;
}

const OPTIONS: readonly ConsentOption[] = [
  {
    kind: "marketing",
    label: "Marketing communications",
    description:
      "Receive product news, tips, and occasional offers by email. You can withdraw this at any time.",
  },
  {
    kind: "ai_disclosure",
    label: "AI content disclosure",
    description:
      "Allow Menivor to label content produced with AI narration and avatars, as required for transparency.",
  },
];

interface ConsentRowProps {
  option: ConsentOption;
  checked: boolean;
  disabled: boolean;
  onToggle: (kind: ConsentKind, granted: boolean) => void;
}

function ConsentRow({ option, checked, disabled, onToggle }: ConsentRowProps) {
  return (
    <label className="flex items-start gap-3 rounded-lg border border-border p-3">
      <input
        type="checkbox"
        className="mt-0.5 size-4 rounded border-input accent-primary"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onToggle(option.kind, e.target.checked)}
      />
      <span>
        <span className="text-sm font-medium">{option.label}</span>
        <span className="block text-xs text-muted-foreground">
          {option.description}
        </span>
      </span>
    </label>
  );
}

/**
 * Consent toggles (GDPR / SOC2 consent capture). Each toggle reflects the CURRENT
 * (newest) decision for a `kind` derived from the caller's append-only consent
 * trail; flipping it appends a new decision (grant or withdrawal) rather than
 * mutating history. Strictly caller-scoped server-side — a decision is always for
 * the signed-in caller. State is updated immutably.
 */
export function ConsentTogglesCard() {
  const { status, current, set, errorMessage } = useMyConsents();
  const [pending, setPending] = React.useState<ConsentKind | null>(null);
  const [saveError, setSaveError] = React.useState("");
  const [savedKind, setSavedKind] = React.useState<ConsentKind | null>(null);

  const handleToggle = React.useCallback(
    (kind: ConsentKind, granted: boolean) => {
      setPending(kind);
      setSaveError("");
      setSavedKind(null);
      void set(kind, granted)
        .then(() => setSavedKind(kind))
        .catch((err) =>
          setSaveError(
            friendlyErrorMessage(err, "Couldn't save your preference. Please try again."),
          ),
        )
        .finally(() => setPending(null));
    },
    [set],
  );

  const loading = status === "loading";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-5 text-primary" aria-hidden />
          Consent &amp; communications
        </CardTitle>
        <CardDescription>
          Control how we contact you and how AI-assisted content is disclosed.
          Every change is recorded with a timestamp for your compliance trail.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Loading your preferences…
          </div>
        ) : status === "error" ? (
          <p
            role="alert"
            className="flex items-center gap-2 text-sm text-destructive"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden />
            {errorMessage}
          </p>
        ) : (
          <div className="space-y-3">
            {OPTIONS.map((option) => (
              <ConsentRow
                key={option.kind}
                option={option}
                checked={current(option.kind) === true}
                disabled={pending !== null}
                onToggle={handleToggle}
              />
            ))}
          </div>
        )}

        {saveError && (
          <p
            role="alert"
            className="flex items-center gap-2 text-sm text-destructive"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden />
            {saveError}
          </p>
        )}
        {savedKind && !saveError && pending === null && (
          <p className="flex items-center gap-2 text-sm text-success">
            <CheckCircle2 className="size-4 shrink-0" aria-hidden />
            Preference saved.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
