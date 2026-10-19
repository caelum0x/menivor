"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import type { Preview } from "../api";
import { PROVIDER_LABEL, formatWhen } from "../plan";

/** Step 4: the planned schedule, exactly as the queue will run it. */
export function ReviewStep({ preview, error }: { preview: Preview | null; error: string }) {
  if (error) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {error}
      </p>
    );
  }
  if (!preview) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Planning the schedule
      </p>
    );
  }
  const byAccount = new Map<string, number>();
  for (const post of preview.posts) {
    byAccount.set(post.account_name, (byAccount.get(post.account_name) ?? 0) + 1);
  }
  return (
    <div className="space-y-5">
      <p className="text-sm">
        {preview.posts.length} posts across {byAccount.size} accounts, from {formatWhen(preview.start_at)}
        {preview.last_post_at ? ` to ${formatWhen(preview.last_post_at)}` : ""}.
      </p>
      <ul className="max-h-80 divide-y divide-white/5 overflow-y-auto rounded-md border border-white/10 text-sm">
        {preview.posts.map((post, index) => (
          <li key={`${post.job_id}-${post.account_id}-${index}`} className="flex justify-between gap-3 px-3 py-2">
            <span className="truncate">
              {post.account_name} <span className="text-muted-foreground">· {PROVIDER_LABEL[post.provider]}</span>
            </span>
            <span className="shrink-0 text-muted-foreground">{formatWhen(post.at)}</span>
          </li>
        ))}
      </ul>
      <ul className="space-y-1 text-xs text-muted-foreground">
        {preview.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </div>
  );
}
