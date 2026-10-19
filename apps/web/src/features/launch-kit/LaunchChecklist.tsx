"use client";

/** Section 4: the 10-step distribution playbook checklist, persisted per product. */

import * as React from "react";
import { Check } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { getLaunchChecklist, markPlaybookStep, type LaunchChecklist as LaunchChecklistData } from "./api";
import { checklistProgressLabel } from "./view-model";

interface Props {
  readonly productName: string;
}

export function LaunchChecklist({ productName }: Props) {
  const getApiToken = useApiToken();
  const [checklist, setChecklist] = React.useState<LaunchChecklistData | null>(null);
  const [error, setError] = React.useState("");
  const [busyKey, setBusyKey] = React.useState("");

  const load = React.useCallback(async () => {
    if (!productName.trim()) {
      setChecklist(null);
      return;
    }
    setError("");
    try {
      const token = await getApiToken();
      setChecklist(await getLaunchChecklist(productName, { token }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "The checklist could not be loaded."));
    }
  }, [getApiToken, productName]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (stepKey: string, done: boolean) => {
    if (!productName.trim()) return;
    setBusyKey(stepKey);
    try {
      const token = await getApiToken();
      await markPlaybookStep({ productName, stepKey, status: done ? "pending" : "done" }, { token });
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "That step could not be saved."));
    } finally {
      setBusyKey("");
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle>10-step launch checklist</CardTitle>
        {checklist ? (
          <span className="text-sm text-muted-foreground" data-testid="checklist-progress">
            {checklistProgressLabel(checklist.done, checklist.total)}
          </span>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3">
        {!productName.trim() ? (
          <p className="text-sm text-muted-foreground">Enter a product name above to see its checklist.</p>
        ) : !checklist ? (
          <Skeleton className="h-40 w-full" aria-busy />
        ) : (
          <ul className="divide-y divide-border">
            {checklist.steps.map((step) => {
              const done = step.status === "done";
              return (
                <li key={step.key} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
                  <button
                    type="button"
                    aria-label={`${step.title}: ${done ? "done" : "pending"}`}
                    disabled={busyKey === step.key}
                    onClick={() => void toggle(step.key, done)}
                    className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded border ${
                      done ? "border-success bg-success/20 text-success" : "border-white/20"
                    } disabled:opacity-50`}
                  >
                    {done ? <Check className="size-3.5" aria-hidden /> : null}
                  </button>
                  <div>
                    <p className={`font-medium ${done ? "line-through text-muted-foreground" : ""}`}>{step.title}</p>
                    <p className="text-sm text-muted-foreground">{step.detail}</p>
                    {step.note ? <p className="text-xs text-muted-foreground">{step.note}</p> : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      </CardContent>
    </Card>
  );
}
