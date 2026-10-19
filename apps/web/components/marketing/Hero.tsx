import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CaptionDemo } from "@/components/marketing/CaptionDemo";
import { WaitlistForm } from "@/components/marketing/WaitlistForm";
import { WAITLIST_MODE } from "@/lib/clerk";
import { getTranslations } from "@/lib/i18n/server";

/**
 * Landing hero — left-aligned editorial type with a single live element: the
 * caption engine's word-by-word highlight running in HTML (no fake video, no
 * fabricated presenter). In waitlist mode the only CTA is the waitlist; once a
 * real auth instance ships, the sign-up path takes over automatically.
 */
export async function Hero() {
  const t = await getTranslations();
  return (
    <section className="border-b border-border">
      <div className="container grid items-center gap-14 py-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,360px)] lg:gap-20 lg:py-24">
        <div className="flex max-w-2xl flex-col items-start gap-7">
          <p className="kicker text-muted-foreground">{t("landing.heroKicker")}</p>

          <h1 className="text-display-lg font-bold text-foreground">
            {t("landing.heroTitle")}
          </h1>

          <p className="max-w-xl text-pretty text-lg leading-relaxed text-muted-foreground">
            {t("landing.heroBody")}
          </p>

          {WAITLIST_MODE ? (
            <div className="flex w-full flex-col items-start gap-3">
              <p className="text-sm text-muted-foreground">
                {t("landing.heroWaitlistNote")}
              </p>
              <WaitlistForm source="hero" />
            </div>
          ) : (
            <div className="flex flex-col items-start gap-2">
              <div className="flex flex-wrap items-center gap-3">
                <Button asChild size="lg">
                  <Link href="/create">
                    {t("landing.heroMakeReelFree")}{" "}
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
                <Button asChild variant="outline" size="lg">
                  <Link href="/pricing">{t("landing.heroSeePricing")}</Link>
                </Button>
              </div>
              <p className="text-sm text-muted-foreground">
                {t("landing.heroFreeNote")}
              </p>
            </div>
          )}
        </div>

        <div className="mx-auto w-full lg:mx-0">
          <CaptionDemo />
        </div>
      </div>
    </section>
  );
}
