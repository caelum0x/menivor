import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { OneFlowCreate } from "@/src/features/create-compose";
import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { AupNotice } from "@/components/legal/AupNotice";

export const metadata: Metadata = {
  title: "Make 3 reels from a topic or link",
  description:
    "Type a topic or paste a product page link and Menivor renders three 9:16 reel variants, each with a different opening hook, ready to pick, edit, publish or download.",
  alternates: { canonical: "/create" },
};

type CreateSearchParams = {
  template?: string | string[];
  q?: string | string[];
  preset?: string | string[];
  auto?: string | string[];
};

function first(value: string | string[] | undefined): string {
  return ((Array.isArray(value) ? value[0] : value) ?? "").trim();
}

/**
 * `/create` — the ONE default create flow. Topic or link in, three reel
 * variants out. The hands-on tools (own narration, AI clip, templates, the
 * step-by-step wizard) stay one click away under "More ways to create".
 */
export default async function CreateReelPage({
  searchParams,
}: Readonly<{
  searchParams: Promise<CreateSearchParams>;
}>) {
  // Template deep links (`/create?template=slug`, used by older links and
  // shared URLs) belong to the template compose flow.
  const query = await searchParams;
  const template = first(query.template);
  if (template) {
    redirect(`/create/templates?template=${encodeURIComponent(template)}`);
  }
  return (
    <main className="min-h-dvh">
      <AppTopBar />

      <section className="container max-w-3xl py-10">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold tracking-tight">
            One topic or link. Three reels.
          </h1>
          <p className="mt-2 text-muted-foreground">
            Paste it below. We write, voice and cut three versions for you.
          </p>
        </div>
        <OneFlowCreate
          initialInput={first(query.q).slice(0, 600)}
          initialPreset={first(query.preset)}
          autoStart={first(query.auto) === "1" && Boolean(first(query.q))}
        />
        <AupNotice className="mt-4 text-center text-xs text-muted-foreground" />
        <p className="mt-10 text-center text-xs text-muted-foreground">
          <Link href="/month" className="underline underline-offset-4">
            A month of posts from your website
          </Link>
          {" · "}
          <Link href="/create/advanced" className="underline underline-offset-4">
            More ways to create
          </Link>
          {" · "}
          <Link href="/very-time" className="underline underline-offset-4">Very ___ Time</Link>
          {" · "}
          <Link href="/presets-gallery" className="underline underline-offset-4">Presets</Link>
          {" · "}
          Credits never expire, failed renders are refunded automatically, and we
          never train on your content.{" "}
          <Link href="/creator-contract" className="underline underline-offset-4">
            Read the Creator Contract
          </Link>
          .
        </p>
      </section>
    </main>
  );
}
