import type { Metadata } from "next";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { AvatarDetail } from "@/components/catalog/AvatarDetail";

interface PageProps {
  /** Next.js 15 passes dynamic params as a Promise. */
  readonly params: Promise<{ avatarId: string }>;
}

export const metadata: Metadata = {
  title: "Avatar",
  description: "Presenter avatar details.",
};

/** Detail view for one avatar (resolved from GET /avatars by id). */
export default async function AvatarDetailPage({ params }: PageProps) {
  const { avatarId } = await params;
  const decoded = decodeURIComponent(avatarId);

  return (
    <CatalogShell
      title="Avatar"
      description="Everything about this presenter avatar, and where to use it."
      backHref="/catalog/avatars"
      backLabel="Avatars"
    >
      <AvatarDetail avatarId={decoded} />
    </CatalogShell>
  );
}
