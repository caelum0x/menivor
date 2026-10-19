import type { Metadata } from "next";
import { safeRelativePath } from "@/lib/auth-redirect";
import { OnboardingFlow } from "@/src/features/onboarding/OnboardingFlow";

export const metadata: Metadata = {
  title: "Unlock your free reels",
  robots: { index: false, follow: false },
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function OnboardingPage({
  searchParams,
}: Readonly<{ searchParams: SearchParams }>) {
  const params = await searchParams;
  const raw = Array.isArray(params.next) ? params.next[0] : params.next;
  return <OnboardingFlow next={safeRelativePath(raw, "/create")} />;
}
