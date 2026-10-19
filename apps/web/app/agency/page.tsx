import Link from "next/link";
import { UserButton } from "@/components/auth/clerk-safe";
import { Briefcase, KeyRound, Calculator, Building2, Image as ImageIcon, TrendingUp } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

const CARDS = [
  { href: "/agency/clients", title: "Clients", blurb: "Manage client accounts, each with its own shared credit pool.", Icon: Building2 },
  { href: "/agency/keys", title: "Client keys", blurb: "Mint per-client resale keys with a daily cap and markup.", Icon: KeyRound },
  { href: "/agency/margin", title: "Margin calculator", blurb: "Model your markup, min fee, and projected monthly margin.", Icon: Calculator },
  { href: "/agency/branding", title: "White-label branding", blurb: "Set the watermark applied to every client\u2019s output.", Icon: ImageIcon },
  { href: "/agency/revenue", title: "Revenue", blurb: "Projected monthly margin across your active client keys.", Icon: TrendingUp },
];

/** Agency console — resell ReelForge generation to clients under your own keys. */
export default function AgencyPage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Briefcase className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Agency</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <p className="mb-6 text-sm text-muted-foreground">
        Resell generation to your clients — set a daily spend cap and a markup; billed only on success.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        {CARDS.map(({ href, title, blurb, Icon }) => (
          <Link key={href} href={href} className="group block">
            <Card className="h-full transition-colors group-hover:border-primary">
              <CardContent className="flex h-full flex-col gap-2 py-5">
                <div className="flex items-center gap-2">
                  <Icon className="h-5 w-5 text-primary" aria-hidden />
                  <h3 className="font-semibold">{title}</h3>
                </div>
                <p className="flex-1 text-sm text-muted-foreground">{blurb}</p>
                <span className="text-sm text-primary group-hover:underline">Open →</span>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </main>
  );
}
