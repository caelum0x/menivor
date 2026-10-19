import { redirect } from "next/navigation";

type SearchParams = Record<string, string | string[] | undefined>;

function toQuery(params: SearchParams): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v));
    else if (value !== undefined) search.set(key, value);
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/**
 * `/dashboard` is a stable alias (sign-in/up, billing and onboarding return
 * here): the canonical reel library lives at `/reels`. Query params are kept.
 */
export default async function DashboardPage({
  searchParams,
}: Readonly<{ searchParams: Promise<SearchParams> }>): Promise<never> {
  redirect(`/reels${toQuery(await searchParams)}`);
}
