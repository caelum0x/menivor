"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface NewsletterFormProps {
  readonly className?: string;
  /** Heading above the field; defaults to "Product updates". */
  readonly title?: string;
  /** One line under the heading. */
  readonly blurb?: string;
  /** Submit button label. */
  readonly submitLabel?: string;
}

const DEFAULT_TITLE = "Product updates";
const DEFAULT_BLURB = "New features and launch notes, about once a month. Unsubscribe any time.";

type Status = "idle" | "submitting" | "success" | "error";

interface FormState {
  readonly status: Status;
  readonly message: string;
}

const IDLE: FormState = { status: "idle", message: "" };

function readError(body: unknown): string {
  return typeof body === "object" && body !== null && "error" in body
    ? String((body as { error: unknown }).error)
    : "";
}

/**
 * Product-updates signup. Posts to `/api/newsletter`, which forwards to our
 * self-hosted listmonk (double opt-in). Requires explicit consent; nothing is
 * pre-ticked. One field only: the email (the hidden Company honeypot was
 * dropped because browser autofill could fill it and silently drop real
 * sign-ups; consent plus double opt-in at the list provider stays).
 */
export function NewsletterForm({
  className,
  title = DEFAULT_TITLE,
  blurb = DEFAULT_BLURB,
  submitLabel = "Subscribe",
}: NewsletterFormProps) {
  const [email, setEmail] = React.useState("");
  const [consent, setConsent] = React.useState(false);
  const [state, setState] = React.useState<FormState>(IDLE);
  const id = React.useId();

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (state.status === "submitting") return;
    if (!consent) {
      setState({ status: "error", message: "Please tick the box to agree to receive updates." });
      return;
    }
    setState({ status: "submitting", message: "" });
    try {
      const response = await fetch("/api/newsletter", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, consent }),
      });
      const body: unknown = await response.json().catch(() => null);
      if (response.ok) {
        setEmail("");
        setConsent(false);
        setState({
          status: "success",
          message:
            "Almost done. Check your inbox and click the confirmation link to start receiving updates.",
        });
        return;
      }
      setState({
        status: "error",
        message: readError(body) || "Something went wrong. Please try again.",
      });
    } catch {
      setState({ status: "error", message: "Network error. Please try again." });
    }
  };

  if (state.status === "success") {
    return (
      <p role="status" className={cn("max-w-sm text-sm font-medium text-primary", className)}>
        {state.message}
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit} className={cn("flex w-full max-w-sm flex-col gap-2", className)} noValidate>
      <p className="text-sm font-medium text-foreground">{title}</p>
      <p className="text-xs text-muted-foreground">{blurb}</p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <label htmlFor={`${id}-email`} className="sr-only">
          Email address
        </label>
        <Input
          id={`${id}-email`}
          type="email"
          required
          autoComplete="email"
          maxLength={254}
          placeholder="you@company.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Button type="submit" disabled={state.status === "submitting"}>
          {state.status === "submitting" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
          {submitLabel}
        </Button>
      </div>
      <label htmlFor={`${id}-consent`} className="flex items-start gap-2 text-xs leading-5 text-muted-foreground">
        <input
          id={`${id}-consent`}
          type="checkbox"
          checked={consent}
          onChange={(event) => setConsent(event.target.checked)}
          className="mt-0.5 size-4 shrink-0 accent-primary"
        />
        <span>
          I agree to receive Menivor product emails. See the{" "}
          <Link href="/privacy" className="underline underline-offset-4 hover:text-foreground">
            privacy policy
          </Link>
          .
        </span>
      </label>
      {state.status === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
