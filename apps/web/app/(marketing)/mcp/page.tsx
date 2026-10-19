import type { Metadata } from "next";
import Link from "next/link";
import {
  SITE_URL,
  breadcrumbLd,
  compactSeoDescription,
  faqPageLd,
  graphDocument,
  type FaqEntry,
} from "@/lib/seo";
import { listLiveTools } from "@/lib/mcp/tools";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { Breadcrumbs } from "@/components/marketing/seo/Breadcrumbs";
import { FaqSection } from "@/components/marketing/seo/FaqSection";

const ENDPOINT = `${SITE_URL}/api/mcp`;
const TITLE = "Menivor MCP server: make reels from Claude, Cursor and other agents";
const DESCRIPTION = compactSeoDescription(
  "Connect Claude Code, Claude Desktop, Cursor or any client that takes a remote MCP server to Menivor. Your agent makes reels and product ads, checks what a render will cost and downloads the finished MP4.",
);

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/mcp" },
  openGraph: { type: "website", url: `${SITE_URL}/mcp`, siteName: "Menivor", title: TITLE, description: DESCRIPTION },
};

const CLIENTS: ReadonlyArray<{ name: string; where: string; code: string }> = [
  {
    name: "Claude Code",
    where: "Run in your terminal:",
    code: `claude mcp add --transport http menivor ${ENDPOINT} \\\n  --header "Authorization: Bearer YOUR_MENIVOR_KEY"`,
  },
  {
    name: "Cursor",
    where: "Add to ~/.cursor/mcp.json (or .cursor/mcp.json in a project):",
    code: JSON.stringify(
      {
        mcpServers: {
          menivor: { url: ENDPOINT, headers: { Authorization: "Bearer YOUR_MENIVOR_KEY" } },
        },
      },
      null,
      2,
    ),
  },
  {
    name: "Claude Desktop",
    where:
      "Claude Desktop's config file starts local servers, so bridge to the remote endpoint with mcp-remote. Add to claude_desktop_config.json (needs Node.js):",
    code: JSON.stringify(
      {
        mcpServers: {
          menivor: {
            command: "npx",
            args: ["-y", "mcp-remote", ENDPOINT, "--header", "Authorization:${MENIVOR_AUTH}"],
            env: { MENIVOR_AUTH: "Bearer YOUR_MENIVOR_KEY" },
          },
        },
      },
      null,
      2,
    ),
  },
  {
    name: "Responses-style APIs",
    where: "APIs that accept a remote MCP tool in the request take Menivor like this:",
    code: JSON.stringify(
      {
        type: "mcp",
        server_label: "menivor",
        server_url: ENDPOINT,
        headers: { Authorization: "Bearer YOUR_MENIVOR_KEY" },
        require_approval: "always",
      },
      null,
      2,
    ),
  },
];

const FAQS: readonly FaqEntry[] = [
  {
    question: "What does the Menivor MCP server cost?",
    answer:
      "Connecting is free. Tools that render spend from your Menivor account exactly as the website does: one reel credit per reel, and wallet charges for metered generations. Quote tools and reads are free.",
  },
  {
    question: "Which key does the agent use?",
    answer:
      "A personal key you create on your API keys page while signed in. The agent can do what that key can do through the REST API. Revoke the key at any time to cut the agent off.",
  },
  {
    question: "Can the agent post to TikTok, Instagram or YouTube?",
    answer:
      "Not yet. Posting to social platforms is not open, so the agent makes the reel and you download the MP4 and post it yourself.",
  },
  {
    question: "Can I use it in chat apps whose connectors sign in with OAuth?",
    answer:
      "Not yet. This server authenticates with a key header, not OAuth. Use one of the configurations above.",
  },
];

function CodeBlock({ code }: { readonly code: string }) {
  return (
    <pre className="mt-2 overflow-x-auto rounded-md border border-border bg-secondary/40 p-4 font-mono text-xs leading-relaxed text-foreground">
      <code>{code}</code>
    </pre>
  );
}

export default function McpPage() {
  const tools = listLiveTools();
  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Integrations", path: "/integrations" },
    { name: "MCP server", path: "/mcp" },
  ];
  const jsonLd = graphDocument([breadcrumbLd(crumbs), faqPageLd(FAQS)]);

  return (
    <div className="container py-16 lg:py-20">
      <JsonLd data={jsonLd} />
      <article className="mx-auto max-w-3xl">
        <Breadcrumbs crumbs={crumbs} />
        <p className="kicker text-muted-foreground">Model Context Protocol</p>
        <h1 className="mt-3 text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          Make reels from your AI agent
        </h1>
        <p className="mt-4 text-pretty text-lg text-muted-foreground">
          Menivor runs a remote MCP server. Connect Claude, Cursor or any MCP
          client, then ask the agent to write a reel, turn a product page into
          ads, check what it will cost and fetch the finished MP4 to post
          yourself.
        </p>

        <section className="mt-10 rounded-xl border border-border bg-card p-5">
          <h2 className="text-lg font-semibold">Endpoint</h2>
          <CodeBlock code={ENDPOINT} />
          <p className="mt-3 text-sm text-muted-foreground">
            Streamable HTTP transport. Authenticate with{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
              Authorization: Bearer YOUR_MENIVOR_KEY
            </code>
            . The key comes from{" "}
            <Link href="/account/api-keys" className="text-primary underline underline-offset-4">
              your API keys page
            </Link>{" "}
            (signed in)
            . Registry manifest:{" "}
            <a href="/server.json" className="text-primary underline underline-offset-4">
              server.json
            </a>
            .
          </p>
        </section>

        <section className="mt-12">
          <h2 className="mb-4 text-2xl font-bold tracking-tight">Connect your client</h2>
          <div className="space-y-8">
            {CLIENTS.map((client) => (
              <div key={client.name}>
                <h3 className="font-semibold text-foreground">{client.name}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{client.where}</p>
                <CodeBlock code={client.code} />
              </div>
            ))}
          </div>
        </section>

        <section className="mt-12">
          <h2 className="mb-4 text-2xl font-bold tracking-tight">Tools</h2>
          <div className="divide-y divide-border rounded-xl border border-border">
            {tools.map((tool) => (
              <div key={tool.name} className="p-4">
                <p className="font-mono text-sm font-semibold text-foreground">{tool.name}</p>
                <p className="mt-1 text-sm text-muted-foreground">{tool.description}</p>
              </div>
            ))}
          </div>
        </section>

        <FaqSection faqs={FAQS} />
      </article>
    </div>
  );
}
