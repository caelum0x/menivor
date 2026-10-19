"use client";

import * as React from "react";
import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatCount, relativeTime, stateLabel } from "./format";
import type { InboxPost } from "./types";

interface PostEngagementProps {
  posts: InboxPost[];
  onFilterPost: (postId: string) => void;
}

/**
 * Per-post engagement as the platforms reported it plus what the inbox pulled.
 * These comment counts also feed the winner loop. A dash means the platform
 * did not report that number; nothing is estimated.
 */
export function PostEngagement({ posts, onFilterPost }: PostEngagementProps) {
  const rows = posts.filter((p) => p.kind === "post");
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardContent className="p-0">
        <div className="border-b border-border px-4 py-3">
          <p className="font-semibold">Posts Menivor published</p>
          <p className="text-xs text-muted-foreground">
            Counts come from each platform. Comment counts also feed your winner loop.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Post</th>
                <th className="px-4 py-2 font-medium">Views</th>
                <th className="px-4 py-2 font-medium">Likes</th>
                <th className="px-4 py-2 font-medium">Comments</th>
                <th className="px-4 py-2 font-medium">Waiting</th>
                <th className="px-4 py-2 font-medium">Inbox</th>
                <th className="px-4 py-2 font-medium">Checked</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((p) => (
                <tr key={p.id}>
                  <td className="max-w-[18rem] px-4 py-2">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{p.platform_label}</Badge>
                      <button
                        type="button"
                        className="truncate text-left hover:underline"
                        onClick={() => onFilterPost(p.id)}
                        title="Show this post's comments"
                      >
                        {p.title || "Untitled post"}
                      </button>
                      {p.url && (
                        <a
                          href={p.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-muted-foreground hover:text-foreground"
                          aria-label="Open post"
                        >
                          <ExternalLink className="size-3.5" aria-hidden />
                        </a>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2 tabular-nums">{formatCount(p.counts.platform_views)}</td>
                  <td className="px-4 py-2 tabular-nums">{formatCount(p.counts.platform_likes)}</td>
                  <td className="px-4 py-2 tabular-nums">
                    {formatCount(
                      p.counts.platform_comments === null && p.counts.synced_comments === 0
                        ? null
                        : Math.max(p.counts.platform_comments ?? 0, p.counts.synced_comments),
                    )}
                  </td>
                  <td className="px-4 py-2 tabular-nums">{p.counts.needs_reply}</td>
                  <td className="px-4 py-2">
                    <span title={p.state_note || undefined} className="text-xs">
                      {stateLabel(p.inbox_state)}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">
                    {relativeTime(p.last_polled_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
