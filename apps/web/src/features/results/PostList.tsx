"use client";

import * as React from "react";
import { ExternalLink, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import type { TrackedPost, TypedNumbers } from "./api";
import { postLine, shortCount } from "./view-model";

const FIELDS: readonly { key: keyof TypedNumbers; label: string }[] = [
  { key: "views", label: "Views" },
  { key: "likes", label: "Likes" },
  { key: "comments", label: "Comments" },
  { key: "shares", label: "Shares" },
];

interface PostListProps {
  readonly posts: readonly TrackedPost[];
  readonly onTypeNumbers: (postId: string, numbers: TypedNumbers) => Promise<void>;
  readonly onRemove: (postId: string) => Promise<void>;
}

/** Every tracked post, best first, with its numbers or why they are missing. */
export function PostList({ posts, onTypeNumbers, onRemove }: PostListProps) {
  const sorted = React.useMemo(
    () => [...posts].sort((a, b) => (b.views ?? -1) - (a.views ?? -1)),
    [posts],
  );
  if (sorted.length === 0) return null;
  return (
    <section className="glass rounded-2xl p-5">
      <h2 className="mb-2 text-sm font-medium text-muted-foreground">Your posts</h2>
      <ul className="divide-y divide-border">
        {sorted.map((post) => (
          <PostRow key={post.id} post={post} onTypeNumbers={onTypeNumbers} onRemove={onRemove} />
        ))}
      </ul>
    </section>
  );
}

function PostRow({
  post,
  onTypeNumbers,
  onRemove,
}: Readonly<{
  post: TrackedPost;
  onTypeNumbers: PostListProps["onTypeNumbers"];
  onRemove: PostListProps["onRemove"];
}>) {
  const [typing, setTyping] = React.useState(false);
  const line = postLine(post);
  return (
    <li className="py-3 first:pt-1 last:pb-1">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">{post.title || `${post.label} post`}</p>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {post.label}
            {line ? ` · ${line}` : ""}
          </p>
          <div className="mt-1 flex flex-wrap gap-x-4 text-sm">
            {post.url ? (
              <a
                href={post.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
              >
                Open <ExternalLink className="size-3" aria-hidden />
              </a>
            ) : null}
            {post.can_type_numbers && !typing ? (
              <button
                type="button"
                onClick={() => setTyping(true)}
                className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
              >
                Enter numbers yourself
              </button>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 items-start gap-2">
          <div className="text-right">
            <p className="text-lg font-semibold tabular-nums">{shortCount(post.views) || "–"}</p>
            <p className="text-xs text-muted-foreground">views</p>
          </div>
          {!post.from_menivor ? (
            <button
              type="button"
              aria-label="Stop tracking this post"
              onClick={() => void onRemove(post.id)}
              className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="size-4" aria-hidden />
            </button>
          ) : null}
        </div>
      </div>
      {typing ? (
        <TypeNumbersForm
          onCancel={() => setTyping(false)}
          onSubmit={async (numbers) => {
            await onTypeNumbers(post.id, numbers);
            setTyping(false);
          }}
        />
      ) : null}
    </li>
  );
}

function TypeNumbersForm({
  onSubmit,
  onCancel,
}: Readonly<{ onSubmit: (numbers: TypedNumbers) => Promise<void>; onCancel: () => void }>) {
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const numbers = React.useMemo(() => {
    const out: Record<string, number> = {};
    for (const { key } of FIELDS) {
      const raw = (values[key] ?? "").replace(/[,\s]/g, "");
      if (raw !== "" && /^\d+$/.test(raw)) out[key] = Number(raw);
    }
    return out as TypedNumbers;
  }, [values]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (Object.keys(numbers).length === 0 || busy) return;
    setBusy(true);
    setError("");
    try {
      await onSubmit(numbers);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Those numbers could not be saved. Try again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="neu-inset mt-3 rounded-xl p-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {FIELDS.map(({ key, label }) => (
          <label key={key} className="text-xs text-muted-foreground">
            {label}
            <Input
              inputMode="numeric"
              pattern="[0-9,]*"
              value={values[key] ?? ""}
              onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
              className="mt-1 h-9"
            />
          </label>
        ))}
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="mt-3 flex gap-2">
        <Button type="submit" size="sm" disabled={busy || Object.keys(numbers).length === 0}>
          {busy ? "Saving..." : "Save"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
