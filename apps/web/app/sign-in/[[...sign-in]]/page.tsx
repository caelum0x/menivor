import type { Metadata } from "next";
import { headers } from "next/headers";
import { SignIn } from "@/components/auth/clerk-safe";
import { safeRelativePath } from "@/lib/auth-redirect";

export const metadata: Metadata = {
  title: "Sign in",
  description:
    "Sign in to Menivor to see your reels and make new ones from a link or a topic.",
  alternates: { canonical: "/sign-in" },
  // Auth pages stay out of the index (robots.txt also disallows them).
  robots: { index: false, follow: true },
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * Sign-in. Returns the user to a validated same-origin `?redirect_url=` (for
 * example the pricing page they were buying from), otherwise the reels library.
 * The sign-up link carries the same destination so onboarding can hand off.
 */
export default async function SignInPage({
  searchParams,
}: Readonly<{ searchParams: SearchParams }>) {
  const params = await searchParams;
  const raw = Array.isArray(params.redirect_url)
    ? params.redirect_url[0]
    : params.redirect_url;
  const next = safeRelativePath(raw, "/reels", (await headers()).get("host"));
  const signUpUrl =
    next === "/reels"
      ? "/sign-up"
      : `/sign-up?redirect_url=${encodeURIComponent(next)}`;

  return (
    <main className="flex min-h-dvh items-center justify-center p-6">
      <SignIn signUpUrl={signUpUrl} forceRedirectUrl={next} />
    </main>
  );
}
