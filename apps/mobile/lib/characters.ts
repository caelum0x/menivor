/**
 * Typed client for the saved-characters engine — Expo.
 *
 * List reusable character identities (name + descriptors + style) and create
 * new ones. Mirrors the web characters feature.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export interface Character {
  id: string;
  name: string;
  descriptors: string[];
  style: string;
  identity_key: string;
}

export interface CreateCharacterBody {
  name: string;
  descriptors?: string[];
  style?: string;
}

export function listCharacters(options?: RequestOptions): Promise<{ characters: Character[] }> {
  return request<{ characters: Character[] }>("/characters", { options });
}

export function createCharacter(
  body: CreateCharacterBody,
  options?: RequestOptions,
): Promise<Character> {
  return request<Character>("/characters", { method: "POST", body, options });
}
