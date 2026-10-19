"use client";

import * as React from "react";
import { ShieldCheck, UserRoundCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { ActorAvatar } from "./ActorAvatar";
import { ActorDetail } from "./ActorDetail";
import { CreateActorForm } from "./CreateActorForm";
import { addPreset, listActors, type Actor, type ActorsListing } from "./api";

const CARD = "rounded-2xl border border-white/10 bg-white/[0.03] p-4 shadow-[inset_0_1px_0_hsl(0_0%_100%/0.05)]";

/** AI actors: original synthetic presets, my actors, and one actor's face, voice and product shot. */
export function ActorsWorkspace() {
  const requestOptions = useRequestOptions();
  const [data, setData] = React.useState<ActorsListing | null>(null);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      setData(await listActors(await requestOptions()));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [requestOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const upsert = (actor: Actor) => {
    setData((d) => (d ? { ...d, mine: [actor, ...d.mine.filter((a) => a.id !== actor.id)] } : d));
    setSelected(actor.id);
  };

  async function add(slug: string) {
    setError("");
    try {
      upsert(await addPreset(slug, await requestOptions()));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const current = data?.mine.find((a) => a.id === selected) ?? null;

  return (
    <div className="space-y-6" data-testid="actors-page">
      <header className="space-y-2">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <UserRoundCheck className="size-6 text-primary" aria-hidden /> AI actors
        </h1>
        <ul className="space-y-1 text-sm text-muted-foreground" aria-label="Rules">
          {(data?.rules ?? []).map((r) => (
            <li key={r} className="flex items-start gap-2">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden /> {r}
            </li>
          ))}
        </ul>
      </header>
      <ErrorText message={error} />

      <section className="space-y-3" aria-label="Presets">
        <h2 className="text-lg font-semibold">Presets</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(data?.presets ?? []).map((p) => (
            <div key={p.id} className={`${CARD} flex flex-col gap-3`}>
              <div className="flex items-center gap-3">
                <ActorAvatar name={p.name} url={p.face_image_url} />
                <div className="min-w-0">
                  <p className="font-medium">{p.name}</p>
                  <p className="text-xs text-muted-foreground">{p.persona}</p>
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={() => add(p.slug)}>Use</Button>
            </div>
          ))}
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
        <section className={`${CARD} space-y-3`} aria-label="My actors">
          <h2 className="text-lg font-semibold">My actors</h2>
          {data && data.mine.length === 0 ? <p className="text-sm text-muted-foreground">No actors yet. Use a preset or create one.</p> : null}
          <ul className="space-y-2">
            {(data?.mine ?? []).map((a) => (
              <li key={a.id}>
                <button
                  type="button"
                  onClick={() => setSelected(a.id)}
                  aria-pressed={selected === a.id}
                  className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left ${selected === a.id ? "border-primary/40 bg-primary/[0.06]" : "border-white/10"}`}
                >
                  <ActorAvatar name={a.name} url={a.face_image_url} size={40} />
                  <span className="flex-1">
                    <span className="block text-sm font-medium">{a.name}</span>
                    <span className="block text-xs text-muted-foreground">{a.status === "ready" ? "Ready" : "Needs a face"}{a.voice_id ? ", voice designed" : ""}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <h3 className="pt-2 text-sm font-semibold">Create an actor</h3>
          <CreateActorForm getOptions={requestOptions} onCreated={upsert} />
        </section>
        <section className={CARD} aria-label="Actor">
          {current ? (
            <ActorDetail key={current.id} actor={current} getOptions={requestOptions} onChanged={upsert} />
          ) : (
            <p className="text-sm text-muted-foreground">Pick an actor to make its face, design its voice and price a product shot.</p>
          )}
        </section>
      </div>
    </div>
  );
}
