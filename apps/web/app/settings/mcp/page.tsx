import type { Metadata } from "next";

import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { McpConnector } from "@/src/features/mcp-connector/McpConnector";

export const metadata: Metadata = {
  title: "MCP connector",
  description: "Connect an AI agent to Menivor with a workspace token.",
  robots: { index: false, follow: false },
};

export default function McpSettingsPage() {
  return (
    <main className="min-h-dvh">
      <SettingsHeader active="/settings/mcp" />
      <section className="container py-10">
        <div className="mx-auto max-w-5xl">
          <McpConnector />
        </div>
      </section>
    </main>
  );
}
