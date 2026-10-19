"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import { SignedIn, SignedOut, UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import { WAITLIST_ANCHOR } from "@/lib/waitlist";
import { useTranslations } from "@/lib/i18n/context";
import type { TranslationKey } from "@/lib/i18n/translator";
import { cn } from "@/lib/utils";
import { MenivorMark } from "@/components/brand/MenivorMark";
import type { LaunchMode } from "@/src/shared/launch-posture";

interface NavLink {
  readonly href: string;
  readonly labelKey: TranslationKey;
}

const NAV_LINKS: readonly NavLink[] = [
  { href: "/styles", labelKey: "nav.styles" },
  { href: "/#how-it-works", labelKey: "nav.howItWorks" },
  { href: "/showcase", labelKey: "nav.showcase" },
  { href: "/tools", labelKey: "nav.freeTools" },
  { href: "/pricing", labelKey: "nav.pricing" },
];

const WAITLIST_HREF = `/#${WAITLIST_ANCHOR}`;

/** Brand wordmark: plain display-face type, no icon badge. */
function Wordmark({
  onClick,
  homeLabel,
}: {
  readonly onClick?: () => void;
  readonly homeLabel: string;
}) {
  return (
    <Link
      href="/"
      onClick={onClick}
      aria-label={homeLabel}
      className="flex items-center rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <MenivorMark variant="gradient" className="size-8" title="Menivor" />
    </Link>
  );
}

/** Signed-out primary action per launch mode (see src/shared/launch-posture). */
function primaryAction(mode: LaunchMode): NavLink {
  if (mode === "public") return { href: "/sign-up", labelKey: "nav.startFree" };
  if (mode === "beta") return { href: "/beta", labelKey: "nav.requestAccess" };
  return { href: WAITLIST_HREF, labelKey: "nav.joinWaitlist" };
}

/**
 * Marketing site header. Sticky, hairline-ruled, fully responsive. The
 * signed-out actions follow the server-read launch mode: waitlist only (no
 * dead sign-in link) in waitlist mode, otherwise sign-in plus free signup
 * (public) or an early-access request (private beta).
 */
export function Navbar({ launchMode = "waitlist" }: Readonly<{ launchMode?: LaunchMode }>) {
  const waitlist = launchMode === "waitlist";
  const primary = primaryAction(launchMode);
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  const pathname = usePathname();
  const t = useTranslations();

  const isActive = (href: string) =>
    href.startsWith("/#") ? false : pathname === href;

  return (
    <header className="glass-bar sticky top-0 z-50 border-b">
      <div className="container flex h-16 items-center justify-between gap-4">
        <Wordmark onClick={close} homeLabel={t("nav.homeAria")} />

        <nav className="hidden items-center gap-1 md:flex">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={isActive(link.href) ? "page" : undefined}
              className={cn(
                "rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive(link.href)
                  ? "bg-white/[0.07] text-foreground shadow-[inset_0_1px_0_hsl(0_0%_100%/0.06)]"
                  : "text-muted-foreground hover:bg-white/[0.05] hover:text-foreground",
              )}
            >
              {t(link.labelKey)}
            </Link>
          ))}
        </nav>

        <div className="hidden items-center gap-2 md:flex">
          <LanguageSwitcher />
          <SignedOut>
            {waitlist ? (
              <Button asChild size="sm">
                <Link href={primary.href}>{t(primary.labelKey)}</Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="ghost" size="sm">
                  <Link href="/sign-in">{t("nav.signIn")}</Link>
                </Button>
                <Button asChild size="sm">
                  <Link href={primary.href}>{t(primary.labelKey)}</Link>
                </Button>
              </>
            )}
          </SignedOut>
          <SignedIn>
            <Button asChild variant="ghost" size="sm">
              <Link href="/reels">{t("common.myReels")}</Link>
            </Button>
            <NotificationBell />
            <UserButton afterSignOutUrl="/" />
          </SignedIn>
        </div>

        <div className="flex items-center gap-2 md:hidden">
          <LanguageSwitcher />
          <SignedIn>
            <NotificationBell />
            <UserButton afterSignOutUrl="/" />
          </SignedIn>
          <Button
            variant="ghost"
            size="icon"
            aria-label={open ? t("nav.closeMenu") : t("nav.openMenu")}
            aria-expanded={open}
            onClick={() => setOpen((prev) => !prev)}
          >
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </Button>
        </div>
      </div>

      <div
        className={cn(
          "overflow-hidden border-white/[0.08] transition-[max-height] duration-300 ease-out md:hidden",
          open ? "max-h-96 border-t" : "max-h-0",
        )}
      >
        <nav className="container flex flex-col gap-0.5 py-4">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={close}
              aria-current={isActive(link.href) ? "page" : undefined}
              className={cn(
                "rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
                isActive(link.href)
                  ? "bg-white/[0.07] text-foreground"
                  : "text-muted-foreground hover:bg-white/[0.06] hover:text-foreground",
              )}
            >
              {t(link.labelKey)}
            </Link>
          ))}
          <div className="mt-3 flex flex-col gap-2 border-t border-border pt-4">
            <SignedOut>
              {waitlist ? (
                <Button asChild size="sm" className="w-full">
                  <Link href={primary.href} onClick={close}>
                    {t(primary.labelKey)}
                  </Link>
                </Button>
              ) : (
                <>
                  <Button asChild variant="outline" size="sm" className="w-full">
                    <Link href="/sign-in" onClick={close}>
                      {t("nav.signIn")}
                    </Link>
                  </Button>
                  <Button asChild size="sm" className="w-full">
                    <Link href={primary.href} onClick={close}>
                      {t(primary.labelKey)}
                    </Link>
                  </Button>
                </>
              )}
            </SignedOut>
            <SignedIn>
              <Button asChild size="sm" className="w-full">
                <Link href="/reels" onClick={close}>
                  {t("nav.goToReels")}
                </Link>
              </Button>
            </SignedIn>
          </div>
        </nav>
      </div>
    </header>
  );
}
