"use client";

import * as React from "react";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { postLabel } from "./format";
import type { InboxPost, ThreadFilters } from "./types";

interface InboxFiltersProps {
  filters: ThreadFilters;
  posts: InboxPost[];
  onChange: (next: ThreadFilters) => void;
}

/** Platform / post / status / kind filters for the conversation list. */
export function InboxFilters({ filters, posts, onChange }: InboxFiltersProps) {
  const visiblePosts = filters.platform
    ? posts.filter((p) => p.platform === filters.platform)
    : posts;
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <div className="space-y-1">
        <Label htmlFor="inbox-status">Show</Label>
        <Select
          id="inbox-status"
          value={filters.status}
          onChange={(e) => onChange({ ...filters, status: e.target.value as ThreadFilters["status"] })}
        >
          <option value="needs_reply">Needs reply</option>
          <option value="replied">Replied</option>
          <option value="done">Done</option>
          <option value="all">Everything</option>
        </Select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="inbox-platform">Platform</Label>
        <Select
          id="inbox-platform"
          value={filters.platform}
          onChange={(e) =>
            onChange({
              ...filters,
              platform: e.target.value as ThreadFilters["platform"],
              postId: "",
            })
          }
        >
          <option value="">All platforms</option>
          <option value="youtube">YouTube</option>
          <option value="instagram">Instagram</option>
          <option value="tiktok">TikTok</option>
        </Select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="inbox-post">Post</Label>
        <Select
          id="inbox-post"
          value={filters.postId}
          onChange={(e) => onChange({ ...filters, postId: e.target.value })}
        >
          <option value="">All posts</option>
          {visiblePosts.map((p) => (
            <option key={p.id} value={p.id}>
              {postLabel(p)}
            </option>
          ))}
        </Select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="inbox-kind">Type</Label>
        <Select
          id="inbox-kind"
          value={filters.kind}
          onChange={(e) => onChange({ ...filters, kind: e.target.value as ThreadFilters["kind"] })}
        >
          <option value="">Comments and messages</option>
          <option value="comment">Comments</option>
          <option value="dm">Direct messages</option>
        </Select>
      </div>
    </div>
  );
}
