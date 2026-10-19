import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { SignedIn, SignedOut } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { PRIMARY_CTA, SECONDARY_CTA } from "@/lib/seo";

/**
 * Shared closing call-to-action band for the programmatic pages. Flat, ruled,
 * and truthful: the primary action comes from lib/seo's PRIMARY_CTA, which is
 * the waitlist when WAITLIST_MODE is on and free signup otherwise.
 * Signed-in visitors are routed to the reel builder instead.
 */
interface CtaBandProps {
  readonly heading: string;
  readonly subheading?: string;
}

export function CtaBand({ heading, subheading }: CtaBandProps) {
  return (
    <section className="mt-16 rounded-md border border-border bg-card">
      <div className="flex flex-col items-start gap-5 px-6 py-10 sm:px-10">
        <h2 className="max-w-2xl text-balance text-2xl font-bold tracking-tight sm:text-3xl">
          {heading}
        </h2>
        {subheading ? (
          <p className="max-w-xl text-pretty text-muted-foreground">
            {subheading}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <SignedOut>
            <Button asChild size="lg">
              <Link href={PRIMARY_CTA.href}>
                {PRIMARY_CTA.label} <ArrowRight className="size-4" />
              </Link>
            </Button>
          </SignedOut>
          <SignedIn>
            <Button asChild size="lg">
              <Link href="/new">
                New reel <ArrowRight className="size-4" />
              </Link>
            </Button>
          </SignedIn>
          <Button asChild variant="outline" size="lg">
            <Link href={SECONDARY_CTA.href}>{SECONDARY_CTA.label}</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
