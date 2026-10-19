import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { MonthHome } from "@/components/month/MonthHome";

export const metadata: Metadata = {
  title: "A month of posts from your website",
  description:
    "Add your website and get 30 posts in proven viral formats: carousels and reels. Swipe right on the ones you like and they are made in your brand.",
  robots: { index: false, follow: false },
};

type Search = { url?: string | string[] };

export default async function MonthPage({ searchParams }: Readonly<{ searchParams: Promise<Search> }>) {
  const query = await searchParams;
  const url = (Array.isArray(query.url) ? query.url[0] : query.url) ?? "";
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-3xl py-12">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold tracking-tight">A month of posts from your website</h1>
          <p className="mt-2 text-muted-foreground">
            Add your website. Swipe right on the posts you like. We make them in your brand.
          </p>
        </div>
        <MonthHome initialUrl={url.slice(0, 300)} />
      </section>
    </main>
  );
}
