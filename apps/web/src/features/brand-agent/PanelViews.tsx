"use client";

import * as React from "react";
import { CalendarClock, Library, Lightbulb, Loader2, Plug, Wand2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import type { RequestOptions } from "@/src/shared/api";
import {
  addInspiration,
  createRoutine,
  listConnectors,
  listInspirations,
  listLibrary,
  listRoutines,
  listSkills,
  setRoutineEnabled,
  type Connector,
  type Inspiration,
  type LibraryItem,
  type Routine,
  type Skill,
} from "./api";

function useList<T>(load: (opts: RequestOptions) => Promise<T[]>, deps: unknown[] = []) {
  const requestOptions = useRequestOptions();
  const [items, setItems] = React.useState<T[] | null>(null);
  const [error, setError] = React.useState("");
  const reload = React.useCallback(async () => {
    try {
      setItems(await load(await requestOptions()));
    } catch (err) {
      setError(errorMessage(err));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- caller-controlled deps
  }, [requestOptions, ...deps]);
  React.useEffect(() => {
    void reload();
  }, [reload]);
  return { items, error, reload, requestOptions };
}

function Header({ icon: Icon, title, hint }: { icon: typeof Library; title: string; hint: string }) {
  return (
    <div className="mb-4 space-y-1">
      <h2 className="flex items-center gap-2 text-lg font-semibold">
        <Icon className="size-5 text-primary" aria-hidden /> {title}
      </h2>
      <p className="text-sm text-muted-foreground">{hint}</p>
    </div>
  );
}

function Loading() {
  return <Loader2 className="size-5 animate-spin text-muted-foreground" aria-label="Loading" />;
}

export function LibraryView({ folderId }: { folderId?: string }) {
  const { items, error } = useList<LibraryItem>((o) => listLibrary(folderId, o), [folderId]);
  return (
    <div>
      <Header icon={Library} title="Library" hint="Everything the agent made after you approved it." />
      <ErrorText message={error} />
      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing yet. Approve an image or video and it lands here.</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {items.map((item) => (
            <li key={item.id} className="glass-subtle rounded-xl border border-border p-3 text-sm">
              <p className="font-medium">{item.title || item.kind}</p>
              <p className="text-muted-foreground">
                {item.kind} {item.url ? <a className="underline" href={item.url}>open</a> : item.ref}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const STATUS_LABEL: Record<Connector["status"], string> = {
  connected: "Connected",
  not_connected: "Not connected",
  unavailable: "Not available yet",
  off: "Off",
};

export function ConnectorsView() {
  const { items, error } = useList<Connector>((o) => listConnectors(o));
  return (
    <div>
      <Header icon={Plug} title="Connectors" hint="What the agent can reach. Nothing posts or spends without you." />
      <ErrorText message={error} />
      {!items ? (
        <Loading />
      ) : (
        <ul className="space-y-2">
          {items.map((c) => (
            <li key={c.id} className="glass-subtle flex items-center justify-between rounded-xl border border-border p-3">
              <span>
                <span className="font-medium">{c.name}</span>
                {c.detail && <span className="block text-sm text-muted-foreground">{c.detail}</span>}
              </span>
              <Badge variant={c.status === "connected" ? "success" : "secondary"}>{STATUS_LABEL[c.status]}</Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function RoutinesView() {
  const { items, error, reload, requestOptions } = useList<Routine>((o) => listRoutines(o));
  const [text, setText] = React.useState("");
  const [formError, setFormError] = React.useState("");
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    try {
      await createRoutine(text.trim(), await requestOptions());
      setText("");
      await reload();
    } catch (err) {
      setFormError(errorMessage(err));
    }
  };
  const toggle = async (r: Routine) => {
    await setRoutineEnabled(r.id, !r.enabled, await requestOptions());
    await reload();
  };
  return (
    <div>
      <Header
        icon={CalendarClock}
        title="Routines"
        hint="Scheduled work. Each run waits in your approvals before anything is made or posted."
      />
      <form onSubmit={add} className="mb-4 flex gap-2">
        <label htmlFor="routine-text" className="sr-only">
          New routine
        </label>
        <Input
          id="routine-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="3 new ad variations every Monday"
        />
        <Button type="submit" disabled={!text.trim()}>
          Add routine
        </Button>
      </form>
      <ErrorText message={error || formError} />
      {!items ? (
        <Loading />
      ) : (
        <ul className="space-y-2">
          {items.map((r) => (
            <li key={r.id} className="glass-subtle flex items-center justify-between rounded-xl border border-border p-3">
              <span className="text-sm">
                <span className="font-medium">{r.name}</span>
                <span className="block text-muted-foreground">
                  {r.count} x {r.skill.replace(/_/g, " ")}, {r.weekday_name} at {String(r.hour).padStart(2, "0")}:00 UTC
                </span>
              </span>
              <Button type="button" size="sm" variant="ghost" onClick={() => void toggle(r)}>
                {r.enabled ? "Pause" : "Resume"}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SkillsView({ onUse }: { onUse: (prompt: string) => void }) {
  const { items, error } = useList<Skill>((o) => listSkills(o));
  return (
    <div>
      <Header icon={Wand2} title="Skills" hint="Reusable recipes. Pick one to start a message with it." />
      <ErrorText message={error} />
      {!items ? (
        <Loading />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {items.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onUse(s.prompt)}
                className="glass-subtle w-full rounded-xl border border-border p-3 text-left text-sm hover:border-primary/40"
              >
                <span className="font-medium">{s.name}</span>
                <span className="block text-muted-foreground">{s.description}</span>
                {s.spends_credits && <span className="block pt-1 text-xs text-muted-foreground">Needs approval</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function InspirationsView() {
  const { items, error, reload, requestOptions } = useList<Inspiration>((o) => listInspirations(o));
  const [url, setUrl] = React.useState("");
  const [formError, setFormError] = React.useState("");
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    try {
      await addInspiration(url.trim(), await requestOptions());
      setUrl("");
      await reload();
    } catch (err) {
      setFormError(errorMessage(err));
    }
  };
  return (
    <div>
      <Header
        icon={Lightbulb}
        title="Inspirations"
        hint="Saved ads and TikTok links. Ask the agent to clone one for your brand."
      />
      <form onSubmit={add} className="mb-4 flex gap-2">
        <label htmlFor="inspiration-url" className="sr-only">
          Ad or TikTok link
        </label>
        <Input id="inspiration-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" />
        <Button type="submit" disabled={!url.trim()}>
          Save link
        </Button>
      </form>
      <ErrorText message={error || formError} />
      {!items ? (
        <Loading />
      ) : (
        <ul className="space-y-2">
          {items.map((i) => (
            <li key={i.id} className="glass-subtle rounded-xl border border-border p-3 text-sm">
              <a href={i.url} className="font-medium underline" target="_blank" rel="noreferrer noopener">
                {i.title || i.url}
              </a>
              <span className="block text-muted-foreground">
                {i.kind} {i.source === "meta_ads" ? "· from Meta Ads" : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
