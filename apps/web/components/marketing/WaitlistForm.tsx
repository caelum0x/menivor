"use client";

import * as React from "react";
import { Loader2, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WAITLIST_FALLBACK_EMAIL } from "@/lib/waitlist";
import { cn } from "@/lib/utils";

interface WaitlistFormProps {
  /** Attribution tag stored with the signup, e.g. `landing-cta` or `hero`. */
  readonly source: string;
  readonly className?: string;
  /** Submit button label; defaults to the waitlist wording. */
  readonly submitLabel?: string;
  /** Confirmation shown after a successful signup. */
  readonly successMessage?: string;
}

const DEFAULT_SUBMIT_LABEL = "Join the waitlist";
const DEFAULT_SUCCESS_MESSAGE = "You're on the list — we'll email you when your spot opens.";

type FormStatus = "idle" | "submitting" | "success" | "error" | "unavailable";

interface FormState {
  readonly status: FormStatus;
  readonly message: string;
}

const IDLE_STATE: FormState = { status: "idle", message: "" };

/**
 * Email capture for the public waitlist. Posts to `/api/waitlist` (KV-backed on
 * Cloudflare); when the endpoint reports itself unavailable — local dev or a
 * deploy without the KV namespace — it degrades to a `mailto:` link instead of
 * erroring out, so the marketing page never shows a dead end.
 *
 * Includes a honeypot field (`company`) that stays hidden from humans; the
 * server silently drops submissions that fill it.
 */
export function WaitlistForm({
  source,
  className,
  submitLabel = DEFAULT_SUBMIT_LABEL,
  successMessage = DEFAULT_SUCCESS_MESSAGE,
}: WaitlistFormProps) {
  const [email, setEmail] = React.useState("");
  const [honeypot, setHoneypot] = React.useState("");
  const [state, setState] = React.useState<FormState>(IDLE_STATE);

  const handleSubmit = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (state.status === "submitting") return;
      setState({ status: "submitting", message: "" });
      try {
        const response = await fetch("/api/waitlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, source, company: honeypot }),
        });
        const body: unknown = await response.json().catch(() => null);
        const errorMessage =
          typeof body === "object" && body !== null && "error" in body
            ? String((body as { error: unknown }).error)
            : "";
        if (response.ok) {
          setState({
            status: "success",
            message: successMessage,
          });
          setEmail("");
          return;
        }
        if (response.status === 503) {
          setState({ status: "unavailable", message: "" });
          return;
        }
        setState({
          status: "error",
          message: errorMessage || "Something went wrong. Please try again.",
        });
      } catch {
        // Network failure — same graceful path as a missing backend.
        setState({ status: "unavailable", message: "" });
      }
    },
    [email, honeypot, source, state.status, successMessage],
  );

  if (state.status === "success") {
    return (
      <p
        role="status"
        className={cn("text-sm font-medium text-primary", className)}
      >
        {state.message}
      </p>
    );
  }

  if (state.status === "unavailable") {
    return (
      <p role="status" className={cn("text-sm text-muted-foreground", className)}>
        Signups are paused right now — email{" "}
        <a
          className="font-medium text-primary underline underline-offset-4"
          href={`mailto:${WAITLIST_FALLBACK_EMAIL}?subject=Menivor%20waitlist`}
        >
          {WAITLIST_FALLBACK_EMAIL}
        </a>{" "}
        and we&rsquo;ll add you by hand.
      </p>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className={cn("flex w-full max-w-md flex-col gap-2", className)}
    >
      <div className="flex flex-col gap-2 sm:flex-row">
        <label htmlFor={`waitlist-email-${source}`} className="sr-only">
          Email address
        </label>
        <Input
          id={`waitlist-email-${source}`}
          type="email"
          required
          autoComplete="email"
          maxLength={254}
          placeholder="you@company.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        {/* Honeypot: hidden from humans, tempting to bots. */}
        <div aria-hidden="true" className="absolute -left-[9999px] top-auto h-px w-px overflow-hidden">
          <label htmlFor={`waitlist-company-${source}`}>Company</label>
          <input
            id={`waitlist-company-${source}`}
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={honeypot}
            onChange={(event) => setHoneypot(event.target.value)}
          />
        </div>
        <Button type="submit" disabled={state.status === "submitting"}>
          {state.status === "submitting" ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <Mail className="size-4" aria-hidden />
          )}
          {submitLabel}
        </Button>
      </div>
      {state.status === "error" && (
        <p role="alert" className="text-sm text-destructive">
          {state.message}
        </p>
      )}
    </form>
  );
}
