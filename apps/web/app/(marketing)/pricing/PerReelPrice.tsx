import Link from "next/link";
import type { PricingPlan } from "@/components/marketing/PricingCard";

/**
 * Per-reel price clarity: what one finished reel costs on each pack at list
 * price, and how length and premium add-ons change it (M3.1, MD8: 1 credit up
 * to 60 s, 1 per started minute after that; premium SKUs priced by MG3).
 */

/** Credits one video of ``seconds`` uses (mirrors apps/api reels.pricing). */
export function creditsForSeconds(seconds: number): number {
  const length = Math.max(1, Math.floor(seconds));
  return length <= 60 ? 1 : Math.ceil(length / 60);
}

interface PerReelRow {
  readonly name: string;
  readonly price: string;
  readonly credits: number;
  readonly perReel: string;
}

/** "$19" -> 19. Returns null for anything that is not a plain dollar price. */
export function parseDollars(price: string): number | null {
  const match = /^\$\s*(\d+(?:\.\d+)?)$/.exec(price.trim());
  return match ? Number(match[1]) : null;
}

export function perReelRows(plans: readonly PricingPlan[]): PerReelRow[] {
  return plans
    .filter((plan) => plan.credits > 0)
    .map((plan) => {
      const dollars = parseDollars(plan.price);
      const perReel =
        dollars === null ? "" : dollars === 0 ? "Free" : `$${(dollars / plan.credits).toFixed(2)}`;
      return { name: plan.name, price: plan.price, credits: plan.credits, perReel };
    })
    .filter((row) => row.perReel !== "");
}

export function PerReelPrice({ plans }: Readonly<{ plans: readonly PricingPlan[] }>) {
  const rows = perReelRows(plans);
  const paidPrices = rows
    .filter((row) => row.perReel !== "Free")
    .map((row) => Number(row.perReel.slice(1)))
    .filter((value) => Number.isFinite(value));
  const low = paidPrices.length ? Math.min(...paidPrices) : null;
  const high = paidPrices.length ? Math.max(...paidPrices) : null;

  return (
    <section className="mt-14 max-w-3xl border-t border-border pt-10">
      <h2 className="text-2xl font-semibold text-foreground">What one reel costs</h2>
      <p className="mt-3 text-muted-foreground">
        One credit is one finished vertical reel up to 60 seconds, with the
        script, voiceover, captions and final render included. A longer video
        uses one credit per started minute, so a 2.5-minute video uses 3
        credits. Premium voices and AI video clips use their own credits. The
        app shows the full price before you render.
      </p>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border text-muted-foreground">
            <tr>
              <th scope="col" className="py-2 pr-4 font-medium">Pack</th>
              <th scope="col" className="py-2 pr-4 font-medium">Price</th>
              <th scope="col" className="py-2 pr-4 font-medium">Reels</th>
              <th scope="col" className="py-2 font-medium">Per reel</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name} className="border-b border-border/60">
                <td className="py-2 pr-4 font-medium text-foreground">{row.name}</td>
                <td className="py-2 pr-4">{row.price}</td>
                <td className="py-2 pr-4">{row.credits}</td>
                <td className="py-2 font-medium text-foreground">{row.perReel}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">
        List prices in USD. Checkout shows the final price, including any tax or
        currency conversion, before you pay.
        {low !== null && high !== null && (
          <>
            {" "}
            A new run makes three hook variants, so testing three hooks costs 3
            credits: {`$${(low * 3).toFixed(2)}`} to {`$${(high * 3).toFixed(2)}`} on
            a pack.
          </>
        )}
      </p>

      <p className="mt-8 text-sm text-muted-foreground">
        Every Menivor pack comes with the same{" "}
        <Link href="/creator-contract" className="font-medium text-primary underline underline-offset-4">
          Creator Contract
        </Link>
        : credits never expire, failed renders are refunded automatically, we
        never train on your content, and you can cancel anytime.
      </p>
    </section>
  );
}
