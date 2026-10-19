"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

import { cancelPost, listPosts, retryPost, type QueuedPost } from "./api";
import { PROVIDER_LABEL, formatWhen, statusText } from "./plan";

type View = "upcoming" | "live" | "attention";
const VIEWS: { key: View; label: string }[] = [
  { key: "upcoming", label: "Upcoming" },
  { key: "live", label: "Live" },
  { key: "attention", label: "Needs you" },
];

export function inView(post: QueuedPost, view: View): boolean {
  if (view === "upcoming") return ["scheduled", "publishing", "processing"].includes(post.status);
  if (view === "live") return post.status === "published";
  return post.status === "failed" || post.status === "held";
}

/** The publish queue. One action: start a new batch. */
export function QueueScreen() {
  const [posts, setPosts] = React.useState<QueuedPost[] | null>(null);
  const [view, setView] = React.useState<View>("upcoming");
  const [error, setError] = React.useState("");
  const [working, setWorking] = React.useState("");

  const reload = React.useCallback(async () => {
    try {
      setPosts((await listPosts()).posts);
      setError("");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not load the queue."));
      setPosts((prev) => prev ?? []);
    }
  }, []);

  React.useEffect(() => {
    void reload();
    const timer = window.setInterval(() => void reload(), 30_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const act = async (post: QueuedPost, action: "cancel" | "retry") => {
    setWorking(post.id);
    try {
      const updated = action === "cancel" ? await cancelPost(post.id) : await retryPost(post.id);
      setPosts((prev) => (prev ?? []).map((p) => (p.id === post.id ? { ...p, ...updated } : p)));
    } catch (err) {
      setError(friendlyErrorMessage(err));
    } finally {
      setWorking("");
    }
  };

  const shown = (posts ?? [])
    .filter((p) => inView(p, view))
    .sort((a, b) => {
      const ta = Date.parse(a.next_attempt_at ?? a.scheduled_at ?? "") || 0;
      const tb = Date.parse(b.next_attempt_at ?? b.scheduled_at ?? "") || 0;
      return view === "upcoming" ? ta - tb : tb - ta;
    });
  const attention = (posts ?? []).filter((p) => inView(p, "attention")).length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1" role="tablist">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              role="tab"
              aria-selected={view === v.key}
              onClick={() => setView(v.key)}
              className={`rounded-md px-3 py-1.5 text-sm ${
                view === v.key ? "bg-white/[0.08] font-medium" : "text-muted-foreground"
              }`}
            >
              {v.label}
              {v.key === "attention" && attention > 0 ? ` (${attention})` : ""}
            </button>
          ))}
        </div>
        <Button asChild>
          <Link href="/autopost/new">New batch</Link>
        </Button>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {posts === null ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden /> Loading the queue
        </p>
      ) : shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing here yet.</p>
      ) : (
        <ul className="grid gap-2">
          {shown.map((post) => (
            <li key={post.id}>
              <Card>
                <CardContent className="flex items-center justify-between gap-3 p-3 text-sm">
                  <div className="min-w-0">
                    <p className="truncate font-medium">
                      {post.account_name || PROVIDER_LABEL[post.provider]}{" "}
                      <span className="font-normal text-muted-foreground">· {PROVIDER_LABEL[post.provider]}</span>
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {statusText(post)} · {formatWhen(post.published_at ?? post.next_attempt_at ?? post.scheduled_at)}
                    </p>
                    {post.error && view === "attention" ? (
                      <p className="mt-1 text-xs text-destructive">{post.error}</p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {post.status === "published" && post.url ? (
                      <a href={post.url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                        Open
                      </a>
                    ) : null}
                    {post.status === "scheduled" || post.status === "held" ? (
                      <Button size="sm" variant="ghost" disabled={working === post.id}
                        onClick={() => void act(post, "cancel")}>
                        Cancel
                      </Button>
                    ) : null}
                    {post.status === "failed" || post.status === "held" ? (
                      <Button size="sm" variant="secondary" disabled={working === post.id}
                        onClick={() => void act(post, "retry")}>
                        Try again
                      </Button>
                    ) : null}
                    {post.status === "held" ? <Badge variant="secondary">Review</Badge> : null}
                  </div>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
