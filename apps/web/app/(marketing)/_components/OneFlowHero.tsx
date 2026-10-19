import Link from "next/link";
import { WaitlistForm } from "@/components/marketing/WaitlistForm";
import { HeroReel } from "@/components/marketing/showcase/HeroReel";
import { WAITLIST_ANCHOR } from "@/lib/waitlist";
import { getTranslations } from "@/lib/i18n/server";
import { OFFER } from "@/lib/offer";
import type { ShowcaseMedia } from "@/lib/styles/showcase";
import type { LaunchPosture } from "@/src/shared/launch-posture";
import { ReadinessCta } from "./ReadinessCta";
import { SignupBox } from "./SignupBox";

/**
 * Video-first landing hero, cinematic and full-bleed: on phones the lead
 * showcase reel fills the screen behind the copy; on wide screens the copy
 * sits left of a row of three moving reels that runs to the right edge. Only
 * the lead reel preloads. The headline leads with the narrowest wedge the
 * capture pipeline already ships end to end — an App Store/Play Store link
 * in, a rendered vertical demo out (see `app/domains/capture/sources.py` +
 * `store.py` + `slideshow.py` on the API) — while the input itself stays the
 * same general paste box (a site, a social post, or a topic all still work).
 * The free-first-reel line reads `OFFER.short` so it can never say "free"
 * when the API flag is off. The primary action follows the server-read
 * launch posture:
 * - `public`: the paste box leads into sign-up, then the free first reel (or
 *   the $1 card check when that flag is off), then the reels render in the
 *   picked style.
 * - `beta`: the same box, swapped client-side for a request-early-access CTA.
 * - `waitlist`: the waitlist is the only CTA.
 */
export async function OneFlowHero({
  posture,
  hero,
  side,
}: Readonly<{
  posture: LaunchPosture;
  hero: ShowcaseMedia;
  side: readonly ShowcaseMedia[];
}>) {
  const t = await getTranslations();
  return (
    <section className="relative isolate overflow-hidden bg-black">
      <div className="lg:grid lg:min-h-[calc(100svh-4rem)] lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:items-center">
        <div
          aria-hidden
          className="absolute inset-x-0 top-0 -z-10 h-[68svh] lg:static lg:order-2 lg:z-auto lg:flex lg:h-full lg:items-center lg:gap-2 lg:py-6 lg:pr-0"
        >
          <HeroReel
            reel={hero}
            priority
            className="size-full lg:aspect-[9/16] lg:h-[min(78svh,760px)] lg:w-auto lg:flex-none lg:rounded-2xl"
          />
          {side.map((reel, index) => (
            <HeroReel
              key={reel.key}
              reel={reel}
              className={
                index === 0
                  ? "hidden lg:block lg:aspect-[9/16] lg:h-[min(66svh,640px)] lg:w-auto lg:flex-none lg:rounded-2xl"
                  : "hidden xl:block xl:aspect-[9/16] xl:h-[min(56svh,540px)] xl:w-auto xl:flex-none xl:rounded-l-2xl"
              }
            />
          ))}
        </div>
        <div
          aria-hidden
          className="absolute inset-x-0 top-0 -z-10 h-[68svh] bg-gradient-to-t from-black via-black/10 to-transparent lg:hidden"
        />
        <div className="relative flex flex-col px-4 pb-10 pt-[52svh] sm:px-8 lg:order-1 lg:justify-center lg:py-16 lg:pl-[max(2rem,calc((100vw-1400px)/2))] lg:pr-10">
        <p className="kicker text-white/70">Paste an App Store link, get a TikTok-ready demo</p>
        <h1 className="mt-4 max-w-2xl text-balance font-display text-[2.6rem] font-bold uppercase leading-[0.95] tracking-tight text-white sm:text-display-lg">
          Paste your App Store link. Get a TikTok-ready demo video.
        </h1>
        <p className="mt-5 max-w-xl text-pretty text-base leading-relaxed text-white/75 sm:text-lg">
          Menivor reads the listing — screenshots, description and rating — writes the hook,
          voices it, captions it and renders a vertical demo ready for TikTok, Reels and Shorts.
          A Google Play link, your own site, or a 30-second screen recording all work the same way.
        </p>
        {posture.mode === "public" && (
          <p className="mt-3 text-sm font-medium text-white/90">{OFFER.short}.</p>
        )}

        <div className="mt-8 w-full max-w-2xl text-left">
          {posture.mode === "waitlist" ? (
            <div className="flex w-full flex-col items-start gap-3">
              <p className="text-sm text-muted-foreground">
                Rendering is in a closed pilot while capacity comes online. Join the
                waitlist and we will email you when your spot opens.
              </p>
              <WaitlistForm source="hero" />
            </div>
          ) : posture.mode === "public" ? (
            <div className="flex w-full flex-col gap-3">
              <SignupBox note={t("landing.signupNote")} />
              <p className="px-1 text-sm text-muted-foreground">
                Already have an account?{" "}
                <Link href="/sign-in" className="underline underline-offset-4 hover:text-foreground">
                  {t("nav.signIn")}
                </Link>
              </p>
            </div>
          ) : (
            <ReadinessCta
              betaVariant="button"
              source="landing-hero"
              requestHref={`#${WAITLIST_ANCHOR}`}
              publicCta={<SignupBox note={t("landing.signupNote")} />}
            />
          )}
        </div>
        </div>
      </div>
    </section>
  );
}
