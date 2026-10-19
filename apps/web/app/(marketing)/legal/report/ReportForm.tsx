"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { API_BASE } from "@/src/shared/api/base";

/** Mirrors `REASONS` in apps/api/app/domains/compliance/takedown.py. */
export const REPORT_REASONS = [
  { value: "impersonation", label: "It impersonates me or someone else" },
  { value: "copyright", label: "It uses my work without permission" },
  { value: "privacy", label: "It shows private information" },
  { value: "harmful", label: "It is hateful, violent or harmful" },
  { value: "sexual", label: "It is sexual content" },
  { value: "other", label: "Something else" },
] as const;

type Phase =
  | { status: "idle" }
  | { status: "sending" }
  | { status: "sent"; ticketId: string }
  | { status: "error"; message: string };

export function ReportForm() {
  const [content, setContent] = React.useState("");
  const [reason, setReason] = React.useState<string>(REPORT_REASONS[0].value);
  const [details, setDetails] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [phase, setPhase] = React.useState<Phase>({ status: "idle" });

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPhase({ status: "sending" });
    try {
      const response = await fetch(`${API_BASE}/legal/reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, reason, details, email }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        data?: { ticket_id?: string };
        message?: string;
      };
      if (!response.ok) {
        const message =
          response.status === 429
            ? "Too many reports from here. Try again in an hour."
            : String(payload.message || "We could not send the report. Try again.")
                .replace(/^[^:]*:\s*/, "");
        setPhase({ status: "error", message });
        return;
      }
      setPhase({ status: "sent", ticketId: String(payload.data?.ticket_id || "") });
    } catch {
      setPhase({ status: "error", message: "We could not send the report. Try again." });
    }
  };

  if (phase.status === "sent") {
    return (
      <div role="status" className="rounded-lg border border-border p-6">
        <p className="font-medium">Report received</p>
        <p className="mt-2 text-sm text-muted-foreground">
          Your ticket is <span className="font-mono">{phase.ticketId}</span>. We
          will reply to {email}. Quote the ticket if you write to us about it.
        </p>
      </div>
    );
  }

  const sending = phase.status === "sending";
  return (
    <form onSubmit={submit} className="space-y-5">
      <div className="space-y-2">
        <Label htmlFor="report-content">Link or id of the video</Label>
        <Input
          id="report-content"
          required
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="https://menivor.com/r/..."
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="report-reason">What is wrong</Label>
        <Select id="report-reason" value={reason} onChange={(e) => setReason(e.target.value)}>
          {REPORT_REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </Select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="report-details">Details (optional)</Label>
        <Textarea
          id="report-details"
          value={details}
          maxLength={4000}
          onChange={(e) => setDetails(e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="report-email">Your email</Label>
        <Input
          id="report-email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      {phase.status === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          {phase.message}
        </p>
      ) : null}
      <Button type="submit" disabled={sending}>
        {sending ? "Sending..." : "Send report"}
      </Button>
    </form>
  );
}
