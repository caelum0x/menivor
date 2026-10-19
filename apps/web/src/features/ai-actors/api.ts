/** AI actors client: presets, my actors, face, designed voice and product-shot renders. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import { apiPath } from "@/src/shared/api/path";

export interface Actor {
  id: string;
  slug: string;
  name: string;
  persona: string;
  look_prompt: string;
  voice_design_prompt: string;
  product_shot_template: string;
  face_image_url: string;
  voice_id: string;
  builtin: boolean;
  status: string;
  provenance: Record<string, unknown>;
  consent: Record<string, unknown>;
}

export interface ActorsListing {
  presets: Actor[];
  mine: Actor[];
  rules: string[];
}

export interface ActorInput {
  name: string;
  persona: string;
  look_prompt: string;
  voice_design_prompt: string;
  product_shot_template: string;
  attest_synthetic: boolean;
}

export interface GateAction {
  id: string;
  status: string;
  title: string;
  credits_estimate: number;
}

export interface VoicePreview {
  generated_voice_id: string;
  audio_base_64?: string;
  media_type?: string;
}

export interface StudioRender {
  id: string;
  kind: string;
  status: string;
  title: string;
  plan: Record<string, unknown>;
  quote_usd: number;
  credits: number;
  approval_item_id: string | null;
  result: Record<string, unknown>;
  error: string;
  created_at: string | null;
}

export interface LibraryImage {
  id: string;
  kind: string;
  url: string;
  title: string;
}


export function listActors(options?: RequestOptions): Promise<ActorsListing> {
  return apiRequest<ActorsListing>("/actors", { options });
}

export async function createActor(input: ActorInput, options?: RequestOptions): Promise<Actor> {
  return (await apiRequest<{ actor: Actor }>("/actors", { method: "POST", body: input, options })).actor;
}

export async function addPreset(slug: string, options?: RequestOptions): Promise<Actor> {
  return (await apiRequest<{ actor: Actor }>(apiPath`/actors/presets/${slug}/use`, { method: "POST", options })).actor;
}

export async function proposeFace(actorId: string, options?: RequestOptions): Promise<GateAction> {
  return (await apiRequest<{ action: GateAction }>(apiPath`/actors/${actorId}/face`, { method: "POST", body: {}, options }))
    .action;
}

export async function setActorFace(actorId: string, libraryItemId: string, options?: RequestOptions): Promise<Actor> {
  return (
    await apiRequest<{ actor: Actor }>(apiPath`/actors/${actorId}/face/use`, {
      method: "POST",
      body: { library_item_id: libraryItemId },
      options,
    })
  ).actor;
}

export function designVoice(
  actorId: string,
  options?: RequestOptions,
): Promise<{ actor_id: string; prompt: string; previews: VoicePreview[] }> {
  return apiRequest(apiPath`/actors/${actorId}/voice/design`, { method: "POST", body: {}, options });
}

export async function lockVoice(actorId: string, generatedVoiceId: string, options?: RequestOptions): Promise<Actor> {
  return (
    await apiRequest<{ actor: Actor }>(apiPath`/actors/${actorId}/voice/lock`, {
      method: "POST",
      body: { generated_voice_id: generatedVoiceId },
      options,
    })
  ).actor;
}

export async function planShot(
  actorId: string,
  body: { product: string; seconds: number; aspect: string },
  options?: RequestOptions,
): Promise<StudioRender> {
  return (await apiRequest<{ render: StudioRender }>(apiPath`/actors/${actorId}/shots/plan`, { method: "POST", body, options }))
    .render;
}

export async function submitRender(renderId: string, options?: RequestOptions): Promise<StudioRender> {
  return (await apiRequest<{ render: StudioRender }>(apiPath`/studio-renders/${renderId}/submit`, { method: "POST", options }))
    .render;
}

export async function listRenders(kind: string, options?: RequestOptions): Promise<StudioRender[]> {
  return (await apiRequest<{ renders: StudioRender[] }>(apiPath`/studio-renders?kind=${kind}`, { options })).renders;
}

export async function listLibraryImages(options?: RequestOptions): Promise<LibraryImage[]> {
  const items = (await apiRequest<{ items: LibraryImage[] }>("/agent/library", { options })).items;
  return items.filter((i) => i.kind === "image" && i.url);
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}
