"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ErrorText, errorMessage } from "@/src/features/ad-studio/shared";
import type { RequestOptions } from "@/src/shared/api";
import { createActor, type Actor } from "./api";

const EMPTY = { name: "", persona: "", look_prompt: "", voice_design_prompt: "", product_shot_template: "" };
export const ATTEST_TEXT = "This is an original, synthetic person. No real person's face, name or voice.";

export function CreateActorForm({
  getOptions,
  onCreated,
}: {
  getOptions: () => Promise<RequestOptions>;
  onCreated: (actor: Actor) => void;
}) {
  const [form, setForm] = React.useState(EMPTY);
  const [attest, setAttest] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const set = (key: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));
  const ready = attest && form.name.trim() && form.look_prompt.trim() && form.voice_design_prompt.trim();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError("");
    try {
      const actor = await createActor({ ...form, attest_synthetic: attest }, await getOptions());
      setForm(EMPTY);
      setAttest(false);
      onCreated(actor);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Create an actor">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="actor-name">Name</Label>
          <Input id="actor-name" value={form.name} onChange={set("name")} maxLength={80} placeholder="An invented name" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="actor-persona">Persona</Label>
          <Input id="actor-persona" value={form.persona} onChange={set("persona")} maxLength={1000} placeholder="Who they are, in one line" />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="actor-look">Look</Label>
        <Textarea id="actor-look" rows={2} value={form.look_prompt} onChange={set("look_prompt")} maxLength={2000}
          placeholder="Age, hair, clothes, setting. The face is generated from this." />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="actor-voice">Voice</Label>
        <Textarea id="actor-voice" rows={2} value={form.voice_design_prompt} onChange={set("voice_design_prompt")}
          maxLength={1000} placeholder="Tone, pace, accent. The voice is designed from this text." />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="actor-shot">Product shot</Label>
        <Textarea id="actor-shot" rows={2} value={form.product_shot_template} onChange={set("product_shot_template")}
          maxLength={2000} placeholder="Holds {product} at chest height and smiles. Use {product} where the product goes." />
      </div>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} className="mt-0.5" />
        <span>{ATTEST_TEXT}</span>
      </label>
      <ErrorText message={error} />
      <Button type="submit" disabled={!ready || busy}>
        {busy ? "Creating..." : "Create actor"}
      </Button>
    </form>
  );
}
