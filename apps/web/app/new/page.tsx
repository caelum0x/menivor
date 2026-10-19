import * as React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { Clapperboard } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";
import { Wizard } from "@/src/features/reel-create";
import { getTranslations } from "@/lib/i18n/server";
import { AupNotice } from "@/components/legal/AupNotice";

export const metadata: Metadata = {
  title: "New reel",
  description:
    "Create a new UGC avatar reel from a screen recording — script, voice, avatar, layout, and captions in one flow.",
};

export default async function NewReelPage() {
  const t = await getTranslations();
  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link href="/reels" className="flex items-center gap-2 font-semibold">
            <Clapperboard className="size-5 text-primary" aria-hidden />
            {t("common.menivor")}
          </Link>
          <UserButton />
        </div>
      </header>

      <section className="container py-10">
        <div className="mb-8 max-w-2xl">
          <h1 className="text-3xl font-bold tracking-tight">
            {t("newReel.title")}
          </h1>
          <p className="mt-2 text-muted-foreground">{t("newReel.subtitle")}</p>
        </div>

        <React.Suspense
          fallback={<p className="text-sm text-muted-foreground">Loading…</p>}
        >
          <Wizard />
        </React.Suspense>
        <AupNotice className="mt-8 text-xs text-muted-foreground" />
      </section>
    </main>
  );
}
