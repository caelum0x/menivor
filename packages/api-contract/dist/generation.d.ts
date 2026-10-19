import type { JobStateValue } from "./job-state.js";
export type BrollGenerationMode = "t2v" | "i2v";
export type GenerationAspect = "9:16" | "16:9" | "1:1";
/** Stable client input for canonical POST /generation/broll/generate. */
export interface BrollGenerateInput {
    prompt: string;
    mode?: BrollGenerationMode;
    image_key?: string;
    aspect?: GenerationAspect;
    workflow_id?: string;
    seed?: number;
}
/** Shared lifecycle snapshot for canonical AI B-roll generation resources. */
export interface BrollGenerationSnapshot {
    generation_id: string;
    state: JobStateValue;
    progress: number;
    broll_key: string;
    result_url?: string;
    duration: number;
    error?: string;
    retry_eligible?: boolean;
    correlation_id?: string;
}
/** Input for POST /uploads/presign. */
export interface PresignUploadInput {
    filename: string;
    content_type: string;
    size: number;
}
/** Signed direct-upload instructions returned by ReelForge. */
export interface PresignUploadResult {
    upload_url: string;
    get_url: string;
    key: string;
    headers: Record<string, string>;
}
