import type { Metadata } from "next";
import { headers } from "next/headers";
import Link from "next/link";
import { SignUp } from "@/components/auth/clerk-safe";
import { safeRelativePath } from "@/lib/auth-redirect";
import { ReferralCapture } from "@/src/features/onboarding/ReferralCapture";
import { normalizeReferralCode } from "@/src/features/onboarding/referral-capture";
import { OFFER } from "@/lib/offer";
import { isStyleId } from "@/lib/styles/catalog";

export const metadata: Metadata = {
  title: "Sign up",
  description:
    "Create a Menivor account, paste a link or type a topic, and get three vertical reels with AI voiceover and word-by-word captions.",
  alternates: { canonical: "/sign-up" },
  // Auth pages stay out of the index (robots.txt also disallows them).
  robots: { index: false, follow: true },
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

/**
 * Sign-up. Every new account goes through `/onboarding` (the $1 card check
 * that unlocks the free reels, plus silent referral redemption) before
 * landing on its destination (default: the create box). `?redirect_url=` (e.g. from a pricing "Create an account to
 * buy" CTA) is carried through as onboarding's `next`; `?ref=` is persisted
 * client-side so the referral survives the Clerk round-trip.
 */
export default async function SignUpPage({
  searchParams,
}: Readonly<{ searchParams: SearchParams }>) {
  const params = await searchParams;
  // The landing box submits `?q=<link or topic>`: after sign-up and the card
  // check, the create box starts the reels from it without another question.
  const pasted = first(params.q).trim().slice(0, 600);
  // A style picked on the landing page (`?preset=`) is preselected in the box.
  const preset = first(params.preset).trim();
  const createQuery = new URLSearchParams();
  if (pasted) {
    createQuery.set("q", pasted);
    createQuery.set("auto", "1");
  }
  if (isStyleId(preset)) createQuery.set("preset", preset);
  const fromBox = createQuery.size > 0 ? `/create?${createQuery.toString()}` : "/create";
  const next = safeRelativePath(
    first(params.redirect_url),
    fromBox,
    (await headers()).get("host"),
  );
  const referralCode = normalizeReferralCode(first(params.ref));
  const onboardingUrl = `/onboarding?next=${encodeURIComponent(next)}`;
  const signInUrl = `/sign-in?redirect_url=${encodeURIComponent(next)}`;

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 p-6">
      {referralCode && (
        <>
          <ReferralCapture code={referralCode} />
          <p className="max-w-sm text-center text-sm text-muted-foreground">
            You were invited to Menivor. Create your account and your referral
            bonus is applied automatically.
          </p>
        </>
      )}
      <div className="max-w-sm text-center">
        <h1 className="text-xl font-semibold">Create your free account</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          One click with Google or Apple. {OFFER.signupNext}
        </p>
      </div>
      <SignUp
        signInUrl={signInUrl}
        forceRedirectUrl={onboardingUrl}
        appearance={{
          layout: { socialButtonsPlacement: "top", socialButtonsVariant: "blockButton" },
        }}
      />
      <p className="max-w-sm text-center text-xs text-muted-foreground">
        By creating an account you agree to the{" "}
        <Link href="/terms" className="underline underline-offset-4">
          Terms of Service
        </Link>
        ,{" "}
        <Link href="/legal/acceptable-use" className="underline underline-offset-4">
          Acceptable Use Policy
        </Link>{" "}
        and{" "}
        <Link href="/privacy" className="underline underline-offset-4">
          Privacy Policy
        </Link>
        . No NSFW, deepfake or impersonation content.
      </p>
    </main>
  );
}
