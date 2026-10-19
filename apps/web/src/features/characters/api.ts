/** Reusable identity-locked characters API (P9 consistency moat). */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface Character {
  id: string;
  name: string;
  descriptors: string[];
  reference_images: string[];
  style: string;
  lora_ref: string;
  identity_key: string;
  deduped?: boolean;
}

export interface CreateCharacterBody {
  name: string;
  descriptors?: string[];
  reference_images?: string[];
  negative?: string[];
  style?: string;
  lora_ref?: string;
}

export function listCharacters(options?: RequestOptions): Promise<{ characters: Character[] }> {
  return apiRequest<{ characters: Character[] }>("/characters", { options });
}

export function createCharacter(body: CreateCharacterBody, options?: RequestOptions): Promise<Character> {
  return apiRequest<Character>("/characters", { method: "POST", body, options });
}

/** Fetch one owned character (rebuildable profile) — GET /characters/{id}. */
export function getCharacter(id: string, options?: RequestOptions): Promise<Character> {
  return apiRequest<Character>(`/characters/${encodeURIComponent(id)}`, { options });
}

/** Result of DELETE /characters/{id}. */
export interface DeleteCharacterResult {
  deleted: boolean;
  id: string;
}

/** Delete an owned character — DELETE /characters/{id}. */
export function deleteCharacter(
  id: string,
  options?: RequestOptions,
): Promise<DeleteCharacterResult> {
  return apiRequest<DeleteCharacterResult>(`/characters/${encodeURIComponent(id)}`, {
    method: "DELETE",
    options,
  });
}

export interface ShotPrompt {
  prompt: string;
  negative_prompt: string;
  seed: number;
  reference_images: string[];
  lora_ref: string;
}

export function characterShotPrompt(
  id: string,
  body: { action: string; shot_index?: number; scene?: string },
  options?: RequestOptions,
): Promise<ShotPrompt> {
  return apiRequest<ShotPrompt>(`/characters/${encodeURIComponent(id)}/shot-prompt`, {
    method: "POST",
    body,
    options,
  });
}
