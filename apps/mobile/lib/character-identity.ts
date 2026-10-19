/**
 * Typed client for the character-identity engine — Expo. These endpoints extend
 * the prior-wave `lib/characters.ts` (list + create) with the identity-lock
 * surface Speak Studio needs: read one owned character, bind uploaded reference
 * images, build a locked shot prompt, kick off an async LoRA training job (polled
 * via the existing `GET /jobs/{id}`), and delete a character.
 *
 *   GET    /characters/{id}                one owned character (rebuildable)
 *   POST   /characters/{id}/shot-prompt    a consistency-locked shot prompt
 *   GET    /characters/{id}/references      the bound reference images
 *   POST   /characters/{id}/references      bind an OWNED uploads/ image
 *   POST   /characters/{id}/train           train a LoRA -> { job_id } to poll
 *   DELETE /characters/{id}                 delete an owned character
 *
 * Every call is owner-scoped server-side (404 for a foreign/unknown id) and
 * flows through the shared `x-api-key` transport. No secrets here.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

/**
 * A rebuildable character-identity profile (`GET /characters/{id}`). Extends the
 * lightweight {@link import("./characters").Character} with the reference sheet
 * and trained-weight ref used by the identity lock.
 */
export interface CharacterDetail {
  id: string;
  name: string;
  descriptors: string[];
  reference_images: string[];
  style: string;
  lora_ref: string;
  identity_key: string;
}

/** Request body for `POST /characters/{id}/shot-prompt`. */
export interface ShotPromptBody {
  action: string;
  shot_index?: number;
  scene?: string;
}

/** A consistency-locked shot prompt derived from a character. */
export interface ShotPrompt {
  prompt: string;
  negative_prompt: string;
  seed: number;
  reference_images: string[];
  lora_ref: string;
}

/** Request body for `POST /characters/{id}/references`. */
export interface ReferenceBody {
  r2_key: string;
  role: string;
  content_type?: string;
  width?: number;
  height?: number;
}

/** One bound reference image row for a character. */
export interface CharacterReference {
  id: string;
  r2_key: string;
  role: string;
  content_type: string;
  width: number;
  height: number;
}

/** Request body for `POST /characters/{id}/train`. */
export interface TrainBody {
  steps?: number;
  rank?: number;
  workspace_id?: string;
}

/**
 * The async training job's handle. `job_id` is polled via the existing
 * `GET /jobs/{id}` ({@link import("./api").getJob}) to completion.
 */
export interface TrainResult {
  job_id: string;
  state: string;
  character_id: string;
}

/**
 * GET /characters/{id} — one character the caller owns (404 otherwise). Returns
 * the full identity profile (descriptors + reference sheet + optional LoRA ref).
 */
export function getCharacter(
  characterId: string,
  options?: RequestOptions,
): Promise<CharacterDetail> {
  return request<CharacterDetail>(
    `/characters/${encodeURIComponent(characterId)}`,
    { options },
  );
}

/**
 * POST /characters/{id}/shot-prompt — build a deterministic, identity-locked
 * shot prompt (+ seed + negative prompt + reference sheet) from an owned
 * character and a plain-language `action`. Pure/deterministic server-side.
 */
export function buildCharacterShotPrompt(
  characterId: string,
  body: ShotPromptBody,
  options?: RequestOptions,
): Promise<ShotPrompt> {
  return request<ShotPrompt>(
    `/characters/${encodeURIComponent(characterId)}/shot-prompt`,
    { method: "POST", body, options },
  );
}

/**
 * GET /characters/{id}/references — the reference images bound to an owned
 * character. The backend returns them under `references`; the list is normalized
 * defensively so a blank payload degrades to `[]`.
 */
export async function listCharacterReferences(
  characterId: string,
  options?: RequestOptions,
): Promise<CharacterReference[]> {
  const data = await request<{ references?: CharacterReference[] }>(
    `/characters/${encodeURIComponent(characterId)}/references`,
    { options },
  );
  return Array.isArray(data?.references) ? data.references : [];
}

/**
 * POST /characters/{id}/references — bind an image the caller OWNS (an
 * `uploads/` R2 key minted with `presignAndUpload`) as a character reference.
 * The backend rejects a foreign key (403) and an unknown character (404).
 */
export function addCharacterReference(
  characterId: string,
  body: ReferenceBody,
  options?: RequestOptions,
): Promise<CharacterReference> {
  return request<CharacterReference>(
    `/characters/${encodeURIComponent(characterId)}/references`,
    { method: "POST", body, options },
  );
}

/**
 * POST /characters/{id}/train — start one async character-LoRA training job and
 * return its `job_id` to poll via `GET /jobs/{id}`. Requires at least one bound
 * reference (400 otherwise) and spends credits (402 on insufficient); the debit
 * is committed before enqueue so training can never run for free.
 */
export function trainCharacter(
  characterId: string,
  body: TrainBody = {},
  options?: RequestOptions,
): Promise<TrainResult> {
  return request<TrainResult>(
    `/characters/${encodeURIComponent(characterId)}/train`,
    { method: "POST", body, options },
  );
}

/** DELETE /characters/{id} — delete an owned character (404 for a foreign id). */
export function deleteCharacter(
  characterId: string,
  options?: RequestOptions,
): Promise<{ deleted: boolean; id: string }> {
  return request<{ deleted: boolean; id: string }>(
    `/characters/${encodeURIComponent(characterId)}`,
    { method: "DELETE", options },
  );
}
