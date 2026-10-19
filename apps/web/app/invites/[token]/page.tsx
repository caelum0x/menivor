import { redirect } from "next/navigation";

/** Legacy path: the canonical accept link is /invite/{token} (API accept_url + mobile app link). */
export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  redirect(`/invite/${encodeURIComponent(token)}`);
}
