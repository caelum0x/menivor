"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, PartyPopper, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorText, errorMessage, useRequestOptions } from "@/components/design/shared";

import { decideIdea, getPlan, makeReel, renderCarousel } from "./api";
import { KeptCard } from "./KeptCard";
import { SwipeDeck } from "./SwipeDeck";
import type { Decision, IdeaUpdate, MonthIdea, MonthPlan, SlideSize } from "./types";

const SIZES: { id: SlideSize; label: string }[] = [
  { id: "tiktok", label: "TikTok 9:16" },
  { id: "instagram", label: "Instagram 4:5" },
];

function replaceIdea(plan: MonthPlan, update: IdeaUpdate): MonthPlan {
  return {
    ...plan,
    counts: update.counts,
    ideas: plan.ideas.map((i) => (i.id === update.idea.id ? update.idea : i)),
  };
}

/** One plan: swipe through the ideas, then make the kept ones. */
export function PlanView({ planId }: { planId: string }) {
  const getOptions = useRequestOptions();
  const [plan, setPlan] = React.useState<MonthPlan | null>(null);
  const [error, setError] = React.useState("");
  const [history, setHistory] = React.useState<string[]>([]);
  const [view, setView] = React.useState<"swipe" | "kept">("swipe");
  const [size, setSize] = React.useState<SlideSize>("tiktok");
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [bulk, setBulk] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    getOptions()
      .then((opts) => getPlan(planId, opts))
      .then((p) => {
        if (!alive) return;
        setPlan(p);
        if (p.counts.pending === 0) setView("kept");
      })
      .catch((err) => alive && setError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, [planId, getOptions]);

  const apply = React.useCallback((update: IdeaUpdate) => {
    setPlan((p) => (p ? replaceIdea(p, update) : p));
  }, []);

  // Carousel videos are made by the render worker: poll until none is pending.
  const videosPending = Boolean(
    plan?.ideas.some((i) => i.outputs.video_status === "queued" || i.outputs.video_status === "rendering"),
  );
  React.useEffect(() => {
    if (!videosPending) return;
    const timer = window.setInterval(() => {
      getOptions()
        .then((opts) => getPlan(planId, opts))
        .then((fresh) =>
          setPlan((p) =>
            p
              ? {
                  ...p,
                  ideas: p.ideas.map((i) => {
                    const next = fresh.ideas.find((f) => f.id === i.id);
                    return next ? { ...i, outputs: next.outputs, render_status: next.render_status } : i;
                  }),
                }
              : p,
          ),
        )
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [videosPending, getOptions, planId]);

  const decide = React.useCallback(
    (idea: MonthIdea, decision: Decision) => {
      // Optimistic: the card leaves at once; the server answer brings the counts.
      setPlan((p) =>
        p ? { ...p, ideas: p.ideas.map((i) => (i.id === idea.id ? { ...i, decision } : i)) } : p,
      );
      setHistory((h) => [...h, idea.id]);
      getOptions()
        .then((opts) => decideIdea(idea.id, decision, opts))
        .then(apply)
        .catch((err) => {
          setError(errorMessage(err));
          setPlan((p) =>
            p ? { ...p, ideas: p.ideas.map((i) => (i.id === idea.id ? { ...i, decision: "pending" } : i)) } : p,
          );
        });
    },
    [apply, getOptions],
  );

  const undo = () => {
    const last = history[history.length - 1];
    const idea = plan?.ideas.find((i) => i.id === last);
    if (!idea) return;
    setHistory((h) => h.slice(0, -1));
    decide(idea, "pending");
    setHistory((h) => h.slice(0, -1));
  };

  const makeAll = async () => {
    if (!plan) return;
    setBulk(true);
    setError("");
    for (const idea of plan.ideas.filter((i) => i.decision === "kept" && i.render_status === "none")) {
      setBusyId(idea.id);
      try {
        const opts = await getOptions();
        apply(idea.kind === "reel" ? await makeReel(idea, opts) : await renderCarousel(idea.id, size, opts));
      } catch (err) {
        setError(errorMessage(err));
        break;
      }
    }
    setBusyId(null);
    setBulk(false);
  };

  if (error && !plan) return <ErrorText message={error} />;
  if (!plan) return <Skeleton className="mx-auto h-[560px] w-full max-w-sm rounded-2xl" />;

  const pending = plan.ideas.filter((i) => i.decision === "pending");
  const kept = plan.ideas.filter((i) => i.decision === "kept");
  const made = kept.filter((i) => i.render_status === "done" || i.render_status === "queued").length;
  const toMake = kept.length - made;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Button asChild size="icon" variant="ghost" aria-label="All plans" title="All plans">
            <Link href="/month">
              <ArrowLeft aria-hidden />
            </Link>
          </Button>
          <div>
            <h1 className="text-xl font-semibold">{plan.name}</h1>
            <p className="text-xs text-muted-foreground">{plan.brief.website || plan.url}</p>
          </div>
        </div>
        <div className="flex rounded-full bg-secondary/40 p-1 text-sm" role="tablist">
          {(["swipe", "kept"] as const).map((v) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={view === v}
              className={`rounded-full px-4 py-1.5 ${view === v ? "bg-background font-semibold shadow" : "text-muted-foreground"}`}
              onClick={() => setView(v)}
            >
              {v === "swipe" ? `Swipe (${pending.length})` : `Kept (${kept.length})`}
            </button>
          ))}
        </div>
      </div>

      {view === "swipe" && pending.length ? (
        <SwipeDeck
          ideas={pending}
          kept={kept.length}
          total={plan.ideas.length}
          getOptions={getOptions}
          onDecide={decide}
          onUndo={undo}
          canUndo={history.length > 0}
        />
      ) : null}

      {view === "swipe" && !pending.length ? (
        <div className="mx-auto max-w-md space-y-4 py-10 text-center">
          <PartyPopper className="mx-auto size-10 text-primary" aria-hidden />
          <h2 className="text-2xl font-bold">Your month is planned</h2>
          <p className="text-muted-foreground">
            You kept {kept.length} posts. Make them now and they are ready to post.
          </p>
          <Button size="lg" onClick={() => setView("kept")} disabled={!kept.length}>
            <Sparkles aria-hidden /> See my {kept.length} posts
          </Button>
        </div>
      ) : null}

      {view === "kept" ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm">
              <span className="font-semibold text-emerald-500">{made}</span>
              <span className="text-muted-foreground"> of {kept.length} made</span>
            </p>
            <div className="flex items-center gap-2">
              <select
                className="h-9 rounded-md border border-white/10 bg-transparent px-2 text-sm"
                value={size}
                aria-label="Slide size"
                onChange={(e) => setSize(e.target.value as SlideSize)}
              >
                {SIZES.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
              <Button onClick={makeAll} disabled={bulk || toMake === 0}>
                {bulk ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
                Make all {toMake ? toMake : ""}
              </Button>
            </div>
          </div>
          <ErrorText message={error} />
          {kept.length === 0 ? (
            <p className="py-10 text-center text-muted-foreground">Swipe right on the posts you like.</p>
          ) : null}
          {kept.map((idea) => (
            <KeptCard
              key={idea.id}
              idea={idea}
              size={size}
              getOptions={getOptions}
              onUpdate={apply}
              busy={busyId === idea.id}
              setBusy={setBusyId}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
