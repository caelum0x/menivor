"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { AlertTriangle, ExternalLink, Loader2, RefreshCw, RotateCcw, X } from "lucide-react";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  cancelPost,
  errorText,
  listPosts,
  retryPost,
  type PlatformPost,
  type PostStatus,
} from "../_lib/publishing-api";
import { PLATFORM_ICONS, POST_STATUS_LABELS, formatWhen } from "./platform-meta";
import { safeServerText } from "@/src/shared/errors/friendly";

const STATUS_VARIANT: Record<PostStatus, BadgeVariant> = {
  scheduled: "outline",
  publishing: "default",
  processing: "default",
  published: "success",
  failed: "destructive",
  canceled: "secondary",
  held: "destructive",
};

const ACTIVE: readonly PostStatus[] = ["scheduled", "publishing", "processing"];
const REFRESH_MS = 15_000;

type LoadState = "loading" | "ready" | "error";

/** Posts to Facebook / LinkedIn / X / Threads / Pinterest / Bluesky with live status. */
export function PlatformPostsList() {
  const { getToken, isLoaded } = useAuth();
  const [posts, setPosts] = React.useState<readonly PlatformPost[]>([]);
  const [total, setTotal] = React.useState(0);
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [error, setError] = React.useState("");
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [rowErrors, setRowErrors] = React.useState<Readonly<Record<string, string>>>({});

  const options = React.useCallback(async () => ({ token: (await getToken()) ?? undefined }), [getToken]);

  const load = React.useCallback(async () => {
    try {
      const page = await listPosts([], 0, await options());
      setPosts(page.posts);
      setTotal(page.total);
      setStatus("ready");
      setError("");
    } catch (err) {
      setError(errorText(err, "Couldn't load posts to other platforms."));
      setStatus("error");
    }
  }, [options]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  const hasActive = posts.some((p) => ACTIVE.includes(p.status));
  React.useEffect(() => {
    if (!hasActive) return;
    const id = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(id);
  }, [hasActive, load]);

  const act = async (post: PlatformPost, action: "cancel" | "retry") => {
    setBusyId(post.id);
    setRowErrors((prev) => ({ ...prev, [post.id]: "" }));
    try {
      const updated = action === "cancel" ? await cancelPost(post.id, await options()) : await retryPost(post.id, await options());
      setPosts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    } catch (err) {
      setRowErrors((prev) => ({ ...prev, [post.id]: errorText(err, "That didn't work.") }));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="mt-10 space-y-3">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Other platforms</h2>
          <p className="text-sm text-muted-foreground">
            Facebook Pages, LinkedIn, X, Threads, Pinterest and Bluesky.
            {total > posts.length ? ` Showing the latest ${posts.length} of ${total}.` : ""}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw className="size-4" aria-hidden /> Refresh
        </Button>
      </div>

      {status === "loading" && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {status === "error" && (
        <p className="flex items-center gap-2 text-sm text-destructive" role="alert">
          <AlertTriangle className="size-4" aria-hidden /> {error}
        </p>
      )}

      {status === "ready" && posts.length === 0 && (
        <Card>
          <CardContent className="p-5 text-sm text-muted-foreground">
            Nothing posted to other platforms yet. Connect one under Connections, then use
            &quot;Post to these platforms&quot;.
          </CardContent>
        </Card>
      )}

      {status === "ready" && posts.length > 0 && (
        <ul className="space-y-2">
          {posts.map((post) => {
            const Icon = PLATFORM_ICONS[post.platform];
            const when = post.status === "published" ? post.published_at : post.scheduled_at;
            return (
              <li key={post.id}>
                <Card>
                  <CardContent className="space-y-2 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="flex items-center gap-2 text-sm font-medium">
                        <Icon className="size-4" aria-hidden />
                        {post.platform_label}
                        <span className="font-normal text-muted-foreground">{formatWhen(when)}</span>
                      </span>
                      <Badge variant={STATUS_VARIANT[post.status]}>{POST_STATUS_LABELS[post.status]}</Badge>
                    </div>
                    {post.text && <p className="line-clamp-2 text-sm text-muted-foreground">{post.text}</p>}
                    {post.status === "processing" && post.note && (
                      <p className="text-xs text-muted-foreground">{post.note}</p>
                    )}
                    {post.error && (post.status === "failed" || post.status === "held" || post.attempts > 0) && (
                      <p className="text-xs text-destructive">{safeServerText(post.error, "This post could not go out.")}</p>
                    )}
                    <div className="flex flex-wrap gap-2">
                      {post.url && (
                        <Button asChild variant="outline" size="sm">
                          <a href={post.url} target="_blank" rel="noopener noreferrer">
                            <ExternalLink className="size-4" aria-hidden /> View post
                          </a>
                        </Button>
                      )}
                      {post.can_cancel && (
                        <Button variant="ghost" size="sm" disabled={busyId === post.id} onClick={() => void act(post, "cancel")}>
                          {busyId === post.id ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <X className="size-4" aria-hidden />}
                          Cancel
                        </Button>
                      )}
                      {post.can_retry && (
                        <Button variant="outline" size="sm" disabled={busyId === post.id} onClick={() => void act(post, "retry")}>
                          {busyId === post.id ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <RotateCcw className="size-4" aria-hidden />}
                          Try again
                        </Button>
                      )}
                    </div>
                    {rowErrors[post.id] && <p className="text-xs text-destructive">{rowErrors[post.id]}</p>}
                  </CardContent>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
