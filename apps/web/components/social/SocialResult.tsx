"use client";

import * as React from "react";
import type { SocialMeta } from "@/lib/types";
import { Label } from "@/components/ui/label";
import { CopyButton } from "@/components/social/CopyButton";

export interface SocialResultProps {
  meta: SocialMeta;
}

/** Join the whole post into one block for the "copy all" affordance. */
function composePost(meta: SocialMeta): string {
  return [
    meta.title.trim(),
    meta.caption.trim(),
    meta.hashtags.join(" ").trim(),
  ]
    .filter((part) => part.length > 0)
    .join("\n\n");
}

/**
 * Renders the generated post copy: a title, caption, and hashtag chips, each with
 * its own copy-to-clipboard button, plus a single "Copy all" that copies the full
 * post (title + caption + hashtags). Pure presentation — the parent owns loading
 * and error state.
 */
export function SocialResult({ meta }: Readonly<SocialResultProps>) {
  const wholePost = React.useMemo(() => composePost(meta), [meta]);
  const hasContent = wholePost.length > 0;

  return (
    <div className="space-y-4 rounded-lg border border-border p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-foreground">Generated post</p>
        <CopyButton
          value={wholePost}
          label="Copy the full post (title, caption, and hashtags)"
          variant="default"
        >
          Copy all
        </CopyButton>
      </div>

      {!hasContent && (
        <p className="text-sm text-muted-foreground">
          The generator returned no copy for this platform. Try regenerating.
        </p>
      )}

      {meta.title.trim().length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-3">
            <Label>Title</Label>
            <CopyButton value={meta.title} label="Copy title" size="sm" />
          </div>
          <p className="whitespace-pre-wrap break-words text-sm text-foreground">
            {meta.title}
          </p>
        </div>
      )}

      {meta.caption.trim().length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-3">
            <Label>Caption</Label>
            <CopyButton value={meta.caption} label="Copy caption" size="sm" />
          </div>
          <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">
            {meta.caption}
          </p>
        </div>
      )}

      {meta.hashtags.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-3">
            <Label>Hashtags</Label>
            <CopyButton
              value={meta.hashtags.join(" ")}
              label="Copy all hashtags"
              size="sm"
            />
          </div>
          <ul className="flex flex-wrap gap-2">
            {meta.hashtags.map((tag, index) => (
              <li key={`${tag}-${index}`}>
                <CopyButton
                  value={tag}
                  label={`Copy hashtag ${tag}`}
                  variant="secondary"
                  size="sm"
                  className="font-mono text-xs"
                >
                  {tag}
                </CopyButton>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
