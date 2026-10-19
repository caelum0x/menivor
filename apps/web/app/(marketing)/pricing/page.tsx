import type { Metadata } from "next";
import Link from "next/link";
import { LivePackPreview } from "@/components/marketing/LivePackPreview";
import { WaitlistForm } from "@/components/marketing/WaitlistForm";
import { PRICING_PLANS } from "@/components/marketing/plans";
import { PerReelPrice } from "./PerReelPrice";
import { PricingCheckout } from "./PricingCheckout";
import { WAITLIST_FALLBACK_EMAIL } from "@/lib/waitlist";
import { WAITLIST_MODE } from "@/lib/clerk";
import { getTranslations } from "@/lib/i18n/server";
import type { Translator } from "@/lib/i18n/translator";
import { loadCatalogForRender } from "@/src/features/plans/api";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Menivor pricing: monthly plans for regular posting, or one-time credit packs that never expire. A failed render refunds its credit automatically.",
  alternates: { canonical: "/pricing" },
};

/**
 * Pricing page. Credit-pack pricing is real, but while WAITLIST_MODE is on
 * nothing is purchasable — so the packs render as a preview whose only CTA is
 * the waitlist, clearly labeled as opening with early access. With a real
 * auth instance, the interactive checkout (provider toggle + hosted checkout
 * redirect) takes over unchanged.
 */
export default async function PricingPage() {
  // Read the live monthly catalog on the server so the HTML already shows
  // "Start Creator" when the plans are on sale (null -> display fallback).
  const [t, monthlyCatalog] = await Promise.all([
    getTranslations(),
    WAITLIST_MODE ? Promise.resolve(null) : loadCatalogForRender(),
  ]);
  return (
    <div className="container py-16 lg:py-24">
      <div className="mb-14 max-w-2xl">
        <p className="kicker text-muted-foreground">{t("pricing.kicker")}</p>
        <h1 className="mt-4 text-display-lg font-bold">{t("pricing.title")}</h1>
        <p className="mt-4 text-pretty text-lg leading-relaxed text-muted-foreground">
          {t("pricing.intro")}
        </p>
      </div>

      {WAITLIST_MODE ? (
        <WaitlistPricing t={t} />
      ) : (
        <PricingCheckout plans={PRICING_PLANS} monthlyCatalog={monthlyCatalog} />
      )}

      <PerReelPrice plans={PRICING_PLANS} />

      <section className="mt-14 max-w-3xl space-y-4 border-t border-border pt-10 text-muted-foreground">
        <h2 className="text-2xl font-semibold text-foreground">
          {t("pricing.howHeading")}
        </h2>
        <p>
          {t("pricing.howPara1")}{" "}
          <Link href="/creator-contract" className="text-primary underline underline-offset-4">
            Read the Creator Contract
          </Link>
          .
        </p>
        <p>{t("pricing.howPara2")}</p>
        <p>{t("pricing.howPara3")}</p>
      </section>

      <p className="mt-12 text-sm text-muted-foreground">
        {t("pricing.volumeQuestion")}{" "}
        <a
          href={`mailto:${WAITLIST_FALLBACK_EMAIL}?subject=Menivor%20volume%20pricing`}
          className="font-medium text-primary underline underline-offset-4"
        >
          {WAITLIST_FALLBACK_EMAIL}
        </a>
        .
      </p>
    </div>
  );
}

/** Static pack preview shown while checkout is gated behind early access. */
function WaitlistPricing({ t }: Readonly<{ t: Translator }>) {
  return (
    <div className="flex flex-col gap-10">
      <LivePackPreview
        plans={PRICING_PLANS}
        ctaLabel={t("pricing.waitlistCtaLabel")}
        ctaHref="/#waitlist"
      />

      <div className="max-w-xl border-t border-border pt-8">
        <p className="kicker text-muted-foreground">{t("pricing.waitlistKicker")}</p>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          {t("pricing.waitlistBody")}
        </p>
        <div className="mt-4">
          <WaitlistForm source="pricing" />
        </div>
      </div>
    </div>
  );
}
