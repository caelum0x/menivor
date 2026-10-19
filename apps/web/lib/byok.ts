/**
 * Typed client for BYOK (bring your own provider key) - `POST/GET/DELETE
 * /byok/keys` in apps/api `domains/byok/router.py`.
 *
 * The secret is write-only: it is sent once on create, encrypted at rest by
 * the API, and never returned. Lists carry only a masked prefix hint.
 *
 * Billing: when a stage routes through a stored key, the provider bills the
 * customer directly and Menivor charges a disclosed routing fee instead of the
 * provider price (apps/api `domains/spend/policy.py`). The API does not yet
 * expose the configured rate, so the defaults below are what the policy module
 * ships with; the exact fee for every stage is recorded on its usage row and
 * appears on /spend.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

/** The policy module's default routing fee: 10% of the equivalent provider price. */
export const BYOK_DEFAULT_FEE_BPS = 1000;
/** ...with a $0.001 minimum per BYOK stage. */
export const BYOK_DEFAULT_MIN_FEE_MICROS = 1000;

/** Providers the routing catalog can send work to with a customer key. */
export const BYOK_PROVIDERS: ReadonlyArray<{
  readonly key: string;
  readonly name: string;
  readonly kind: string;
  readonly keyUrl: string;
}> = [
  { key: "elevenlabs", name: "ElevenLabs", kind: "Voice", keyUrl: "https://elevenlabs.io/app/settings/api-keys" },
  { key: "kling", name: "Kling", kind: "Video", keyUrl: "https://app.klingai.com/global/dev" },
  { key: "runway", name: "Runway", kind: "Video", keyUrl: "https://dev.runwayml.com/" },
  { key: "luma", name: "Luma", kind: "Video", keyUrl: "https://lumalabs.ai/api" },
  { key: "minimax", name: "MiniMax", kind: "Video and voice", keyUrl: "https://www.minimax.io/platform" },
  { key: "ltx_fal", name: "fal.ai (LTX-Video)", kind: "Video", keyUrl: "https://fal.ai/dashboard/keys" },
  { key: "heygen", name: "HeyGen", kind: "Avatar", keyUrl: "https://app.heygen.com/settings?nav=API" },
  { key: "openai", name: "OpenAI", kind: "Script", keyUrl: "https://platform.openai.com/api-keys" },
  { key: "openrouter", name: "OpenRouter", kind: "Script", keyUrl: "https://openrouter.ai/settings/keys" },
  { key: "cartesia", name: "Cartesia", kind: "Voice", keyUrl: "https://play.cartesia.ai/keys" },
];

export function providerName(key: string): string {
  return BYOK_PROVIDERS.find((provider) => provider.key === key)?.name ?? key;
}

export interface ProviderKey {
  readonly id: string;
  readonly provider_key: string;
  readonly label: string;
  /** Masked hint such as `sk-…AB`; never the secret. */
  readonly key_prefix: string;
  readonly scope: string;
  readonly priority: number;
  readonly status: string;
  readonly use_count: number;
  readonly last_used_at: string | null;
  readonly created_at: string | null;
}

export interface AddProviderKeyInput {
  readonly provider_key: string;
  readonly secret: string;
  readonly label?: string;
  readonly priority?: number;
}

/** Client-side check before the secret leaves the browser. */
export function validateProviderKeyInput(input: AddProviderKeyInput): string | null {
  if (!BYOK_PROVIDERS.some((provider) => provider.key === input.provider_key)) {
    return "Choose a provider.";
  }
  const secret = input.secret.trim();
  if (secret.length < 8) return "Paste the full API key from the provider.";
  if (secret.length > 4096) return "That key is too long.";
  if (/\s/.test(secret)) return "API keys do not contain spaces.";
  if ((input.label ?? "").length > 80) return "Keep the label under 80 characters.";
  return null;
}

/** Routing fee for a stage whose provider price would be `providerMicros`. */
export function byokFeeMicros(
  providerMicros: number,
  feeBps = BYOK_DEFAULT_FEE_BPS,
  minMicros = BYOK_DEFAULT_MIN_FEE_MICROS,
): number {
  const base = Math.max(0, Math.round(providerMicros));
  if (feeBps <= 0 || base <= 0) return 0;
  return Math.max(minMicros, Math.floor((base * feeBps + 5000) / 10000));
}

/** GET /byok/keys - the caller's keys, secrets never included. */
export async function listProviderKeys(options?: RequestOptions): Promise<ProviderKey[]> {
  const data = await request<{ keys?: ProviderKey[] }>("/byok/keys", { options });
  return data.keys ?? [];
}

/** POST /byok/keys - store one key, encrypted at rest. */
export function addProviderKey(
  input: AddProviderKeyInput,
  options?: RequestOptions,
): Promise<ProviderKey> {
  return request<ProviderKey>("/byok/keys", {
    method: "POST",
    body: {
      provider_key: input.provider_key,
      secret: input.secret.trim(),
      label: (input.label ?? "").trim(),
      priority: input.priority ?? 0,
    },
    options,
  });
}

/** DELETE /byok/keys/{id} - revoke immediately. */
export function revokeProviderKey(id: string, options?: RequestOptions): Promise<ProviderKey> {
  return request<ProviderKey>(`/byok/keys/${encodeURIComponent(id)}`, {
    method: "DELETE",
    options,
  });
}
