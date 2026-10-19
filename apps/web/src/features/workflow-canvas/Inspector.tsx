"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { PLATFORMS, type StepNode } from "./graph";
import { NODE_META } from "./nodes";

const PLATFORM_LABEL: Record<string, string> = { tiktok: "TikTok", instagram: "Instagram", youtube_shorts: "YouTube Shorts" };

export function Inspector({
  node,
  onChange,
}: {
  node: StepNode | null;
  onChange: (id: string, patch: Partial<StepNode["data"]>) => void;
}) {
  if (!node) {
    return <p className="text-sm text-muted-foreground">Select a step to change it.</p>;
  }
  const { data } = node;
  const meta = NODE_META[data.kind];
  const set = (patch: Partial<StepNode["data"]>) => onChange(node.id, patch);
  return (
    <div className="space-y-3" data-testid="inspector">
      <div>
        <h3 className="text-sm font-semibold">{meta.label}</h3>
        <p className="text-xs text-muted-foreground">{meta.help}</p>
      </div>
      {data.kind === "brief" ? (
        <div className="space-y-1.5">
          <Label htmlFor="wf-request">What to make</Label>
          <Textarea
            id="wf-request"
            rows={4}
            maxLength={500}
            placeholder="Leave empty to use your Brain"
            value={String(data.request ?? "")}
            onChange={(e) => set({ request: e.target.value })}
          />
        </div>
      ) : null}
      {data.kind === "script" ? (
        <div className="space-y-1.5">
          <Label htmlFor="wf-seconds">Length (seconds)</Label>
          <Input
            id="wf-seconds"
            type="number"
            min={10}
            max={90}
            value={data.seconds ?? 30}
            onChange={(e) => set({ seconds: Math.max(10, Math.min(90, Number(e.target.value) || 30)) })}
          />
        </div>
      ) : null}
      {data.kind === "images" || data.kind === "video" ? (
        <div className="space-y-1.5">
          <Label htmlFor="wf-count">How many</Label>
          <Input
            id="wf-count"
            type="number"
            min={1}
            max={5}
            value={data.count ?? 1}
            onChange={(e) => set({ count: Math.max(1, Math.min(5, Number(e.target.value) || 1)) })}
          />
          <p className="text-xs text-muted-foreground">Spends credits only after you approve.</p>
        </div>
      ) : null}
      {data.kind === "captions" ? (
        <div className="flex gap-2" role="radiogroup" aria-label="Caption style">
          {(["clean", "bold"] as const).map((style) => (
            <button
              key={style}
              type="button"
              role="radio"
              aria-checked={(data.style ?? "clean") === style}
              className={cn(
                "rounded-full px-3 py-1 text-sm",
                (data.style ?? "clean") === style ? "neu-pressed text-foreground" : "neu-raised text-muted-foreground",
              )}
              onClick={() => set({ style })}
            >
              {style === "clean" ? "Clean" : "Bold"}
            </button>
          ))}
        </div>
      ) : null}
      {data.kind === "publish" ? (
        <fieldset className="space-y-1.5">
          <legend className="text-sm font-medium">Post to</legend>
          {PLATFORMS.map((p) => {
            const list = data.platforms ?? ["tiktok"];
            const on = list.includes(p);
            return (
              <label key={p} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => {
                    const next = on ? list.filter((x) => x !== p) : [...list, p];
                    set({ platforms: next.length ? next : ["tiktok"] });
                  }}
                />
                {PLATFORM_LABEL[p]}
              </label>
            );
          })}
        </fieldset>
      ) : null}
      {data.kind === "approve" ? (
        <p className="text-sm text-muted-foreground">
          Images, videos and posts wait here. You approve them in the Agent queue.
        </p>
      ) : null}
    </div>
  );
}
