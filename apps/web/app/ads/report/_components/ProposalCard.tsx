"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Check, X } from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { formatMinor, formatPercent } from "@/src/features/ads/format";
import { applyProposal, decideProposal, type Proposal, type ProposalStatus } from "./api";

const STATUS_BADGE: Record<ProposalStatus, { label: string; variant: BadgeVariant }> = {
  proposed: { label: "Waiting for approval", variant: "default" },
  approved: { label: "Approved", variant: "secondary" },
  applied: { label: "Applied", variant: "success" },
  rejected: { label: "Rejected", variant: "outline" },
  superseded: { label: "Superseded", variant: "outline" },
  failed: { label: "Apply failed", variant: "destructive" },
};

function toPercentMap(proposal: Proposal): Record<string, string> {
  return Object.fromEntries(proposal.networks.map((n) => [n.network, String(Math.round(n.proposed_share * 1000) / 10)]));
}

/** Today's proposed split with approve / edit / reject. */
export function ProposalCard({ proposal, onChange }: { proposal: Proposal; onChange: (next: Proposal) => void }) {
  const requestOptions = useRequestOptions();
  const [editing, setEditing] = React.useState(false);
  const [shares, setShares] = React.useState<Record<string, string>>(() => toPercentMap(proposal));
  const [busy, setBusy] = React.useState<"" | "approve" | "reject" | "apply">("");
  const [error, setError] = React.useState("");
  const pending = proposal.status === "proposed";
  const badge = STATUS_BADGE[proposal.status];

  React.useEffect(() => setShares(toPercentMap(proposal)), [proposal]);

  const editedTotal = Object.values(shares).reduce((sum, v) => sum + (Number(v) || 0), 0);
  const editValid = Math.abs(editedTotal - 100) < 0.6 && Object.values(shares).every((v) => Number(v) >= 0);

  async function decide(decision: "approve" | "reject") {
    setBusy(decision);
    setError("");
    try {
      const split =
        decision === "approve" && editing
          ? Object.fromEntries(Object.entries(shares).map(([k, v]) => [k, (Number(v) || 0) / 100]))
          : undefined;
      onChange(await decideProposal(proposal.id, { decision, split }, await requestOptions()));
      setEditing(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  async function applyNow() {
    setBusy("apply");
    setError("");
    try {
      onChange(await applyProposal(proposal.id, await requestOptions()));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">Budget split for {proposal.run_date}</CardTitle>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
        <CardDescription>
          {formatMinor(proposal.total_daily_minor, proposal.currency)} per day across {proposal.networks.length}{" "}
          network{proposal.networks.length === 1 ? "" : "s"}. {proposal.reason}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="space-y-3">
          {proposal.networks.map((n) => (
            <li key={n.network} className="rounded-md border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="font-medium">
                  {n.label}
                  {n.source === "manual" ? <span className="ml-2 text-xs text-muted-foreground">(move by hand)</span> : null}
                </span>
                <span className="flex items-center gap-2 tabular-nums">
                  {formatPercent(n.current_share, 0)}
                  <ArrowRight className="h-3 w-3 text-muted-foreground" aria-label="to" />
                  {editing ? (
                    <span className="flex items-center gap-1">
                      <Input
                        aria-label={`${n.label} share in percent`}
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        className="h-8 w-20"
                        value={shares[n.network] ?? ""}
                        onChange={(e) => setShares((prev) => ({ ...prev, [n.network]: e.target.value }))}
                      />
                      %
                    </span>
                  ) : (
                    <strong>{formatPercent(n.proposed_share, 0)}</strong>
                  )}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {formatMinor(n.current_daily_minor, proposal.currency)} to{" "}
                {formatMinor(n.proposed_daily_minor, proposal.currency)} per day
                {n.p_best !== null ? `. ${formatPercent(n.p_best, 0)} chance of the lowest cost per result` : ""}
              </p>
              {n.warning ? <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">{n.warning}</p> : null}
            </li>
          ))}
        </ul>

        {proposal.apply_result ? (
          <div className="space-y-1 rounded-md bg-secondary/40 p-3 text-xs">
            <p className="font-medium">What happened</p>
            {proposal.apply_result.networks.map((r) => (
              <p key={r.network} className={r.ok ? "" : "text-destructive"}>
                {r.network}: {r.manual ? r.detail : r.ok ? `set to ${formatMinor(r.daily_minor, proposal.currency)} per day` : r.detail}
              </p>
            ))}
          </div>
        ) : null}

        {pending ? (
          <div className="space-y-2">
            {editing && !editValid ? (
              <p className="text-xs text-destructive">Shares add up to {editedTotal.toFixed(1)}%. They must add up to 100%.</p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => decide("approve")} disabled={!!busy || (editing && !editValid)}>
                <Check className="mr-1 h-4 w-4" aria-hidden />
                {busy === "approve" ? "Applying..." : editing ? "Approve edited split" : "Approve and apply"}
              </Button>
              <Button variant="outline" onClick={() => setEditing((v) => !v)} disabled={!!busy}>
                {editing ? "Cancel edit" : "Edit shares"}
              </Button>
              <Button variant="ghost" onClick={() => decide("reject")} disabled={!!busy}>
                <X className="mr-1 h-4 w-4" aria-hidden />
                {busy === "reject" ? "Rejecting..." : "Reject"}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Approving changes live daily budgets on Meta and TikTok. It also appears in{" "}
              <Link href="/approvals" className="underline">
                Approvals
              </Link>
              .
            </p>
          </div>
        ) : null}
        {proposal.status === "approved" ? (
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={applyNow} disabled={!!busy}>
              {busy === "apply" ? "Applying..." : "Apply now"}
            </Button>
            <p className="text-xs text-muted-foreground">
              Approved in Approvals. Menivor applies it within a few minutes, or you can apply it now.
            </p>
          </div>
        ) : null}
        <ErrorText message={error} />
      </CardContent>
    </Card>
  );
}
