"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useBetaLaunchStatus } from "@/app/beta/_lib/use-launch-status";
import { AvailableFormats } from "@/app/beta/_components/AvailableFormats";
import { BetaRequestForm } from "@/app/beta/_components/BetaRequestForm";

export interface ReadinessCtaProps {
  /** What to render when the server reports public access (or before it answers). */
  readonly publicCta: React.ReactNode;
  /** `button`: a compact "Request early access" link; `form`: the full request form. */
  readonly betaVariant: "button" | "form";
  /** Attribution tag for requests made from this CTA. */
  readonly source: string;
  /** Where the `button` variant points (an on-page anchor or /beta). */
  readonly requestHref?: string;
}

/**
 * Readiness-aware CTA. Reads GET /launch/status; while the phase is
 * `private_beta` it swaps the signup/create CTA for a request-early-access
 * path and lists the formats that render today. Until the status arrives (or
 * if it cannot be read) the public CTA stays, since the server enforces the
 * signup gate regardless of what the page shows.
 */
export function ReadinessCta({
  publicCta,
  betaVariant,
  source,
  requestHref = "/beta",
}: ReadinessCtaProps) {
  const { status } = useBetaLaunchStatus();

  if (status?.phase !== "private_beta") return <>{publicCta}</>;

  if (betaVariant === "form") {
    return (
      <div className="mt-4 flex flex-col gap-8">
        <p className="max-w-xl text-pretty leading-relaxed text-muted-foreground">
          Menivor is in a private beta. Request access below; we approve requests by hand
          and approved emails sign in normally.
        </p>
        <BetaRequestForm source={source} />
        <AvailableFormats formats={status.availableFormats} className="max-w-xl border-t border-border pt-8" />
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col items-start gap-5">
      <p className="text-sm text-muted-foreground">
        Menivor is in a private beta. Request access and we will email you once it is approved.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild size="lg">
          <Link href={requestHref}>
            Request early access <ArrowRight className="size-4" aria-hidden />
          </Link>
        </Button>
        <Link href="/sign-in" className="text-sm text-muted-foreground underline underline-offset-4">
          Already approved? Sign in
        </Link>
      </div>
      <AvailableFormats formats={status.availableFormats} className="max-w-xl" />
    </div>
  );
}
