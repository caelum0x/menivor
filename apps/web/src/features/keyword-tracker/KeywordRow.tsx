"use client";

import * as React from "react";
import { ExternalLink, RefreshCw, X } from "lucide-react";
import type { TrackedKeyword } from "./api";
import { RankSparkline } from "./RankSparkline";
import { appStoreUrl, changeTone, formatChange, formatPopularity, formatRank } from "./view-model";

interface Props {
  readonly keyword: TrackedKeyword;
  readonly onRefresh: (id: string) => Promise<void>;
  readonly onRemove: (id: string) => Promise<void>;
}

/** One row of the keywords table: app/term, current rank, 7/30-day change, sparkline. */
export function KeywordRow({ keyword, onRefresh, onRemove }: Props) {
  const [busy, setBusy] = React.useState<"refresh" | "remove" | "">("");

  const run = async (action: "refresh" | "remove", fn: () => Promise<void>) => {
    setBusy(action);
    try {
      await fn();
    } finally {
      setBusy("");
    }
  };

  return (
    <li className="flex flex-col gap-3 py-3 first:pt-1 last:pb-1 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="truncate font-medium">{keyword.term}</p>
        <p className="mt-0.5 flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
          <a
            href={appStoreUrl(keyword.app_id)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 hover:text-foreground hover:underline"
          >
            {keyword.app_name || keyword.app_id} <ExternalLink className="size-3" aria-hidden />
          </a>
          <span>· {keyword.country.toUpperCase()} store</span>
          {formatPopularity(keyword.popularity) ? (
            <span title="Apple's own Search Popularity index">
              · Popularity {formatPopularity(keyword.popularity)}
            </span>
          ) : null}
          {keyword.last_error ? <span className="text-destructive">· {keyword.last_error}</span> : null}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-4">
        <div className="text-right">
          <p className="text-lg font-semibold tabular-nums">{formatRank(keyword.current_rank)}</p>
          <div className="flex gap-2 text-xs">
            <span className={changeTone(keyword.change_7d)}>{formatChange(keyword.change_7d) || "7d —"}</span>
            <span className={changeTone(keyword.change_30d)}>
              {formatChange(keyword.change_30d) ? `${formatChange(keyword.change_30d)} (30d)` : "30d —"}
            </span>
          </div>
        </div>
        <RankSparkline history={keyword.history} />
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="Check this rank right now"
            disabled={busy !== ""}
            onClick={() => void run("refresh", () => onRefresh(keyword.id))}
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw className={`size-4 ${busy === "refresh" ? "animate-spin" : ""}`} aria-hidden />
          </button>
          <button
            type="button"
            aria-label="Stop tracking this keyword"
            disabled={busy !== ""}
            onClick={() => void run("remove", () => onRemove(keyword.id))}
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>
      </div>
    </li>
  );
}
