"use client";

import * as React from "react";
import { Mail, MessageSquare } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { relativeTime, statusLabel } from "./format";
import type { InboxThread } from "./types";

interface ThreadListProps {
  threads: InboxThread[];
  selectedId: string | null;
  onSelect: (threadId: string) => void;
}

/** Conversation list: newest activity first, with platform, post and status. */
export function ThreadList({ threads, selectedId, onSelect }: ThreadListProps) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border" aria-label="Conversations">
      {threads.map((t) => {
        const Icon = t.kind === "dm" ? Mail : MessageSquare;
        const active = t.id === selectedId;
        return (
          <li key={t.id}>
            <button
              type="button"
              onClick={() => onSelect(t.id)}
              aria-current={active ? "true" : undefined}
              className={cn(
                "flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors hover:bg-secondary/50",
                active && "bg-secondary/70",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
                  <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="truncate">{t.author_name || "Someone"}</span>
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {relativeTime(t.last_message_at)}
                </span>
              </div>
              <p className="line-clamp-2 text-sm text-muted-foreground">{t.text || "(no text)"}</p>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant="outline">{t.platform_label}</Badge>
                {t.kind === "comment" && t.post_title && (
                  <span className="max-w-[16rem] truncate">on {t.post_title}</span>
                )}
                <Badge variant={t.status === "needs_reply" ? "default" : "secondary"}>
                  {statusLabel(t.status)}
                </Badge>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
