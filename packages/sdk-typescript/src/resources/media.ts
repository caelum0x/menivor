import type { Requester } from "../transport.js";

/**
 * Unified media gateway — OpenRouter-style `/images` + `/videos`.
 *
 * One API key + one wallet balance → any image or video model. Images return
 * synchronously; videos submit a job you poll to a terminal status. Credits and
 * usage mirror OpenRouter's cost-visibility surface.
 */

export type Modality = "image" | "video" | "audio";

/** A routable media model in the unified catalog. */
export interface MediaModel {
  id: string;
  modality: Modality;
  provider: string;
  price_micros: number;
  unit: string; // "image" | "second"
  max_seconds: number;
  description: string;
}

/** Synchronous image result (`POST /images`). */
export interface ImageResult {
  model: string;
  url: string;
  cost_micros: number;
}

/** Async video job (`POST /videos`, `GET /videos/{id}`). */
export interface VideoJob {
  id: string;
  model: string;
  status: string; // in_progress | completed | failed
  url: string;
  cost_micros: number;
  error: string;
}

/** Spendable credits + lifetime gateway spend (`GET /credits`). */
export interface Credits {
  available_micros: number;
  reserved_micros: number;
  total_gateway_spend_micros: number;
  currency: string;
}

/** Spend + counts grouped by model (`GET /media/usage`). */
export interface UsageRow {
  model: string;
  modality: Modality;
  jobs: number;
  spend_micros: number;
  seconds: number;
}

export interface CreateImageRequest {
  model: string;
  prompt: string;
}

export interface CreateVideoRequest {
  model: string;
  prompt?: string;
  duration?: number;
  aspect_ratio?: string;
  image_url?: string;
}

export interface CreateAudioRequest {
  model: string;
  prompt: string;
  instrumental?: boolean;
}

export interface WaitForVideoOptions {
  /** Poll interval in ms (default 3000). */
  intervalMs?: number;
  /** Max attempts before giving up (default 200). */
  maxAttempts?: number;
  /** Injectable sleep for tests. */
  sleep?: (ms: number) => Promise<void>;
}

const TERMINAL = new Set(["completed", "failed"]);

/** Is a video job in a terminal state? */
export function isTerminalStatus(status: string): boolean {
  return TERMINAL.has(status);
}

/** Unified image + video generation over one key + one balance. */
export class MediaResource {
  constructor(private readonly request: Requester) {}

  /** List image + video models (optionally filtered by modality). */
  listModels(modality?: Modality): Promise<{ models: MediaModel[] }> {
    return this.request("GET", "/media/models", {
      query: modality === undefined ? {} : { modality },
    });
  }

  /** Generate an image synchronously → `{ url }`. */
  createImage(body: CreateImageRequest): Promise<ImageResult> {
    return this.request("POST", "/media/images", { body });
  }

  /** Submit a video job (poll it with {@link getVideo} or {@link waitForVideo}). */
  createVideo(body: CreateVideoRequest): Promise<VideoJob> {
    return this.request("POST", "/media/videos", { body });
  }

  /** Poll a video job once. */
  getVideo(jobId: string): Promise<VideoJob> {
    return this.request("GET", `/media/videos/${encodeURIComponent(jobId)}`);
  }

  /** Submit a music/audio job (poll it with {@link getAudio}). */
  createAudio(body: CreateAudioRequest): Promise<VideoJob> {
    return this.request("POST", "/media/audio", { body });
  }

  /** Poll an audio job once. */
  getAudio(jobId: string): Promise<VideoJob> {
    return this.request("GET", `/media/audio/${encodeURIComponent(jobId)}`);
  }

  /** Submit a video and poll until it reaches a terminal status. */
  async waitForVideo(
    body: CreateVideoRequest,
    options: WaitForVideoOptions = {},
  ): Promise<VideoJob> {
    const intervalMs = options.intervalMs ?? 3000;
    const maxAttempts = options.maxAttempts ?? 200;
    const sleep =
      options.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
    let job = await this.createVideo(body);
    let attempts = 0;
    while (!isTerminalStatus(job.status)) {
      if (++attempts > maxAttempts) {
        throw new Error(`waitForVideo: job ${job.id} did not finish in ${maxAttempts} polls`);
      }
      await sleep(intervalMs);
      job = await this.getVideo(job.id);
    }
    return job;
  }

  /** Spendable credits + lifetime gateway spend. */
  credits(): Promise<Credits> {
    return this.request("GET", "/media/credits");
  }

  /** Gateway spend + job counts grouped by model. */
  usage(limit?: number): Promise<{ usage: UsageRow[] }> {
    return this.request("GET", "/media/usage", {
      query: limit === undefined ? {} : { limit },
    });
  }

  /** Per-generation cost/status detail (OpenRouter `/generation?id=`). */
  generation(jobId: string): Promise<VideoJob> {
    return this.request("GET", `/media/generation/${encodeURIComponent(jobId)}`);
  }
}

/** Integer-microdollar → "$0.084" style display (1 USD = 1_000_000 micros). */
export function formatUsdMicros(micros: number): string {
  const usd = (micros || 0) / 1_000_000;
  const digits = usd !== 0 && Math.abs(usd) < 0.1 ? 3 : 2;
  return `$${usd.toFixed(digits)}`;
}
