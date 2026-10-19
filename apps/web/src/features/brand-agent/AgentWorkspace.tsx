"use client";

import * as React from "react";
import Link from "next/link";
import {
  Brain,
  CalendarClock,
  Coins,
  Folder,
  History,
  Library,
  Lightbulb,
  MessageSquare,
  Plug,
  Plus,
  Wand2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { createFolder, createSession, getOverview, type AgentOverview } from "./api";
import { BrainView } from "./BrainView";
import { ChatView } from "./ChatView";
import { ConnectorsView, InspirationsView, LibraryView, RoutinesView, SkillsView } from "./PanelViews";

export type AgentPanel = "chat" | "brain" | "library" | "connectors" | "routines" | "skills" | "inspirations";

const TABS = [
  { href: "/studio", label: "Studio" },
  { href: "/workflows", label: "Workflow" },
  { href: "/agent", label: "Agent" },
] as const;

const NAV: { id: AgentPanel; label: string; icon: typeof Brain }[] = [
  { id: "brain", label: "Brain", icon: Brain },
  { id: "library", label: "Library", icon: Library },
  { id: "connectors", label: "Connectors", icon: Plug },
  { id: "routines", label: "Routines", icon: CalendarClock },
  { id: "skills", label: "Skills", icon: Wand2 },
  { id: "inspirations", label: "Inspirations", icon: Lightbulb },
];

function CreditsMeter({ credits }: { credits: AgentOverview["credits"] }) {
  const total = Math.max(credits.trial_grant, credits.balance + credits.used, 1);
  const pct = Math.min(100, Math.round((credits.balance / total) * 100));
  return (
    <div className="space-y-1.5 rounded-xl border border-border p-3" aria-label="Credits">
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <Coins className="size-3.5" aria-hidden /> {credits.balance} credits left
      </p>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
        <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
      </div>
      <Link href="/billing" className="text-xs text-muted-foreground underline-offset-2 hover:underline">
        Get more credits
      </Link>
    </div>
  );
}

/** Arcads-style agent workspace: sidebar (tabs, sessions, Brain, library...) + the active panel. */
export function AgentWorkspace() {
  const requestOptions = useRequestOptions();
  const [overview, setOverview] = React.useState<AgentOverview | null>(null);
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [panel, setPanel] = React.useState<AgentPanel>("chat");
  const [folderId, setFolderId] = React.useState<string | undefined>(undefined);
  const [prefill, setPrefill] = React.useState("");
  const [error, setError] = React.useState("");

  const refresh = React.useCallback(async () => {
    try {
      const data = await getOverview(undefined, await requestOptions());
      setOverview(data);
      return data;
    } catch (err) {
      setError(errorMessage(err));
      return null;
    }
  }, [requestOptions]);

  const newSession = React.useCallback(async () => {
    try {
      const created = await createSession(overview?.space.id, await requestOptions());
      setSessionId(created.id);
      setPanel("chat");
      void refresh();
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [overview?.space.id, requestOptions, refresh]);

  React.useEffect(() => {
    void (async () => {
      const data = await refresh();
      if (data && data.recents.length > 0) setSessionId(data.recents[0]!.id);
      else if (data) {
        const created = await createSession(data.space.id, await requestOptions());
        setSessionId(created.id);
      }
    })();
    // first load only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addFolder = async () => {
    const name = typeof window !== "undefined" ? window.prompt("Folder name")?.trim() : "";
    if (!name) return;
    try {
      await createFolder(name, await requestOptions());
      void refresh();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const onSeen = React.useCallback(() => void refresh(), [refresh]);
  const unseen = overview?.brain.unseen ?? 0;

  return (
    <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
      <aside className="glass space-y-5 rounded-2xl border border-border p-4 lg:sticky lg:top-20 lg:self-start">
        <nav aria-label="Workspace" className="grid grid-cols-3 gap-1 rounded-xl bg-white/[0.04] p-1 text-center text-sm">
          {TABS.map((tab) => (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={tab.href === "/agent" ? "page" : undefined}
              className={
                tab.href === "/agent"
                  ? "rounded-lg bg-white/10 px-2 py-1.5 font-medium"
                  : "rounded-lg px-2 py-1.5 text-muted-foreground hover:text-foreground"
              }
            >
              {tab.label}
            </Link>
          ))}
        </nav>

        <Button type="button" variant="outline" className="w-full justify-start" onClick={() => void newSession()}>
          <Plus className="size-4" aria-hidden /> New session
        </Button>

        <ul className="space-y-0.5" aria-label="Agent sections">
          <li>
            <button
              type="button"
              onClick={() => setPanel("chat")}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-white/5"
              aria-current={panel === "chat" ? "page" : undefined}
            >
              <MessageSquare className="size-4 text-muted-foreground" aria-hidden /> Chat
            </button>
          </li>
          {NAV.map(({ id, label, icon: Icon }) => (
            <li key={id}>
              <button
                type="button"
                onClick={() => {
                  setPanel(id);
                  if (id === "library") setFolderId(undefined);
                }}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-white/5"
                aria-current={panel === id ? "page" : undefined}
              >
                <Icon className="size-4 text-muted-foreground" aria-hidden /> {label}
                {id === "brain" && unseen > 0 && (
                  <span
                    className="ml-auto rounded-full bg-primary/20 px-1.5 text-xs text-primary"
                    aria-label={`${unseen} new brand memory updates`}
                  >
                    {unseen}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>

        <div className="space-y-1">
          <div className="flex items-center justify-between px-2 text-xs uppercase tracking-wide text-muted-foreground">
            Folders
            <button type="button" onClick={() => void addFolder()} aria-label="New folder" className="hover:text-foreground">
              <Plus className="size-3.5" aria-hidden />
            </button>
          </div>
          {(overview?.folders ?? []).map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => {
                setFolderId(f.id);
                setPanel("library");
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-sm hover:bg-white/5"
            >
              <Folder className="size-4 text-muted-foreground" aria-hidden /> {f.name}
            </button>
          ))}
        </div>

        <div className="space-y-1">
          <p className="px-2 text-xs uppercase tracking-wide text-muted-foreground">Recents</p>
          {(overview?.recents ?? []).slice(0, 8).map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                setSessionId(s.id);
                setPanel("chat");
              }}
              className="flex w-full items-center gap-2 truncate rounded-lg px-2 py-1 text-left text-sm hover:bg-white/5"
              aria-current={s.id === sessionId ? "true" : undefined}
            >
              <History className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate">{s.title}</span>
            </button>
          ))}
        </div>

        {overview && <CreditsMeter credits={overview.credits} />}
      </aside>

      <section className="min-w-0">
        <ErrorText message={error} />
        {panel === "chat" && sessionId && (
          <ChatView key={sessionId} sessionId={sessionId} prefill={prefill} onTurn={() => void refresh()} />
        )}
        {panel === "brain" && overview && <BrainView spaceId={overview.space.id} onSeen={onSeen} />}
        {panel === "library" && <LibraryView folderId={folderId} />}
        {panel === "connectors" && <ConnectorsView />}
        {panel === "routines" && <RoutinesView />}
        {panel === "skills" && (
          <SkillsView
            onUse={(prompt) => {
              setPrefill(prompt);
              setPanel("chat");
            }}
          />
        )}
        {panel === "inspirations" && <InspirationsView />}
      </section>
    </div>
  );
}
