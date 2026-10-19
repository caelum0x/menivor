import Link from "next/link";
import { PRICING_PLANS } from "@/components/marketing/plans";
import { fetchPublicPackCatalog, mergeLiveCatalog } from "@/components/marketing/live-plans";
import { cn } from "@/lib/utils";

async function livePlans() {
  try {
    return mergeLiveCatalog(PRICING_PLANS, await fetchPublicPackCatalog());
  } catch {
    // The API is unreachable: show the display defaults; checkout re-prices.
    return PRICING_PLANS;
  }
}

/**
 * Honest pricing summary: the same packs and live prices as /pricing. One
 * credit is one finished reel; credits never expire; failed renders refund.
 */
export async function PricingStrip() {
  const plans = await livePlans();
  return (
    <section id="pricing" className="scroll-mt-20 border-b border-white/[0.06]">
      <div className="container py-16 lg:py-20">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="max-w-xl">
            <p className="kicker text-muted-foreground">Pricing</p>
            <h2 className="mt-3 text-display font-bold">Pay per reel. Credits never expire.</h2>
          </div>
          <Link href="/pricing" className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground">
            Full pricing
          </Link>
        </div>
        <ul className="mt-10 grid gap-4 md:grid-cols-3">
          {plans.map((plan) => (
            <li
              key={plan.name}
              className={cn(
                "glass-subtle flex flex-col rounded-2xl p-5",
                plan.highlighted && "ring-1 ring-primary/50",
              )}
            >
              <h3 className="text-base font-semibold text-foreground">{plan.name}</h3>
              <p className="mt-3">
                <span className="text-3xl font-bold text-foreground">{plan.price}</span>{" "}
                <span className="text-sm text-muted-foreground">{plan.period}</span>
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {plan.credits} reel credits. One credit is one finished reel.
              </p>
            </li>
          ))}
        </ul>
        <p className="mt-6 text-sm text-muted-foreground">
          Failed renders refund their credit automatically, and we never train on your content.{" "}
          <Link href="/creator-contract" className="underline underline-offset-4">
            Read the Creator Contract
          </Link>
          .
        </p>
      </div>
    </section>
  );
}
