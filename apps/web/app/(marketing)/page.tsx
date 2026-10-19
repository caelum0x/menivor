import Link from "next/link";
import { preconnect, preload } from "react-dom";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { OneFlowHero } from "./_components/OneFlowHero";
import { StylePickProvider } from "@/components/marketing/styles/StylePick";
import { ThreeSteps } from "@/components/marketing/styles/ThreeSteps";
import { PricingStrip } from "@/components/marketing/styles/PricingStrip";
import { ShowcaseWall } from "@/components/marketing/showcase/ShowcaseWall";
import { ShowcaseNote } from "@/components/marketing/showcase/ShowcaseNote";
import { galleryWallMedia } from "@/src/features/gallery/wall";
import { isStyleId } from "@/lib/styles/catalog";
import { showcaseLayout, type ShowcaseMedia } from "@/lib/styles/showcase";
import { WaitlistForm } from "@/components/marketing/WaitlistForm";
import { FaqSection } from "@/components/marketing/seo/FaqSection";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { WAITLIST_ANCHOR } from "@/lib/waitlist";
import { faqPageLd, graphDocument, type FaqEntry } from "@/lib/seo";
import { getTranslations } from "@/lib/i18n/server";
import { ReadinessCta } from "./_components/ReadinessCta";
import { FormatSummary } from "./_components/PublicLaunchCta";
import { availabilityAnswer, type LaunchPosture } from "@/src/shared/launch-posture";
import { getLaunchPosture } from "@/src/shared/launch-posture/server";
import type { Translator } from "@/lib/i18n/translator";

const BASE_FAQS: readonly FaqEntry[] = [
  {
    question: "What is Menivor?",
    answer:
      "Menivor makes finished short videos for you. Paste a link and get ads written for it, or type a topic and get a story. Each run renders vertical reels with different opening hooks, a voiceover and word-by-word captions, ready to post.",
  },
  {
    question: "Can Menivor turn a screen recording into a reel?",
    answer:
      "Yes. Menivor uses your screen recording as the footage, writes a hook-first script, voices it and burns in word-by-word captions, then renders a vertical MP4.",
  },
  {
    question: "Do Menivor credits expire?",
    answer:
      "No. Credits never expire, a failed render refunds its credit automatically, and we never train on your content. These promises are published in our Creator Contract.",
  },
  {
    question: "What styles can Menivor make?",
    answer:
      "Block-world gameplay split-screen, meme-caption hooks (like “you met me at a very ___ time in my life”), original AI anime-style scenes, satisfying split-screen, POV text, before and after, story time and a cartoon narrator over gameplay. Pick one with a click after pasting your link.",
  },
  {
    question: "Is the footage and music safe to post?",
    answer:
      "Yes. Gameplay and satisfying loops are original footage we render ourselves, anime-style scenes are generated fresh for your reel, and meme hooks reuse only the text pattern, written for your product. No ripped clips or library sounds are used.",
  },
  {
    question: "Does Menivor support Turkish videos?",
    answer:
      "Yes. Menivor writes and voices hook scripts in English or Turkish, and its caption fonts include Turkish characters.",
  },
];

/** FAQ list with the availability answer built from the live launch status. */
function homeFaqs(posture: LaunchPosture): readonly FaqEntry[] {
  return [
    ...BASE_FAQS,
    { question: "Is Menivor available now?", answer: availabilityAnswer(posture) },
  ];
}

/**
 * First paint on phones is the lead reel's poster: preload it at high priority
 * and open the media connection early. The loops attach only once on screen.
 */
function preloadHeroPoster(hero: ShowcaseMedia): void {
  if (/^https:\/\//.test(hero.poster)) preconnect(new URL(hero.poster).origin);
  preload(hero.poster, { as: "image", fetchPriority: "high" });
}

type LandingSearchParams = Promise<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

/**
 * Video-first landing: a full-bleed hero of moving reels beside the paste box
 * (one-click style chips; `/?style=<id>` preselects server-side), then dense
 * masonry walls of real showcase reels by niche, each tile named by its
 * style with a "Paste a link" action that preselects it. Then how it works,
 * honest live pricing, an FAQ whose availability answer lists exactly what
 * the API reports as open, and a posture-matched closing section. No reel
 * appears twice; no fabricated metrics or testimonials.
 */
export default async function LandingPage({
  searchParams,
}: Readonly<{ searchParams: LandingSearchParams }>) {
  const posture = await getLaunchPosture();
  const faqs = homeFaqs(posture);
  const params = await searchParams;
  const requested = first(params.style);
  // Disjoint split: no reel appears twice on the page.
  const showcase = showcaseLayout();
  preloadHeroPoster(showcase.hero);
  // P-M2: staff-approved gallery items join the first wall (at most six; none on an outage).
  const firstGroup = showcase.groups[0]?.id;
  const gallery = firstGroup ? await galleryWallMedia(firstGroup) : [];
  return (
    <>
      <JsonLd data={graphDocument([faqPageLd(faqs)])} />
      <StylePickProvider initial={isStyleId(requested) ? requested : null}>
        <OneFlowHero posture={posture} hero={showcase.hero} side={showcase.heroSide} />
        {/* The walls sit below the hero on every screen size (never behind its copy). */}
        <div id="styles" className="relative scroll-mt-20 bg-black">
          {showcase.groups.map((group, index) => (
            <ShowcaseWall
              key={group.id}
              id={group.id}
              title={group.title}
              subline={group.subline}
              reels={group.reels}
              gallery={index === 0 ? gallery : []}
            />
          ))}
          <ShowcaseNote />
        </div>
      </StylePickProvider>
      <ThreeSteps />
      <PricingStrip />
      <div className="container py-16">
        <FaqSection faqs={faqs} />
      </div>
      <CtaSection posture={posture} />
    </>
  );
}

async function CtaSection({ posture }: Readonly<{ posture: LaunchPosture }>) {
  const t = await getTranslations();
  if (posture.mode === "public") return <PublicCtaSection posture={posture} t={t} />;
  return (
    <section id={WAITLIST_ANCHOR} className="scroll-mt-20">
      <div className="container py-20">
        <div className="max-w-2xl">
          <p className="kicker text-muted-foreground">{t("landing.ctaKicker")}</p>
          <h2 className="mt-4 text-display font-bold">{t("landing.ctaTitle")}</h2>

          {posture.mode === "waitlist" ? (
            <>
              <p className="mt-4 max-w-xl text-pretty leading-relaxed text-muted-foreground">
                {t("landing.ctaWaitlistBody")}
              </p>
              <div className="mt-6">
                <WaitlistForm source="landing-cta" />
              </div>
            </>
          ) : (
            <ReadinessCta
              betaVariant="form"
              source="landing-cta"
              publicCta={
                <>
                  <p className="mt-4 max-w-xl text-pretty leading-relaxed text-muted-foreground">
                    {t("landing.ctaLiveBody")}
                  </p>
                  <div className="mt-6 flex flex-wrap items-center gap-3">
                    <Button asChild size="lg">
                      <Link href="/sign-up">
                        {t("landing.ctaCreateFirst")}{" "}
                        <ArrowRight className="size-4" />
                      </Link>
                    </Button>
                    <Button asChild variant="outline" size="lg">
                      <Link href="/pricing">{t("landing.ctaComparePlans")}</Link>
                    </Button>
                  </div>
                  <p className="mt-4 text-sm text-muted-foreground">
                    Credits never expire, failed renders are refunded automatically,
                    and we never train on your content.{" "}
                    <Link href="/creator-contract" className="underline underline-offset-4">
                      Read the Creator Contract
                    </Link>
                    .
                  </p>
                  {/* Always-present email capture: pricing, the wallet and the
                      generation-unavailable fallback all deep-link to #waitlist
                      (e.g. while the server launch gate keeps checkout closed). */}
                  <div className="mt-10 max-w-xl border-t border-border pt-8">
                    <p className="text-sm font-medium text-foreground">
                      Get launch updates
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      One email when paid packs and new render capacity open.
                    </p>
                    <div className="mt-4">
                      <WaitlistForm
                        source="landing-updates"
                        submitLabel={t("landing.updatesSubmit")}
                        successMessage={t("landing.updatesSuccess")}
                      />
                    </div>
                  </div>
                </>
              }
            />
          )}
        </div>
      </div>
    </section>
  );
}

/** Closing section at public launch: signup first, launch-updates capture second. */
function PublicCtaSection({
  posture,
  t,
}: Readonly<{ posture: LaunchPosture; t: Translator }>) {
  return (
    <section id={WAITLIST_ANCHOR} className="scroll-mt-20">
      <div className="container py-20">
        <div className="max-w-2xl">
          <p className="kicker text-muted-foreground">{t("landing.publicKicker")}</p>
          <h2 className="mt-4 text-display font-bold">{t("landing.publicTitle")}</h2>
          <p className="mt-4 max-w-xl text-pretty leading-relaxed text-muted-foreground">
            {t("landing.publicBody")}
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Button asChild size="lg">
              <Link href="/sign-up">
                {t("landing.startFree")} <ArrowRight className="size-4" aria-hidden />
              </Link>
            </Button>
            <Button asChild variant="outline" size="lg">
              <Link href="/pricing">{t("landing.ctaComparePlans")}</Link>
            </Button>
          </div>
          <div className="mt-6">
            <FormatSummary posture={posture} t={t} />
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            Credits never expire, failed renders are refunded automatically, and we never
            train on your content.{" "}
            <Link href="/creator-contract" className="underline underline-offset-4">
              Read the Creator Contract
            </Link>
            .
          </p>
          <div className="mt-10 max-w-xl border-t border-border pt-8">
            <p className="text-sm font-medium text-foreground">{t("landing.updatesTitle")}</p>
            <p className="mt-1 text-sm text-muted-foreground">{t("landing.updatesBody")}</p>
            <div className="mt-4">
              <WaitlistForm
                source="landing-updates"
                submitLabel={t("landing.updatesSubmit")}
                successMessage={t("landing.updatesSuccess")}
              />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
