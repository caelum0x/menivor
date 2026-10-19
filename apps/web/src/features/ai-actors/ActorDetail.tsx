"use client";

import * as React from "react";
import Link from "next/link";
import { AudioLines, Clapperboard, ScanFace } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ErrorText, errorMessage } from "@/src/features/ad-studio/shared";
import type { RequestOptions } from "@/src/shared/api";
import { ActorAvatar } from "./ActorAvatar";
import {
  designVoice,
  listLibraryImages,
  lockVoice,
  planShot,
  proposeFace,
  submitRender,
  setActorFace as setFace,
  type Actor,
  type LibraryImage,
  type StudioRender,
  type VoicePreview,
} from "./api";

type Opts = () => Promise<RequestOptions>;

function text(value: unknown): string {
  return value === undefined || value === null || value === "" ? "" : String(value);
}

export function ProvenanceList({ actor }: { actor: Actor }) {
  const p = actor.provenance;
  const c = actor.consent;
  const rows: [string, string][] = [
    ["Synthetic person", p.synthetic ? "Yes" : "No"],
    ["Made by", text(p.generator)],
    ["Face", text(p.face)],
    ["Face prompt", text(p.face_prompt)],
    ["Voice", p.voice ? `Designed from ${text(p.voice_designed_from) || "a text prompt"}` : "Not designed yet"],
    ["Consent", text(c.type).replace(/_/g, " ")],
    ["Attested by", text(c.attested_by)],
    ["Attested at", text(c.attested_at)],
  ];
  return (
    <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-xs" aria-label="Provenance">
      {rows.filter(([, v]) => v).map(([k, v]) => (
        <React.Fragment key={k}>
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="break-words">{v}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function Section({ icon: Icon, title, children }: { icon: typeof ScanFace; title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2 rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <h3 className="flex items-center gap-2 text-sm font-medium">
        <Icon className="size-4 text-primary" aria-hidden /> {title}
      </h3>
      {children}
    </section>
  );
}

function FacePanel({ actor, getOptions, onChanged }: { actor: Actor; getOptions: Opts; onChanged: (a: Actor) => void }) {
  const [queued, setQueued] = React.useState<number | null>(null);
  const [images, setImages] = React.useState<LibraryImage[] | null>(null);
  const [pick, setPick] = React.useState("");
  const [error, setError] = React.useState("");
  const run = async (fn: () => Promise<void>) => {
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  return (
    <Section icon={ScanFace} title="Face">
      <p className="text-xs text-muted-foreground">Generated from the look prompt. Uploads are not used.</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => run(async () => setQueued((await proposeFace(actor.id, await getOptions())).credits_estimate))}>
          Make face
        </Button>
        <Button variant="ghost" size="sm" onClick={() => run(async () => setImages(await listLibraryImages(await getOptions())))}>
          Use generated face
        </Button>
      </div>
      {queued !== null ? (
        <p className="text-sm" role="status">
          Face queued for approval ({queued} credits). <Link className="underline" href="/agent">Approve in Agent</Link>
        </p>
      ) : null}
      {images ? (
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1">
            <Label htmlFor={`face-pick-${actor.id}`}>Generated image</Label>
            <Select id={`face-pick-${actor.id}`} value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">Pick an image</option>
              {images.map((i) => <option key={i.id} value={i.id}>{i.title || i.id}</option>)}
            </Select>
          </div>
          <Button variant="outline" size="sm" disabled={!pick}
            onClick={() => run(async () => onChanged(await setFace(actor.id, pick, await getOptions())))}>
            Set as face
          </Button>
        </div>
      ) : null}
      <ErrorText message={error} />
    </Section>
  );
}

function VoicePanel({ actor, getOptions, onChanged }: { actor: Actor; getOptions: Opts; onChanged: (a: Actor) => void }) {
  const [previews, setPreviews] = React.useState<VoicePreview[] | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  async function design() {
    setBusy(true);
    setError("");
    try {
      setPreviews((await designVoice(actor.id, await getOptions())).previews);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  async function keep(id: string) {
    setError("");
    try {
      onChanged(await lockVoice(actor.id, id, await getOptions()));
      setPreviews(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <Section icon={AudioLines} title="Voice">
      <p className="text-xs text-muted-foreground">
        {actor.voice_id ? "Designed voice saved." : "Designed from the voice prompt. Never cloned."}
      </p>
      <Button variant="outline" size="sm" disabled={busy} onClick={design}>
        {busy ? "Designing..." : "Design voice"}
      </Button>
      {previews?.map((p, i) => (
        <div key={p.generated_voice_id} className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Preview {i + 1}</span>
          {p.audio_base_64 ? (
            <audio controls src={`data:${p.media_type || "audio/mpeg"};base64,${p.audio_base_64}`} className="h-8" />
          ) : null}
          <Button variant="ghost" size="sm" onClick={() => keep(p.generated_voice_id)}>Use this voice</Button>
        </div>
      ))}
      <ErrorText message={error} />
    </Section>
  );
}

function ShotPanel({ actor, getOptions }: { actor: Actor; getOptions: Opts }) {
  const [product, setProduct] = React.useState("");
  const [seconds, setSeconds] = React.useState("5");
  const [aspect, setAspect] = React.useState("9:16");
  const [render, setRender] = React.useState<StudioRender | null>(null);
  const [error, setError] = React.useState("");
  const run = async (fn: () => Promise<void>) => {
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  return (
    <Section icon={Clapperboard} title="Product shot">
      <div className="grid gap-2 sm:grid-cols-[1fr_6rem_6rem]">
        <div className="space-y-1">
          <Label htmlFor={`shot-product-${actor.id}`}>Product</Label>
          <Input id={`shot-product-${actor.id}`} value={product} onChange={(e) => setProduct(e.target.value)} maxLength={200} />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`shot-seconds-${actor.id}`}>Seconds</Label>
          <Select id={`shot-seconds-${actor.id}`} value={seconds} onChange={(e) => setSeconds(e.target.value)}>
            <option value="5">5</option>
            <option value="10">10</option>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor={`shot-aspect-${actor.id}`}>Shape</Label>
          <Select id={`shot-aspect-${actor.id}`} value={aspect} onChange={(e) => setAspect(e.target.value)}>
            <option value="9:16">9:16</option>
            <option value="16:9">16:9</option>
            <option value="1:1">1:1</option>
          </Select>
        </div>
      </div>
      {!render ? (
        <Button variant="outline" size="sm" disabled={!product.trim()}
          onClick={() => run(async () => setRender(await planShot(actor.id, { product, seconds: Number(seconds), aspect }, await getOptions())))}>
          Price the shot
        </Button>
      ) : null}
      {render ? (
        <div className="space-y-2 text-sm" aria-label="Shot price">
          <p>
            {render.title}: about ${render.quote_usd.toFixed(2)} engine cost, {render.credits} AI-video credits.
          </p>
          {render.status === "planned" ? (
            <Button variant="outline" size="sm" onClick={() => run(async () => setRender(await submitRender(render.id, await getOptions())))}>
              Send for approval
            </Button>
          ) : (
            <p role="status">
              <Badge variant="secondary">Waiting for approval</Badge>{" "}
              <Link className="underline" href="/approvals">Open approvals</Link>
            </p>
          )}
        </div>
      ) : null}
      <ErrorText message={error} />
    </Section>
  );
}

export function ActorDetail({ actor, getOptions, onChanged }: { actor: Actor; getOptions: Opts; onChanged: (a: Actor) => void }) {
  return (
    <div className="space-y-3" data-testid="actor-detail">
      <div className="flex items-center gap-3">
        <ActorAvatar name={actor.name} url={actor.face_image_url} size={72} />
        <div>
          <h2 className="text-lg font-semibold">{actor.name}</h2>
          <p className="text-sm text-muted-foreground">{actor.persona}</p>
          <Badge variant={actor.status === "ready" ? "success" : "secondary"}>{actor.status === "ready" ? "Ready" : "Needs a face"}</Badge>
        </div>
      </div>
      <ProvenanceList actor={actor} />
      <FacePanel actor={actor} getOptions={getOptions} onChanged={onChanged} />
      <VoicePanel actor={actor} getOptions={getOptions} onChanged={onChanged} />
      <ShotPanel actor={actor} getOptions={getOptions} />
    </div>
  );
}
