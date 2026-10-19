"use client";

/**
 * Section 1: the 18-platform launch checklist. Filterable by category, with
 * a status toggle (not_started -> submitted -> live) per platform. Nothing
 * here submits anything on a directory — a human reports what they did.
 */

import * as React from "react";
import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { listLaunchPlatforms, setPlatformStatus, type LaunchPlatform } from "./api";
import {
  categoriesFromPlatforms,
  filterPlatformsByCategory,
  nextPlatformStatus,
  platformProgressLabel,
  platformStatusLabel,
  platformStatusTone,
} from "./view-model";

interface Props {
  readonly productName: string;
}

export function PlatformChecklist({ productName }: Props) {
  const getApiToken = useApiToken();
  const [platforms, setPlatforms] = React.useState<readonly LaunchPlatform[] | null>(null);
  const [category, setCategory] = React.useState("");
  const [error, setError] = React.useState("");
  const [busyId, setBusyId] = React.useState("");

  const load = React.useCallback(async () => {
    setError("");
    try {
      const token = await getApiToken();
      const overview = await listLaunchPlatforms({ productName: productName || undefined }, { token });
      setPlatforms(overview.platforms);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Launch directories could not be loaded."));
    }
  }, [getApiToken, productName]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const advance = async (platform: LaunchPlatform) => {
    if (!productName.trim()) {
      setError("Enter a product name above to track platform status.");
      return;
    }
    setBusyId(platform.id);
    try {
      const token = await getApiToken();
      const updated = await setPlatformStatus(
        { productName, platformId: platform.id, status: nextPlatformStatus(platform.status) },
        { token },
      );
      setPlatforms((current) =>
        current ? current.map((p) => (p.id === platform.id ? { ...p, ...updated } : p)) : current,
      );
    } catch (err) {
      setError(friendlyErrorMessage(err, "That status could not be saved."));
    } finally {
      setBusyId("");
    }
  };

  const categories = platforms ? categoriesFromPlatforms(platforms) : [];
  const visible = platforms ? filterPlatformsByCategory(platforms, category) : [];

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle>Launch platforms</CardTitle>
        {platforms ? (
          <span className="text-sm text-muted-foreground" data-testid="platform-progress">
            {platformProgressLabel(platforms)}
          </span>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          18 real launch directories. Mark what you actually submitted — nothing here submits for you.
        </p>
        {platforms ? (
          <Select
            aria-label="Filter by category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        ) : null}

        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}

        {!platforms ? (
          <Skeleton className="h-40 w-full" aria-busy />
        ) : (
          <ul className="divide-y divide-border">
            {visible.map((platform) => (
              <li key={platform.id} className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0">
                  <a
                    href={platform.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 font-medium hover:underline"
                  >
                    {platform.name} <ExternalLink className="size-3" aria-hidden />
                  </a>
                  <p className="text-sm text-muted-foreground">{platform.note}</p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busyId === platform.id}
                  onClick={() => void advance(platform)}
                  aria-label={`${platform.name} status: ${platformStatusLabel(platform.status)}`}
                >
                  <Badge variant={platformStatusTone(platform.status)}>
                    {busyId === platform.id ? "Saving..." : platformStatusLabel(platform.status)}
                  </Badge>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
