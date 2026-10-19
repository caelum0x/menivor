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
    unit: string;
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
    status: string;
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
/** Is a video job in a terminal state? */
export declare function isTerminalStatus(status: string): boolean;
/** Unified image + video generation over one key + one balance. */
export declare class MediaResource {
    private readonly request;
    constructor(request: Requester);
    /** List image + video models (optionally filtered by modality). */
    listModels(modality?: Modality): Promise<{
        models: MediaModel[];
    }>;
    /** Generate an image synchronously → `{ url }`. */
    createImage(body: CreateImageRequest): Promise<ImageResult>;
    /** Submit a video job (poll it with {@link getVideo} or {@link waitForVideo}). */
    createVideo(body: CreateVideoRequest): Promise<VideoJob>;
    /** Poll a video job once. */
    getVideo(jobId: string): Promise<VideoJob>;
    /** Submit a music/audio job (poll it with {@link getAudio}). */
    createAudio(body: CreateAudioRequest): Promise<VideoJob>;
    /** Poll an audio job once. */
    getAudio(jobId: string): Promise<VideoJob>;
    /** Submit a video and poll until it reaches a terminal status. */
    waitForVideo(body: CreateVideoRequest, options?: WaitForVideoOptions): Promise<VideoJob>;
    /** Spendable credits + lifetime gateway spend. */
    credits(): Promise<Credits>;
    /** Gateway spend + job counts grouped by model. */
    usage(limit?: number): Promise<{
        usage: UsageRow[];
    }>;
    /** Per-generation cost/status detail (OpenRouter `/generation?id=`). */
    generation(jobId: string): Promise<VideoJob>;
}
/** Integer-microdollar → "$0.084" style display (1 USD = 1_000_000 micros). */
export declare function formatUsdMicros(micros: number): string;
