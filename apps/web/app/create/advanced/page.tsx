import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, Clapperboard } from "lucide-react";
import { CreateTabs } from "@/src/features/quick-create";
import { getTranslations } from "@/lib/i18n/server";
import { AupNotice } from "@/components/legal/AupNotice";

export const metadata: Metadata = {
  title: "More ways to create",
  description:
    "Turn your own narration into a captioned 9:16 reel with no presenter or voice provider, or generate an AI video clip from a text prompt or image.",
};

/**
 * `/create/advanced` — the hands-on create tools that used to be the default
 * `/create`: a captioned reel from your own narration (no provider keys) and
 * the text/image to AI video tab. The default `/create` is now the one-box
 * topic-or-link flow.
 */
export default async function AdvancedCreatePage() {
  const t = await getTranslations();
  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <Clapperboard className="size-5 text-primary" aria-hidden />
            {t("common.menivor")}
          </Link>
          <nav className="flex items-center gap-4 text-sm text-muted-foreground">
            <Link href="/create" className="inline-flex items-center gap-1 hover:text-foreground">
              <ArrowLeft className="size-3.5" aria-hidden /> Topic or link
            </Link>
            <Link href="/create/templates" className="hover:text-foreground">
              {t("create.navFromTemplate")}
            </Link>
            <Link href="/new" className="hover:text-foreground">
              {t("create.navGuidedWizard")}
            </Link>
            <Link href="/reels" className="hover:text-foreground">
              {t("create.navMyReels")}
            </Link>
            <Link href="/settings/provider-keys" className="hover:text-foreground">
              Your provider keys
            </Link>
          </nav>
        </div>
      </header>

      <section className="container max-w-3xl py-10">
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight">{t("create.title")}</h1>
          <p className="mt-2 text-muted-foreground">{t("create.subtitle")}</p>
        </div>
        <CreateTabs />
        <AupNotice className="mt-8 text-center text-xs text-muted-foreground" />
      </section>
    </main>
  );
}
