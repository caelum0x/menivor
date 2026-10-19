import type { Metadata } from "next";

import { ApiRefPage } from "@/src/features/api-docs/ApiRefPage";

export const metadata: Metadata = {
  title: "API reference — Menivor",
  description:
    "Menivor public API reference: reels create/status, templates catalog, live trends feed, and creator analytics. Rendered from a typed static data module — no network calls needed to view the docs.",
};

/**
 * API reference — rendered from lib/api-catalog.ts (static typed data).
 *
 * Endpoints documented:
 *   POST  /jobs              create a reel job
 *   GET   /jobs/{id}         get job status + presigned result URL
 *   GET   /jobs              list caller's jobs
 *   GET   /templates         list shot-templates
 *   GET   /templates/{slug}  get template detail
 *   GET   /trends/recommended live ranked trends
 *   GET   /me/analytics      creator BI dashboard
 */
export default function ApiDocsRoute() {
  return <ApiRefPage />;
}
