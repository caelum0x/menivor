"use client";

import * as React from "react";
import { Check, Clapperboard, GalleryHorizontalEnd, Undo2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageView, imageKeys, useImageUrls } from "@/components/design/PageView";
import { fitScale } from "@/components/design/shared";
import { fontsIn, requestFonts } from "@/components/design/fonts";

import type { Decision, MonthIdea } from "./types";

const THRESHOLD = 110;

export function IdeaPreview({
  idea,
  getOptions,
  maxW,
  maxH,
}: {
  idea: MonthIdea;
  getOptions: () => Promise<{ token?: string }>;
  maxW: number;
  maxH: number;
}) {
  const { page, width, height } = idea.preview;
  const urls = useImageUrls(imageKeys([page]), getOptions);
  React.useEffect(() => {
    requestFonts(fontsIn({ version: 1, pages: [page] }));
  }, [page]);
  return (
    <div className="overflow-hidden rounded-xl shadow-sm ring-1 ring-black/5">
      <PageView page={page} width={width} height={height} scale={fitScale(width, height, maxW, maxH)} imageUrls={urls} />
    </div>
  );
}

function KindBadge({ idea }: { idea: MonthIdea }) {
  const Icon = idea.kind === "reel" ? Clapperboard : GalleryHorizontalEnd;
  return (
    <Badge variant="secondary" className="gap-1">
      <Icon className="size-3.5" aria-hidden />
      {idea.kind === "reel" ? "Reel" : "Carousel"} · {idea.format_name}
    </Badge>
  );
}

function SwipeCard({
  idea,
  getOptions,
  onDecide,
}: {
  idea: MonthIdea;
  getOptions: () => Promise<{ token?: string }>;
  onDecide: (decision: Decision) => void;
}) {
  const [dx, setDx] = React.useState(0);
  const start = React.useRef<number | null>(null);

  const end = () => {
    if (start.current === null) return;
    start.current = null;
    if (dx > THRESHOLD) onDecide("kept");
    else if (dx < -THRESHOLD) onDecide("skipped");
    setDx(0);
  };

  return (
    <div
      className="touch-pan-y select-none rounded-2xl border border-white/10 bg-card/70 p-4 shadow-lg backdrop-blur transition-transform duration-150"
      style={{ transform: `translateX(${dx}px) rotate(${dx / 25}deg)` }}
      onPointerDown={(e) => {
        start.current = e.clientX;
        (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (start.current !== null) setDx(e.clientX - start.current);
      }}
      onPointerUp={end}
      onPointerCancel={end}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <KindBadge idea={idea} />
        <span
          className={`text-xs font-semibold transition-opacity ${dx > 30 ? "text-emerald-600 opacity-100" : dx < -30 ? "text-rose-600 opacity-100" : "opacity-0"}`}
          aria-hidden
        >
          {dx > 0 ? "Keep" : "Skip"}
        </span>
      </div>
      <div className="flex justify-center">
        <IdeaPreview idea={idea} getOptions={getOptions} maxW={300} maxH={420} />
      </div>
      <ol className="mt-4 space-y-1 text-sm text-muted-foreground">
        {idea.slides.slice(1, 4).map((line, i) => (
          <li key={i} className="line-clamp-2">
            <span className="mr-2 font-mono text-xs text-primary">{String(i + 2).padStart(2, "0")}</span>
            {line}
          </li>
        ))}
        {idea.slides.length > 4 ? <li className="text-xs">+{idea.slides.length - 4} more</li> : null}
      </ol>
      {idea.why ? <p className="mt-3 text-xs text-muted-foreground">{idea.why}</p> : null}
    </div>
  );
}

/** Tinder-style deck: right (or the check) keeps a post, left (or the cross) skips it. */
export function SwipeDeck({
  ideas,
  kept,
  total,
  getOptions,
  onDecide,
  onUndo,
  canUndo,
}: {
  ideas: MonthIdea[];
  kept: number;
  total: number;
  getOptions: () => Promise<{ token?: string }>;
  onDecide: (idea: MonthIdea, decision: Decision) => void;
  onUndo: () => void;
  canUndo: boolean;
}) {
  const current = ideas[0];

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!current || (e.target as HTMLElement)?.closest("input,textarea")) return;
      if (e.key === "ArrowRight") onDecide(current, "kept");
      if (e.key === "ArrowLeft") onDecide(current, "skipped");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, onDecide]);

  if (!current) return null;
  const seen = total - ideas.length;
  return (
    <div className="mx-auto w-full max-w-sm">
      <div className="mb-3 flex items-center justify-between text-sm">
        <span className="text-muted-foreground">
          {seen + 1} of {total}
        </span>
        <span className="font-semibold text-emerald-600">{kept} kept</span>
      </div>
      <div className="mb-4 h-1 overflow-hidden rounded-full bg-secondary">
        <div className="h-full bg-primary transition-all" style={{ width: `${(seen / Math.max(1, total)) * 100}%` }} />
      </div>
      <SwipeCard key={current.id} idea={current} getOptions={getOptions} onDecide={(d) => onDecide(current, d)} />
      <div className="mt-5 flex items-center justify-center gap-5">
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="size-14 rounded-full"
          aria-label="Skip this post"
          title="Skip (left arrow)"
          onClick={() => onDecide(current, "skipped")}
        >
          <X className="size-6 text-rose-600" aria-hidden />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-10 rounded-full"
          aria-label="Undo the last swipe"
          title="Undo"
          disabled={!canUndo}
          onClick={onUndo}
        >
          <Undo2 className="size-4" aria-hidden />
        </Button>
        <Button
          type="button"
          size="icon"
          className="size-14 rounded-full"
          aria-label="Keep this post"
          title="Keep (right arrow)"
          onClick={() => onDecide(current, "kept")}
        >
          <Check className="size-6" aria-hidden />
        </Button>
      </div>
    </div>
  );
}
