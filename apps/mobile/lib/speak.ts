/**
 * Typed client for Speak Studio — Expo. Turn an OWNED reference image + an OWNED
 * narration audio clip into a lipsync "talking video". Mirrors the B-roll studio
 * flow: `POST /generation/speak/generate` enqueues an async
 * `Job(kind="speak_lipsync")` the caller polls to completion via
 * `GET /generation/speak/generations/{id}`; `GET /generation/speak/providers`
 * lists the bounded, commercial-safe lipsync providers.
 *
 * Every call flows through the shared `x-api-key` transport (no secrets here).
 * Both keys must be uploads the caller owns (minted with `presignAndUpload`);
 * the backend rejects a foreign key with 403 before any billed work.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";
import type { JobStateValue } from "@/lib/types";

/**
 * Request body for `POST /generation/speak/generate`. `image_key` and
 * `audio_key` are R2 keys the caller owns; `provider` is an optional reviewed
 * lipsync selector (empty resolves a commercial-safe default server-side).
 */
export interface SpeakGenerateRequest {
  image_key: string;
  audio_key: string;
  provider?: string;
}

/**
 * One speak generation's lifecycle snapshot (the underlying
 * `Job(kind="speak_lipsync")`). `talking_video_key` / `result_url` are empty
 * until `state` reaches {@link JobState.Complete}.
 */
export interface SpeakGeneration {
  generation_id: string;
  state: JobStateValue;
  progress: number;
  talking_video_key: string;
  result_url: string;
  provider: string;
  license_class: string;
  error: string;
  retry_eligible: boolean;
  correlation_id?: string;
}

/** One selectable lipsync provider + its capability and license class. */
export interface SpeakProvider {
  provider: string;
  capability: string;
  metering_unit: string;
  license_class: string;
  latency_band: string;
  available: boolean;
}

/** The bounded speak engine capability the UI may offer right now. */
export interface SpeakProviders {
  modes: string[];
  runtime: string;
  providers: SpeakProvider[];
}

/**
 * POST /generation/speak/generate — start one async lipsync render and return
 * its initial snapshot (poll {@link getSpeakGeneration} with `generation_id`).
 *
 * Spends credits: the debit is committed before the render is enqueued, so pass
 * `options.idempotencyKey` to keep an ambiguous transport retry from creating a
 * second billed generation. Surfaces 400 (missing/foreign key), 402
 * (insufficient credits), and 503 (no provider available) as an `ApiError`.
 */
export function generateSpeak(
  body: SpeakGenerateRequest,
  options?: RequestOptions,
): Promise<SpeakGeneration> {
  return request<SpeakGeneration>("/generation/speak/generate", {
    method: "POST",
    body,
    options,
  });
}

/**
 * GET /generation/speak/generations/{id} — poll one owned generation's
 * state/progress (and `talking_video_key` + `result_url` once complete).
 * Owner-scoped: an unknown/foreign/non-speak id is a clean 404.
 */
export function getSpeakGeneration(
  generationId: string,
  options?: RequestOptions,
): Promise<SpeakGeneration> {
  return request<SpeakGeneration>(
    `/generation/speak/generations/${encodeURIComponent(generationId)}`,
    { options },
  );
}

/**
 * GET /generation/speak/providers — the bounded lipsync selectors + license
 * classes, each flagged `available` when it can actually route now. The shape is
 * normalized defensively so a partial payload degrades to empty lists rather
 * than throwing, and non-object provider rows are dropped.
 */
export async function listSpeakProviders(
  options?: RequestOptions,
): Promise<SpeakProviders> {
  const data = await request<Partial<SpeakProviders>>(
    "/generation/speak/providers",
    { options },
  );
  const providers = Array.isArray(data?.providers)
    ? data.providers.filter(
        (p): p is SpeakProvider =>
          !!p && typeof p === "object" && typeof p.provider === "string",
      )
    : [];
  return {
    modes: Array.isArray(data?.modes)
      ? data.modes.filter((m): m is string => typeof m === "string")
      : [],
    runtime: typeof data?.runtime === "string" ? data.runtime : "",
    providers,
  };
}
