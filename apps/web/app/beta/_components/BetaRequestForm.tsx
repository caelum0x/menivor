"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  BETA_EMAIL_MAX,
  BETA_USE_CASE_MAX,
  checkBetaFields,
  submitBetaRequest,
} from "../_lib/launch";

type FormStatus = "idle" | "submitting" | "received" | "error";

export interface BetaRequestFormProps {
  /** Attribution tag stored with the request, e.g. `landing-hero`. */
  readonly source: string;
  readonly className?: string;
}

/**
 * Private-beta access request: email + what you want to make, posted to
 * POST /beta/request. The success copy is the server's own neutral message
 * (it never reveals whether an address was already on the list), and it says
 * plainly that access is approved by hand, not instantly.
 */
export function BetaRequestForm({ source, className }: BetaRequestFormProps) {
  const [email, setEmail] = React.useState("");
  const [useCase, setUseCase] = React.useState("");
  const [status, setStatus] = React.useState<FormStatus>("idle");
  const [message, setMessage] = React.useState("");
  const fieldId = React.useId();

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (status === "submitting") return;
    const check = checkBetaFields(email, useCase);
    if (!check.ok) {
      setStatus("error");
      setMessage(check.error);
      return;
    }
    setStatus("submitting");
    setMessage("");
    const outcome = await submitBetaRequest(check.email, check.useCase, source);
    if (outcome.status === "received") {
      setStatus("received");
      setMessage(outcome.message);
      setEmail("");
      setUseCase("");
      return;
    }
    setStatus("error");
    setMessage(outcome.message);
  };

  if (status === "received") {
    return (
      <div role="status" className={cn("max-w-xl space-y-2", className)}>
        <p className="text-sm font-medium text-foreground">{message}</p>
        <p className="text-sm text-muted-foreground">
          Approval is manual and not instant. Once approved, sign in with the same email.
        </p>
      </div>
    );
  }

  const submitting = status === "submitting";
  return (
    <form onSubmit={onSubmit} noValidate className={cn("flex w-full max-w-xl flex-col gap-3", className)}>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${fieldId}-email`} className="text-sm font-medium text-foreground">
          Email
        </label>
        <Input
          id={`${fieldId}-email`}
          type="email"
          required
          autoComplete="email"
          maxLength={BETA_EMAIL_MAX}
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={submitting}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${fieldId}-use`} className="text-sm font-medium text-foreground">
          What do you want to make?
        </label>
        <Textarea
          id={`${fieldId}-use`}
          required
          rows={3}
          maxLength={BETA_USE_CASE_MAX}
          placeholder="For example: captioned product demos for our TikTok, 3 a week"
          value={useCase}
          onChange={(e) => setUseCase(e.target.value)}
          disabled={submitting}
        />
      </div>
      {status === "error" && message ? (
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="lg" disabled={submitting}>
          {submitting ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
          Request early access
        </Button>
        <Link href="/sign-in" className="text-sm text-muted-foreground underline underline-offset-4">
          Already approved? Sign in
        </Link>
      </div>
      <p className="text-xs text-muted-foreground">
        Free during the beta. We only use your email to reply about access.
      </p>
    </form>
  );
}
