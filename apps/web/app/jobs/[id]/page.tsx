import { redirect } from "next/navigation";

/**
 * `/jobs/{id}` is kept as a stable alias (notifications, editor exports and
 * older links point here); the canonical reel detail page is `/reels/{id}`.
 */
export default async function JobDetailAliasPage({
  params,
}: Readonly<{ params: Promise<{ id: string }> }>): Promise<never> {
  const { id } = await params;
  redirect(`/reels/${encodeURIComponent(id)}`);
}
