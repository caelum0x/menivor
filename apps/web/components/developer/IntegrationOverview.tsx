"use client";

import * as React from "react";
import {
  BookOpen,
  ExternalLink,
  FileJson,
  Gauge,
  KeyRound,
  Layers,
  Webhook,
} from "lucide-react";
import type { DeveloperPortal } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CopyBox } from "@/components/apikeys/CopyBox";
import { formatCount } from "@/components/developer/format";
import type { DeveloperPortalStatus } from "@/lib/use-developer-portal";

interface IntegrationOverviewProps {
  status: DeveloperPortalStatus;
  portal: DeveloperPortal | null;
  errorMessage: string;
}

/**
 * The developer-portal overview: caller-scoped footprint tiles (keys, requests
 * this month, webhook subscriptions, workspaces), the API base URL, and links to
 * the interactive API reference + machine-readable OpenAPI schema. READ-only and
 * secret-free.
 */
export function IntegrationOverview({
  status,
  portal,
  errorMessage,
}: IntegrationOverviewProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Layers className="size-5 text-primary" aria-hidden />
          Integration overview
        </CardTitle>
        <CardDescription>
          Your API footprint and the links you need to build against the
          Menivor REST API.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {status === "error" ? (
          <p className="text-sm text-destructive" role="alert">
            {errorMessage || "Couldn't load your developer portal."}
          </p>
        ) : status === "loading" || !portal ? (
          <div className="grid gap-3 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full rounded-lg" />
            ))}
          </div>
        ) : (
          <>
            <dl className="grid gap-3 sm:grid-cols-4">
              <StatTile
                icon={<KeyRound className="size-4" aria-hidden />}
                label="Active API keys"
                value={`${formatCount(portal.api_keys.active)} / ${formatCount(
                  portal.api_keys.total,
                )}`}
              />
              <StatTile
                icon={<Gauge className="size-4" aria-hidden />}
                label="Requests this month"
                value={formatCount(portal.api_keys.requests_this_month)}
              />
              <StatTile
                icon={<Webhook className="size-4" aria-hidden />}
                label="Webhook subscriptions"
                value={`${formatCount(portal.webhooks.active)} / ${formatCount(
                  portal.webhooks.total,
                )}`}
              />
              <StatTile
                icon={<Layers className="size-4" aria-hidden />}
                label="Workspaces"
                value={formatCount(portal.workspaces)}
              />
            </dl>

            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">
                API base URL
                {portal.api_version ? (
                  <Badge variant="outline" className="ml-2">
                    v{portal.api_version}
                  </Badge>
                ) : null}
              </p>
              <CopyBox
                value={portal.api_base_url}
                label="Copy API base URL"
              />
            </div>

            <div className="flex flex-wrap gap-2">
              {portal.docs_url ? (
                <Button asChild variant="outline" size="sm">
                  <a
                    href={portal.docs_url}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    <BookOpen className="size-4" aria-hidden /> API reference
                    <ExternalLink className="size-3.5" aria-hidden />
                  </a>
                </Button>
              ) : null}
              {portal.openapi_url ? (
                <Button asChild variant="outline" size="sm">
                  <a
                    href={portal.openapi_url}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    <FileJson className="size-4" aria-hidden /> OpenAPI schema
                    <ExternalLink className="size-3.5" aria-hidden />
                  </a>
                </Button>
              ) : null}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

interface StatTileProps {
  icon: React.ReactNode;
  label: string;
  value: string;
}

function StatTile({ icon, label, value }: StatTileProps) {
  return (
    <div className="rounded-lg border border-border bg-secondary/20 p-3">
      <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className="text-muted-foreground">{icon}</span>
        {label}
      </dt>
      <dd className="mt-1 text-xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
