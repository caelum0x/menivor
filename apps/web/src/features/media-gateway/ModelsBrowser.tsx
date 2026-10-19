"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Boxes, ImageIcon, RefreshCw, Video } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { listMediaModels, priceLabel, type MediaModel, type Modality } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type Filter = "" | Modality;
type LoadState = "loading" | "ready" | "error";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "", label: "All" },
  { key: "video", label: "Video" },
  { key: "image", label: "Image" },
];

/** OpenRouter-style unified model catalog: one key + one balance, every model. */
export function ModelsBrowser() {
  const { getToken } = useAuth();
  const [state, setState] = React.useState<LoadState>("loading");
  const [models, setModels] = React.useState<MediaModel[]>([]);
  const [filter, setFilter] = React.useState<Filter>("");
  const [error, setError] = React.useState("");

  const load = React.useCallback(
    async (which: Filter) => {
      setState("loading");
      setError("");
      try {
        const token = (await getToken()) ?? undefined;
        const { models: rows } = await listMediaModels(which || undefined, { token });
        setModels(rows);
        setState("ready");
      } catch (err) {
        setError(friendlyErrorMessage(err, "Failed to load."));
        setState("error");
      }
    },
    [getToken],
  );

  React.useEffect(() => {
    void load(filter);
  }, [filter, load]);

  const providers = React.useMemo(
    () => new Set(models.map((m) => m.provider)).size,
    [models],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Models</h2>
          <p className="text-sm text-muted-foreground">
            {state === "ready"
              ? `${models.length} models across ${providers} providers — one key, one balance.`
              : "Unified image + video catalog."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {FILTERS.map((f) => (
            <Button
              key={f.key || "all"}
              size="sm"
              variant={filter === f.key ? "default" : "outline"}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </Button>
          ))}
          <Button size="sm" variant="ghost" onClick={() => void load(filter)} aria-label="Refresh">
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {state === "error" ? (
        <Card>
          <CardContent className="py-6 text-sm text-red-600">{error}</CardContent>
        </Card>
      ) : null}

      {state === "loading" ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {models.map((m) => (
            <ModelCard key={m.id} model={m} />
          ))}
          {state === "ready" && models.length === 0 ? (
            <Card className="sm:col-span-2 lg:col-span-3">
              <CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
                <Boxes className="h-4 w-4" /> No models for this filter.
              </CardContent>
            </Card>
          ) : null}
        </div>
      )}
    </div>
  );
}

function ModelCard({ model }: { model: MediaModel }) {
  const isVideo = model.modality === "video";
  return (
    <Card>
      <CardContent className="space-y-2 py-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            {isVideo ? (
              <Video className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ImageIcon className="h-4 w-4 text-muted-foreground" />
            )}
            <span className="font-mono text-sm font-medium">{model.id}</span>
          </div>
          <Badge variant="secondary">{model.modality}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">{model.description}</p>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Badge variant="outline">{model.provider}</Badge>
          <Badge variant="outline">{priceLabel(model)}</Badge>
          {isVideo && model.max_seconds ? (
            <Badge variant="outline">≤ {model.max_seconds}s</Badge>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
