/**
 * Typed client for the BYOK (bring-your-own-provider-key) vault — Expo.
 *
 * Store, list, and revoke the caller's OWN provider API keys (OpenRouter,
 * ElevenLabs, HeyGen, …) that the routing layer uses for renders when BYOK is
 * consented. Mirrors the API domain in `apps/api/app/domains/byok`.
 *
 * SECURITY: the raw secret is write-only. It is accepted on `addProviderKey`,
 * encrypted at rest server-side, and NEVER returned by any endpoint — list and
 * revoke expose only a non-secret `key_prefix` hint plus metadata.
 *
 * Endpoints:
 *   POST   /byok/keys            store a provider key (encrypted at rest)
 *   GET    /byok/keys            list the caller's keys (no secrets)
 *   DELETE /byok/keys/{key_id}   revoke one owned key (immediate)
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

/** Status of a stored provider key. */
export type ProviderKeyStatus = "active" | "revoked";

/**
 * Client-facing view of a stored provider key. Never carries the ciphertext or
 * raw secret — only the masked `key_prefix` hint and routing metadata.
 */
export interface ProviderKey {
  readonly id: string;
  /** Provider slug the key routes to, e.g. "openrouter". */
  readonly provider_key: string;
  readonly label: string;
  /** Non-secret display hint, e.g. "sk-…AB". */
  readonly key_prefix: string;
  readonly scope: string;
  /** Routing priority — higher wins when several keys exist for a provider. */
  readonly priority: number;
  readonly status: ProviderKeyStatus | string;
  readonly use_count: number;
  readonly last_used_at: string | null;
  readonly created_at: string | null;
}

/** Body accepted by POST /byok/keys. The secret is write-only. */
export interface AddProviderKeyBody {
  readonly provider_key: string;
  readonly secret: string;
  readonly label?: string;
  readonly priority?: number;
}

/** A provider the vault can hold keys for, surfaced as quick-pick chips. */
export interface KnownProvider {
  readonly key: string;
  readonly name: string;
  /** Short hint on where the key is used. */
  readonly hint: string;
}

/**
 * Curated list of routing providers the BYOK vault integrates with. Sourced
 * from the API routing adapters (`apps/api/app/domains/routing/providers`).
 * Callers may still store a key for any provider slug via free text.
 */
export const KNOWN_PROVIDERS: readonly KnownProvider[] = [
  { key: "openrouter", name: "OpenRouter", hint: "LLM prompts & scripts" },
  { key: "elevenlabs", name: "ElevenLabs", hint: "Voice & TTS" },
  { key: "heygen", name: "HeyGen", hint: "Avatars & lipsync" },
  { key: "kling", name: "Kling", hint: "Video generation" },
  { key: "runway", name: "Runway", hint: "Video generation" },
  { key: "luma", name: "Luma", hint: "Video generation" },
  { key: "veo", name: "Veo", hint: "Video generation" },
  { key: "minimax", name: "MiniMax", hint: "Video generation" },
  { key: "suno", name: "Suno", hint: "Music generation" },
  { key: "wan", name: "Wan", hint: "Video generation" },
];

/** Resolve the display name for a provider slug, falling back to the slug. */
export function providerName(providerKey: string): string {
  const match = KNOWN_PROVIDERS.find((p) => p.key === providerKey);
  return match ? match.name : providerKey;
}

/** List the caller's stored provider keys (never secrets). */
export function listProviderKeys(
  options?: RequestOptions,
): Promise<{ keys: ProviderKey[] }> {
  return request<{ keys: ProviderKey[] }>("/byok/keys", { options });
}

/**
 * Store one of the caller's own provider keys, encrypted at rest. The response
 * carries only the safe view (masked prefix + metadata), never the secret.
 */
export function addProviderKey(
  body: AddProviderKeyBody,
  options?: RequestOptions,
): Promise<ProviderKey> {
  return request<ProviderKey>("/byok/keys", { method: "POST", body, options });
}

/**
 * Revoke one owned key immediately. Irreversible; the routing layer stops using
 * it at once and falls back to the platform key. Returns the revoked view.
 */
export function deleteProviderKey(
  keyId: string,
  options?: RequestOptions,
): Promise<ProviderKey> {
  return request<ProviderKey>(`/byok/keys/${encodeURIComponent(keyId)}`, {
    method: "DELETE",
    options,
  });
}
