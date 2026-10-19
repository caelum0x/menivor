import type { Metadata } from "next";
import { EditorWorkspace } from "@/src/features/editor";
import { SITE_URL } from "@/lib/seo";
import MarketingLayout from "../(marketing)/layout";
import { CHOP_DESCRIPTION, CHOP_TITLE, ChopLanding } from "./_components/ChopLanding";

/** Re-read the release list at most once an hour. */
export const revalidate = 3600;

type EditorSearchParams = Promise<{ job?: string | string[] }>;

/**
 * `/editor` serves two audiences:
 * - with `?job=` (from a reel's Edit button, or empty for the reel picker):
 *   the in-browser timeline editor;
 * - without it: the public landing page for Chop, the desktop editor.
 */
export async function generateMetadata({
  searchParams,
}: Readonly<{ searchParams: EditorSearchParams }>): Promise<Metadata> {
  const query = await searchParams;
  if (query.job !== undefined) {
    return { title: "Editor", robots: { index: false, follow: false } };
  }
  return {
    title: { absolute: CHOP_TITLE },
    description: CHOP_DESCRIPTION,
    alternates: { canonical: "/editor" },
    openGraph: {
      type: "website",
      url: `${SITE_URL}/editor`,
      siteName: "Menivor",
      title: CHOP_TITLE,
      description: CHOP_DESCRIPTION,
    },
    twitter: { card: "summary_large_image", title: CHOP_TITLE, description: CHOP_DESCRIPTION },
  };
}

export default async function EditorPage({
  searchParams,
}: Readonly<{ searchParams: EditorSearchParams }>) {
  const query = await searchParams;
  if (query.job === undefined) {
    return (
      <MarketingLayout>
        <ChopLanding />
      </MarketingLayout>
    );
  }
  const rawJob = Array.isArray(query.job) ? query.job[0] : query.job;
  return <EditorWorkspace jobId={(rawJob || "").trim()} />;
}
