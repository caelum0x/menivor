import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import {
  SITE_URL,
  breadcrumbLd,
  compactSeoDescription,
  graphDocument,
  itemListLd,
} from "@/lib/seo";
import { BYOK_PROVIDERS } from "@/lib/byok";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";

const TITLE = "Menivor integrations: API, MCP, webhooks, publishing and more";
const DESCRIPTION = compactSeoDescription(
  "Every way to connect Menivor: TikTok, Instagram and YouTube publishing, the REST API, signed webhooks, a remote MCP server for AI agents, the free Chop desktop editor, and your own provider keys.",
);

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/integrations" },
  openGraph: { type: "website", url: `${SITE_URL}/integrations`, siteName: "Menivor", title: TITLE, description: DESCRIPTION },
};

interface Integration {
  readonly name: string;
  readonly body: string;
  readonly href: string;
  readonly cta: string;
}

const GROUPS: ReadonlyArray<{ readonly title: string; readonly items: readonly Integration[] }> = [
  {
    title: "Publish and schedule",
    items: [
      {
        name: "TikTok, Instagram and YouTube Shorts",
        body: "Connect your accounts once, then publish a finished reel or schedule it for a future time.",
        href: "/connections",
        cta: "Connect accounts",
      },
      {
        name: "Content calendar",
        body: "See scheduled posts across platforms and move them around.",
        href: "/calendar",
        cta: "Open the calendar",
      },
    ],
  },
  {
    title: "Build on Menivor",
    items: [
      {
        name: "REST API",
        body: "Create reels, poll jobs, upload media and read performance over HTTPS with an x-api-key header.",
        href: "/api-docs",
        cta: "Read the API reference",
      },
      {
        name: "Personal API keys",
        body: "Mint and revoke keys for scripts, the MCP server and the Chop editor.",
        href: "/account/api-keys",
        cta: "Manage API keys",
      },
      {
        name: "Webhooks",
        body: "Get signed callbacks when a job finishes or fails, with delivery history and test sends.",
        href: "/developer",
        cta: "Set up webhooks",
      },
      {
        name: "MCP server for AI agents",
        body: "Let Claude, Cursor or the OpenAI Responses API create reels, quote prices and schedule posts.",
        href: "/mcp",
        cta: "Connect an agent",
      },
    ],
  },
  {
    title: "Edit and import",
    items: [
      {
        name: "Chop, the Menivor editor",
        body: "Free desktop editor for macOS, Windows and Linux. Open a Menivor reel to fine-tune it, add captions and voiceover, and send the result back.",
        href: "/editor",
        cta: "Get Chop",
      },
      {
        name: "Import from a URL",
        body: "Paste a product or article link and get a hook-first reel draft from its content.",
        href: "/import",
        cta: "Import a URL",
      },
    ],
  },
  {
    title: "Providers and accounts",
    items: [
      {
        name: "Bring your own provider keys",
        body: `Route generation through your own ${BYOK_PROVIDERS.slice(0, 6)
          .map((provider) => provider.name)
          .join(", ")} and other accounts for a metered routing fee.`,
        href: "/settings/provider-keys",
        cta: "Add provider keys",
      },
      {
        name: "SSO and SCIM",
        // MN7a: SSO is set up per team on Enterprise until self-serve SSO ships.
        body: "Single sign-on and SCIM provisioning for teams on Enterprise plans.",
        href: "/settings/sso",
        cta: "Contact sales",
      },
      {
        name: "Model catalog",
        body: "Compare the video, voice and image models Menivor routes to, with per-unit prices.",
        href: "/models",
        cta: "Browse models",
      },
    ],
  },
];

export default function IntegrationsPage() {
  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Integrations", path: "/integrations" },
  ];
  const all = GROUPS.flatMap((group) => group.items);
  const jsonLd = graphDocument([
    breadcrumbLd(crumbs),
    itemListLd(all.map((item) => ({ name: item.name, path: item.href }))),
  ]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />
      <div className="mx-auto max-w-5xl">
        <Breadcrumbs crumbs={crumbs} />
        <h1 className="text-balance text-4xl font-bold tracking-tight sm:text-5xl">Integrations</h1>
        <p className="mt-4 max-w-2xl text-pretty text-lg text-muted-foreground">
          Everything Menivor connects to today, each with the page where you set it up.
        </p>

        {GROUPS.map((group) => (
          <section key={group.title} className="mt-12">
            <h2 className="mb-4 text-2xl font-bold tracking-tight">{group.title}</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              {group.items.map((item) => (
                <Link
                  key={item.name}
                  href={item.href}
                  className="group flex flex-col rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/60"
                >
                  <h3 className="font-semibold text-foreground">{item.name}</h3>
                  <p className="mt-1.5 flex-1 text-sm text-pretty text-muted-foreground">{item.body}</p>
                  <span className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-primary">
                    {item.cta}
                    <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
                  </span>
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
