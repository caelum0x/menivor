import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Translator } from "@/lib/i18n/translator";
import { joinLabels, type LaunchPosture } from "@/src/shared/launch-posture";
import { SignupBox } from "./SignupBox";

/**
 * Public-launch CTA block: the link-or-topic box into sign-up, sign-in for
 * returning users, and exactly what the API says is open (and not yet) on the
 * current tier. There is no guest path: sign-up plus a $1 card check come
 * first. Server-rendered from the launch posture.
 */
export function PublicLaunchCta({
  posture,
  t,
}: Readonly<{ posture: LaunchPosture; t: Translator }>) {
  return (
    <div className="flex w-full flex-col items-start gap-5">
      <SignupBox note={t("landing.signupNote")} />
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild variant="outline" size="lg">
          <Link href="/sign-up">
            {t("landing.startFree")} <ArrowRight className="size-4" aria-hidden />
          </Link>
        </Button>
        <Button asChild variant="ghost" size="lg">
          <Link href="/sign-in">{t("nav.signIn")}</Link>
        </Button>
      </div>
      <FormatSummary posture={posture} t={t} />
    </div>
  );
}

/**
 * "Open now" line built from GET /launch/status. Locked formats are not
 * listed: public copy never names a feature that is not live (claims rule 5).
 */
export function FormatSummary({
  posture,
  t,
}: Readonly<{ posture: LaunchPosture; t: Translator }>) {
  if (posture.availableFormats.length === 0) return null;
  return (
    <dl className="max-w-xl space-y-1 text-sm text-muted-foreground">
      <div>
        <dt className="inline font-medium text-foreground">{t("landing.openNowLabel")}</dt>{" "}
        <dd className="inline">{joinLabels(posture.availableFormats)}.</dd>
      </div>
    </dl>
  );
}
