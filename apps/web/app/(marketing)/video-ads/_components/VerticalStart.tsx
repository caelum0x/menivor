import { WaitlistForm } from "@/components/marketing/WaitlistForm";
import { WAITLIST_ANCHOR } from "@/lib/waitlist";
import { getTranslations } from "@/lib/i18n/server";
import { getLaunchPosture } from "@/src/shared/launch-posture/server";
import { ReadinessCta } from "../../_components/ReadinessCta";
import { SignupBox } from "../../_components/SignupBox";

/**
 * The one input on every video-ads page, driven by the live launch status like
 * the landing hero: the paste-a-link box into sign-up when public, the
 * early-access request in a beta, the waitlist otherwise.
 */
export async function VerticalStart() {
  const [posture, t] = await Promise.all([getLaunchPosture(), getTranslations()]);
  if (posture.mode === "waitlist") return <WaitlistForm source="video-ads" />;
  if (posture.mode === "public") return <SignupBox note={t("landing.signupNote")} />;
  return (
    <ReadinessCta
      betaVariant="button"
      source="video-ads"
      requestHref={`/#${WAITLIST_ANCHOR}`}
      publicCta={<SignupBox note={t("landing.signupNote")} />}
    />
  );
}
