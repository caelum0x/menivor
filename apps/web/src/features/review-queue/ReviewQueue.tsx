"use client";

import * as React from "react";
import Link from "next/link";
import { Check, Loader2, RefreshCw, SquareStack, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ErrorText, errorMessage } from "@/src/features/ad-studio/shared";
import { useStableRequestOptions } from "./use-stable-options";
import { decide, getQueue, type ReasonChip, type ReviewDecision, type ReviewItem, type ReviewQueue as Queue } from "./api";

/** Horizontal drag (px) that counts as a swipe. */
export const SWIPE_PX = 100;
type ChipSet = "approve" | "fix";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable;
}

function Media({ item }: { item: ReviewItem }) {
  const url = item.payload.media_url || "";
  if (!url) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Still rendering. You can review it now or later.
      </div>
    );
  }
  if (item.payload.kind === "video") {
    return (
      <video
        src={url}
        className="h-full w-full object-cover"
        muted
        loop
        playsInline
        autoPlay
        aria-label={`Video: ${item.title}`}
      />
    );
  }
  // eslint-disable-next-line @next/next/no-img-element -- generated media on our CDN, any size
  return <img src={url} alt={item.title} className="h-full w-full object-cover" draggable={false} />;
}

function Chips({
  chips,
  selected,
  onPick,
  label,
}: Readonly<{ chips: ReasonChip[]; selected: string; onPick: (id: string) => void; label: string }>) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label={label}>
      {chips.map((c, i) => (
        <button
          key={c.id}
          type="button"
          aria-pressed={selected === c.id}
          onClick={() => onPick(selected === c.id ? "" : c.id)}
          className={cn(
            "glass-subtle rounded-full px-3 py-1.5 text-xs transition-colors hover:border-primary/60",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            selected === c.id && "border-primary/70 font-medium text-primary",
          )}
        >
          <span className="mr-1.5 text-muted-foreground">{i + 1}</span>
          {c.label}
        </button>
      ))}
    </div>
  );
}

/** Relay-Studio-style review: one creative at a time; swipe, keys or buttons; a reason chip per decision. */
export function ReviewQueue() {
  const requestOptions = useStableRequestOptions();
  const [queue, setQueue] = React.useState<Queue | null>(null);
  const [items, setItems] = React.useState<ReviewItem[]>([]);
  const [reviewed, setReviewed] = React.useState(0);
  const [chipSet, setChipSet] = React.useState<ChipSet>("approve");
  const [chip, setChip] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [dragX, setDragX] = React.useState(0);
  const dragStart = React.useRef<number | null>(null);

  const load = React.useCallback(async () => {
    try {
      const data = await getQueue(await requestOptions());
      setQueue(data);
      setItems(data.items);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [requestOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const current = items[0] ?? null;
  const chips = React.useMemo(
    () => (queue ? (chipSet === "approve" ? queue.reasons.approve : queue.reasons.fix) : []),
    [queue, chipSet],
  );
  const credits = current?.payload.regenerate_credits ?? 0;

  const switchSet = (next: ChipSet) => {
    if (next !== chipSet) {
      setChipSet(next);
      setChip("");
    }
  };

  const act = React.useCallback(
    async (decision: ReviewDecision) => {
      if (!current || busy) return;
      const reason = (decision === "approve") === (chipSet === "approve") ? chip : "";
      if (decision === "regenerate" && !reason) {
        setChipSet("fix");
        setChip("");
        setError("Pick what to change first, then regenerate.");
        return;
      }
      setBusy(true);
      setError("");
      try {
        const out = await decide(
          current.id,
          { decision, reason: reason || undefined, confirm_spend: decision === "regenerate" ? true : undefined },
          await requestOptions(),
        );
        setItems((prev) => prev.slice(1));
        setReviewed((n) => n + 1);
        setChip("");
        setChipSet("approve");
        const label = out.review?.reason_label ? `: ${out.review.reason_label}` : "";
        setNotice(
          decision === "approve"
            ? `Approved${label}`
            : decision === "reject"
              ? `Rejected${label}`
              : out.regenerate_action?.status === "executed"
                ? "A new version is on its way. It will appear here."
                : "Regeneration is waiting for approval in Agent.",
        );
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setBusy(false);
        setDragX(0);
      }
    },
    [busy, chip, chipSet, current, requestOptions],
  );

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey || !current) return;
      const key = e.key.toLowerCase();
      if (key === "arrowright" || key === "a") {
        e.preventDefault();
        void act("approve");
      } else if (key === "arrowleft" || key === "x") {
        e.preventDefault();
        void act("reject");
      } else if (key === "r") {
        e.preventDefault();
        void act("regenerate");
      } else if (/^[1-6]$/.test(key)) {
        const picked = chips[Number(key) - 1];
        if (picked) setChip((prev) => (prev === picked.id ? "" : picked.id));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [act, chips, current]);

  const onPointerDown = (e: React.PointerEvent) => {
    dragStart.current = e.clientX;
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (dragStart.current !== null) setDragX(e.clientX - dragStart.current);
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (dragStart.current === null) return;
    const dx = e.clientX - dragStart.current;
    dragStart.current = null;
    if (dx >= SWIPE_PX) void act("approve");
    else if (dx <= -SWIPE_PX) void act("reject");
    else setDragX(0);
  };

  if (!queue) {
    return error ? <ErrorText message={error} /> : <Loader2 className="size-5 animate-spin" aria-label="Loading" />;
  }

  const total = reviewed + items.length;
  const top = queue.stats.top_reasons;

  return (
    <div className="mx-auto max-w-xl space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <SquareStack className="size-6 text-primary" aria-hidden /> Review
        </h1>
        {current ? (
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {reviewed + 1} of {total}
          </p>
        ) : null}
      </div>

      {!current ? (
        <div className="glass-subtle space-y-3 rounded-3xl p-10 text-center">
          <p className="text-lg font-medium">Nothing to review</p>
          <p className="text-sm text-muted-foreground">New images and videos from the agent show up here.</p>
          <Link href="/agent" className="text-sm text-primary underline-offset-4 hover:underline">
            Open Agent
          </Link>
          {notice ? <p className="text-xs text-muted-foreground">{notice}</p> : null}
        </div>
      ) : (
        <>
          <div
            data-testid="review-card"
            role="region"
            aria-label={`Creative: ${current.title}`}
            className="glass relative aspect-[9/14] touch-pan-y select-none overflow-hidden rounded-3xl transition-transform"
            style={{ transform: `translateX(${dragX}px) rotate(${dragX / 30}deg)` }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={() => {
              dragStart.current = null;
              setDragX(0);
            }}
          >
            <Media item={current} />
            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-5">
              <Badge variant="secondary" className="mb-2 capitalize">
                {current.payload.kind || "creative"}
              </Badge>
              <p className="font-semibold text-white">{current.title}</p>
            </div>
            {dragX > 40 ? (
              <span className="absolute left-5 top-5 rounded-full bg-success/80 px-3 py-1 text-sm text-white">Approve</span>
            ) : null}
            {dragX < -40 ? (
              <span className="absolute right-5 top-5 rounded-full bg-destructive/80 px-3 py-1 text-sm text-white">Reject</span>
            ) : null}
          </div>

          <div className="space-y-2">
            <div className="flex gap-2 text-xs" role="tablist" aria-label="Reason type">
              {(["approve", "fix"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  role="tab"
                  aria-selected={chipSet === s}
                  onClick={() => switchSet(s)}
                  className={cn("rounded-full px-3 py-1", chipSet === s ? "bg-white/10 font-medium" : "text-muted-foreground")}
                >
                  {s === "approve" ? "Why it works" : "What to fix"}
                </button>
              ))}
            </div>
            <Chips chips={chips} selected={chip} onPick={setChip} label={chipSet === "approve" ? "Why it works" : "What to fix"} />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Button variant="outline" size="lg" onClick={() => void act("reject")} disabled={busy} aria-label="Reject (Left arrow or X)">
              <X aria-hidden /> Reject
            </Button>
            <Button
              variant="outline"
              size="lg"
              onClick={() => void act("regenerate")}
              disabled={busy}
              aria-label={`Regenerate for ${credits} credits (R)`}
            >
              <RefreshCw aria-hidden /> Regenerate ({credits} credits)
            </Button>
            <Button size="lg" onClick={() => void act("approve")} disabled={busy} aria-label="Approve (Right arrow or A)">
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />} Approve
            </Button>
          </div>
          <p className="text-center text-xs text-muted-foreground">
            Swipe right or press A to approve, left or X to reject, R to regenerate, 1-6 to pick a reason.
          </p>
        </>
      )}

      {error ? <ErrorText message={error} /> : null}
      {notice && current ? <p className="text-sm text-muted-foreground" role="status">{notice}</p> : null}

      <dl className="grid grid-cols-3 gap-3 text-center text-sm">
        {(["approved", "rejected", "regenerated"] as const).map((k) => (
          <div key={k} className="glass-subtle rounded-2xl p-3">
            <dt className="capitalize text-muted-foreground">{k}</dt>
            <dd className="text-lg font-semibold">{queue.stats.by_status[k] ?? 0}</dd>
          </div>
        ))}
      </dl>
      {top.length ? (
        <p className="text-xs text-muted-foreground">
          Most used reasons: {top.map((r) => `${r.label} (${r.count})`).join(", ")}
        </p>
      ) : null}
    </div>
  );
}
