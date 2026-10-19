"use client";

import * as React from "react";
import { AlertCircle, CheckCircle2, Clock, Loader2 } from "lucide-react";
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
import { ApiError } from "@/lib/api";
import type { RetentionPolicy, RetentionUpdateRequest } from "@/lib/types";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface RetentionPolicyFormProps {
  /** The workspace's current policy, or `null` while none is configured. */
  policy: RetentionPolicy | null;
  canManage: boolean;
  onSave: (body: RetentionUpdateRequest) => Promise<RetentionPolicy>;
}

type Phase =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved" }
  | { status: "error"; message: string };

/** A blank field means "keep forever" (null); otherwise a non-negative integer. */
function parseDays(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const value = Number.parseInt(trimmed, 10);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function daysToField(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/**
 * Configure a workspace's data-RETENTION window (GDPR retention). Each field
 * bounds how long the workspace's jobs / assets are kept before the periodic
 * sweep anonymizes the aged rows; a BLANK field means keep-forever (`null`).
 * Controls are gated on `workspace.settings` (the server re-enforces it and
 * scopes the write to this workspace alone). All form state is controlled and
 * updated immutably; it reseeds whenever the loaded policy changes.
 */
export function RetentionPolicyForm({
  policy,
  canManage,
  onSave,
}: RetentionPolicyFormProps) {
  const [jobsDays, setJobsDays] = React.useState(
    daysToField(policy?.jobs_retention_days),
  );
  const [assetsDays, setAssetsDays] = React.useState(
    daysToField(policy?.assets_retention_days),
  );
  const [phase, setPhase] = React.useState<Phase>({ status: "idle" });

  const policyKey = policy
    ? `${policy.workspace_id}:${policy.updated_at ?? ""}`
    : "none";
  React.useEffect(() => {
    setJobsDays(daysToField(policy?.jobs_retention_days));
    setAssetsDays(daysToField(policy?.assets_retention_days));
    setPhase({ status: "idle" });
  }, [policyKey, policy]);

  const busy = phase.status === "saving";

  const handleSubmit = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canManage || busy) return;

      const body: RetentionUpdateRequest = {
        jobs_retention_days: parseDays(jobsDays),
        assets_retention_days: parseDays(assetsDays),
      };

      setPhase({ status: "saving" });
      try {
        await onSave(body);
        setPhase({ status: "saved" });
      } catch (err) {
        setPhase({
          status: "error",
          message:
            friendlyErrorMessage(err, "Couldn't save the retention policy. Please try again."),
        });
      }
    },
    [assetsDays, busy, canManage, jobsDays, onSave],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clock className="size-5 text-primary" aria-hidden />
          Data retention
        </CardTitle>
        <CardDescription>
          Automatically anonymize this workspace&apos;s jobs and assets after a
          set number of days. Leave a field blank to keep that data forever.
          Financial and audit records are always retained as required by law.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-5">
          <fieldset disabled={!canManage || busy} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="retention-jobs">Jobs retention (days)</Label>
              <Input
                id="retention-jobs"
                type="number"
                min={0}
                inputMode="numeric"
                value={jobsDays}
                placeholder="Keep forever"
                onChange={(e) => setJobsDays(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Jobs (and their scripts/prompts) older than this are anonymized
                by the periodic sweep. Blank = keep forever.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="retention-assets">Assets retention (days)</Label>
              <Input
                id="retention-assets"
                type="number"
                min={0}
                inputMode="numeric"
                value={assetsDays}
                placeholder="Keep forever"
                onChange={(e) => setAssetsDays(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Rendered assets older than this are purged by the sweep. Blank =
                keep forever.
              </p>
            </div>
          </fieldset>

          {phase.status === "error" && (
            <p
              role="alert"
              className="flex items-center gap-2 text-sm text-destructive"
            >
              <AlertCircle className="size-4 shrink-0" aria-hidden />
              {phase.message}
            </p>
          )}
          {phase.status === "saved" && (
            <p className="flex items-center gap-2 text-sm text-success">
              <CheckCircle2 className="size-4 shrink-0" aria-hidden />
              Retention policy saved.
            </p>
          )}

          {canManage && (
            <Button type="submit" disabled={busy}>
              {busy ? (
                <>
                  <Loader2 className="animate-spin" aria-hidden /> Saving…
                </>
              ) : (
                "Save retention policy"
              )}
            </Button>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
