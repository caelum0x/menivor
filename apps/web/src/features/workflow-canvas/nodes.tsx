"use client";

import * as React from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Captions, CheckCircle2, Coins, Film, FileText, ImageIcon, Lightbulb, Send } from "lucide-react";

import { cn } from "@/lib/utils";
import type { NodeType } from "./api";
import { SPEND_TYPES, type StepNode } from "./graph";

export const NODE_META: Record<NodeType, { label: string; icon: typeof Lightbulb; help: string }> = {
  brief: { label: "Brief", icon: Lightbulb, help: "What to make, from your Brain." },
  script: { label: "Script", icon: FileText, help: "Hook and lines from the brief." },
  images: { label: "Images", icon: ImageIcon, help: "Ad images." },
  video: { label: "Video", icon: Film, help: "A UGC-style video." },
  captions: { label: "Captions", icon: Captions, help: "Burned captions on the video." },
  approve: { label: "Approve", icon: CheckCircle2, help: "Nothing after this runs until you approve." },
  publish: { label: "Publish", icon: Send, help: "Schedule to your accounts." },
};

function summary(data: StepNode["data"]): string {
  switch (data.kind) {
    case "brief":
      return data.request ? String(data.request) : "From your Brain";
    case "script":
      return `${data.seconds ?? 30} seconds`;
    case "images":
    case "video": {
      const n = data.count ?? 1;
      return `${n} ${data.kind === "video" ? "video" : "image"}${n > 1 ? "s" : ""}`;
    }
    case "captions":
      return data.style === "bold" ? "Bold style" : "Clean style";
    case "approve":
      return "You decide here";
    case "publish":
      return (data.platforms ?? ["tiktok"]).map((p) => p.replace("_", " ")).join(", ");
    default:
      return "";
  }
}

/** One calm card per step; left handle in, right handle out. */
export function StepNodeView({ data, selected }: NodeProps<StepNode>) {
  const meta = NODE_META[data.kind];
  const Icon = meta.icon;
  return (
    <div
      className={cn(
        "glass-subtle w-48 rounded-xl px-3 py-2.5 text-left text-sm shadow-sm transition",
        selected ? "ring-2 ring-primary" : "ring-0",
      )}
      data-testid={`node-${data.kind}`}
    >
      {data.kind !== "brief" ? <Handle type="target" position={Position.Left} /> : null}
      <div className="flex items-center gap-2 font-medium">
        <Icon className="size-4 text-primary" aria-hidden />
        <span>{meta.label}</span>
        {SPEND_TYPES.has(data.kind) ? (
          <span className="ml-auto flex items-center gap-1 text-[11px] font-normal text-muted-foreground" title="Spends credits after approval">
            <Coins className="size-3" aria-hidden /> credits
          </span>
        ) : null}
      </div>
      <p className="mt-1 truncate text-xs text-muted-foreground">{summary(data)}</p>
      {data.kind === "approve" ? (
        <p className="mt-1 text-[11px] leading-snug text-muted-foreground">Nothing after this runs until you approve.</p>
      ) : null}
      {data.kind !== "publish" ? <Handle type="source" position={Position.Right} /> : null}
    </div>
  );
}

export const nodeTypes = { step: StepNodeView };
