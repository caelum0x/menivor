"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowUpRight,
  Bell,
  CircleUserRound,
  Coins,
  CreditCard,
  Film,
  Gauge,
  Gift,
  KeyRound,
  Plug,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  Wallet,
} from "lucide-react";
import { signInHref, signUpHref } from "@/lib/auth-redirect";
import { LEGAL_CONTACT_EMAIL } from "@/components/marketing/LegalPage";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AccountNav } from "@/components/account/AccountNav";
import { AppHeader } from "@/components/account/AppHeader";
import { ProfileForm } from "@/components/account/ProfileForm";
import { useMyProfile } from "@/components/account/use-my-profile";

interface QuickLink {
  href: string;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
}

const QUICK_LINKS: readonly QuickLink[] = [
  {
    href: "/wallet",
    label: "Wallet & credits",
    description: "Balance, credit activity and one-off credit packs.",
    icon: Wallet,
  },
  {
    href: "/billing",
    label: "Workspace plan",
    description: "Subscriptions, plan usage, invoices and cancellation.",
    icon: CreditCard,
  },
  {
    href: "/spend",
    label: "Spend controls",
    description: "Budgets and limits on what renders can spend.",
    icon: SlidersHorizontal,
  },
  {
    href: "/workspace",
    label: "Team workspaces",
    description: "Create teams, invite members, share credits.",
    icon: Users,
  },
  {
    href: "/referral",
    label: "Referrals",
    description: "Invite friends and earn bonus credits.",
    icon: Gift,
  },
  {
    href: "/notifications",
    label: "Notifications",
    description: "Render results, mentions and account alerts.",
    icon: Bell,
  },
  {
    href: "/connections",
    label: "Connections",
    description: "Link social accounts to publish your reels.",
    icon: Plug,
  },
  {
    href: "/account/api-keys",
    label: "API keys",
    description: "Mint and revoke personal keys for the REST API.",
    icon: KeyRound,
  },
  {
    href: "/usage",
    label: "API usage",
    description: "Requests and spend per API key.",
    icon: Gauge,
  },
  {
    href: "/settings/privacy",
    label: "Privacy & data",
    description: "Export your data, consent choices, delete account.",
    icon: ShieldCheck,
  },
];

/** Device-session guests carry a synthetic `device+…` email. */
function isGuestEmail(email: string): boolean {
  return email.startsWith("device+");
}

export default function AccountPage() {
  const { status, me, profile, errorMessage, saving, saveError, reload, save } =
    useMyProfile();

  return (
    <main className="min-h-dvh">
      <AppHeader />

      <section className="container py-10">
        <div className="mx-auto max-w-3xl">
          <div className="mb-6">
            <p className="text-sm font-medium text-muted-foreground">Account</p>
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <CircleUserRound className="size-7 text-primary" aria-hidden />
              Your account
            </h1>
            <p className="mt-2 text-muted-foreground">
              Manage your profile, credits and billing, teams, keys and
              privacy.
            </p>
          </div>

          <AccountNav />

          {status === "loading" && (
            <div className="space-y-6">
              <div className="grid gap-3 sm:grid-cols-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-24 w-full rounded-lg" />
                ))}
              </div>
              <Skeleton className="h-64 w-full rounded-lg" />
            </div>
          )}

          {status === "error" && (
            <Card className="border-destructive/40 bg-destructive/5">
              <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-3">
                  <AlertTriangle
                    className="mt-0.5 size-5 shrink-0 text-destructive"
                    aria-hidden
                  />
                  <div>
                    <p className="font-medium">Couldn&apos;t load your account</p>
                    <p className="text-sm text-muted-foreground">
                      {errorMessage}
                    </p>
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={reload}>
                  <RefreshCw className="size-4" aria-hidden /> Try again
                </Button>
              </CardContent>
            </Card>
          )}

          {status === "ready" && me && (
            <div className="space-y-8">
              {isGuestEmail(me.email) && (
                <Card className="border-primary/40 bg-primary/5">
                  <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="font-medium">You&apos;re using a guest session</p>
                      <p className="text-sm text-muted-foreground">
                        Everything here is saved only in this browser. Create a
                        free account to keep your reels and credits everywhere.
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <Button asChild size="sm">
                        <Link href={signUpHref("/account")}>Create account</Link>
                      </Button>
                      <Button asChild variant="outline" size="sm">
                        <Link href={signInHref("/account")}>Sign in</Link>
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}
              <div className="grid gap-3 sm:grid-cols-3">
                <StatCard
                  icon={CircleUserRound}
                  label={isGuestEmail(me.email) ? "Account" : "Signed in as"}
                  value={isGuestEmail(me.email) ? "Guest (this browser)" : me.email}
                  mono={!isGuestEmail(me.email)}
                />
                <StatCard
                  icon={Coins}
                  label="Credits"
                  value={me.credits.toLocaleString()}
                />
                <StatCard
                  icon={Film}
                  label="Reels created"
                  value={me.jobs_count.toLocaleString()}
                />
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <CircleUserRound className="size-5 text-primary" aria-hidden />
                    Public profile
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ProfileForm
                    profile={profile}
                    saving={saving}
                    saveError={saveError}
                    onSave={save}
                  />
                </CardContent>
              </Card>

              <div className="grid gap-3 sm:grid-cols-3">
                {QUICK_LINKS.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="group flex flex-col gap-2 rounded-lg border border-border p-4 transition-colors hover:border-primary hover:bg-primary/5"
                  >
                    <span className="flex items-center justify-between">
                      <link.icon className="size-5 text-primary" aria-hidden />
                      <ArrowUpRight
                        className="size-4 text-muted-foreground transition-colors group-hover:text-primary"
                        aria-hidden
                      />
                    </span>
                    <span className="font-medium">{link.label}</span>
                    <span className="text-sm text-muted-foreground">
                      {link.description}
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}
          <p className="mt-10 text-sm text-muted-foreground">
            Need help? Email{" "}
            <a
              href={`mailto:${LEGAL_CONTACT_EMAIL}`}
              className="font-medium text-primary underline underline-offset-4"
            >
              {LEGAL_CONTACT_EMAIL}
            </a>
            . Read our{" "}
            <Link href="/legal/acceptable-use" className="underline underline-offset-4">
              Acceptable Use Policy
            </Link>
            .
          </p>
        </div>
      </section>
    </main>
  );
}

interface StatCardProps {
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  label: string;
  value: string;
  mono?: boolean;
}

function StatCard({ icon: Icon, label, value, mono }: Readonly<StatCardProps>) {
  return (
    <Card>
      <CardContent className="space-y-1 p-4">
        <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Icon className="size-3.5" aria-hidden />
          {label}
        </span>
        <p
          className={
            mono
              ? "truncate font-mono text-sm"
              : "text-2xl font-bold tracking-tight"
          }
          title={mono ? value : undefined}
        >
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
