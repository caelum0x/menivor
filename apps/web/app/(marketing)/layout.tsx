import Link from "next/link";
import { Navbar } from "@/components/marketing/Navbar";
import { NewsletterForm } from "@/components/marketing/NewsletterForm";
import {
  INDEPENDENT_PRODUCT_DISCLOSURE,
  LEGAL_CONTACT_EMAIL,
} from "@/components/marketing/LegalPage";
import { getLaunchPosture } from "@/src/shared/launch-posture/server";
import { WAITLIST_ANCHOR } from "@/lib/waitlist";
import { getTranslations } from "@/lib/i18n/server";
import type { TranslationKey } from "@/lib/i18n/translator";

type FooterLink =
  | { readonly href: string; readonly labelKey: TranslationKey }
  | { readonly href: string; readonly label: string };

const BASE_FOOTER_LINKS: readonly FooterLink[] = [
  { href: "/#how-it-works", labelKey: "footer.howItWorks" },
  { href: "/styles", label: "Styles" },
  { href: "/pricing", labelKey: "footer.pricing" },
  { href: "/for", labelKey: "footer.platforms" },
  { href: "/make", labelKey: "footer.make" },
  { href: "/video-ads", label: "Video ads by business" },
  { href: "/tools", labelKey: "footer.tools" },
  { href: "/guides", labelKey: "footer.guides" },
  { href: "/features", labelKey: "footer.features" },
  { href: "/providers", labelKey: "footer.providers" },
  { href: "/integrations", label: "Integrations" },
  { href: "/mcp", label: "MCP server" },
  { href: "/made-with-menivor", label: "Made with Menivor" },
  { href: "/creator-contract", label: "Creator Contract" },
  { href: "/terms", labelKey: "footer.terms" },
  { href: "/privacy", labelKey: "footer.privacy" },
  { href: "/refunds", labelKey: "footer.refunds" },
  { href: "/legal/acceptable-use", label: "Acceptable use" },
  { href: "/contact", labelKey: "footer.contact" },
];

// While the waitlist is the only working entry point, don't advertise a dead
// sign-in page; the link returns once the launch status leaves waitlist mode.
function footerLinks(waitlist: boolean): readonly FooterLink[] {
  return [
    ...BASE_FOOTER_LINKS,
    waitlist
      ? { href: `/#${WAITLIST_ANCHOR}`, labelKey: "footer.waitlist" }
      : { href: "/sign-in", labelKey: "footer.signIn" },
  ];
}

/**
 * Shared chrome for the public marketing surface. Wraps every marketing page
 * with the responsive navbar and a flat, ruled footer index while the root
 * layout supplies ClerkProvider and global styles.
 */
export default async function MarketingLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const t = await getTranslations();
  const posture = await getLaunchPosture();
  return (
    <div className="flex min-h-dvh flex-col">
      <Navbar launchMode={posture.mode} />
      <main className="flex-1">{children}</main>

      <footer className="border-t border-white/[0.08] bg-black/25">
        <div className="container flex flex-col gap-6 py-10 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex flex-col gap-2">
            <Link
              href="/"
              className="font-display text-sm font-bold tracking-tight text-foreground"
            >
              Menivor
            </Link>
            <p className="kicker text-muted-foreground">{t("footer.tagline")}</p>
            <NewsletterForm className="mt-4" />
          </div>
          <nav className="grid grid-cols-2 gap-x-10 gap-y-2 sm:grid-cols-3">
            {footerLinks(posture.mode === "waitlist").map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {"label" in link ? link.label : t(link.labelKey)}
              </Link>
            ))}
          </nav>
          <span className="text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()} Menivor
          </span>
        </div>
        <div className="container flex flex-col gap-2 border-t border-white/[0.06] py-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-2xl">{INDEPENDENT_PRODUCT_DISCLOSURE}</p>
          <a
            href={`mailto:${LEGAL_CONTACT_EMAIL}`}
            className="transition-colors hover:text-foreground"
          >
            {LEGAL_CONTACT_EMAIL}
          </a>
        </div>
      </footer>
    </div>
  );
}
