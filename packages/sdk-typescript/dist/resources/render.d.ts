import type { Requester } from "../transport.js";
/** A wallet-metered async-GPU render job (unified envelope). */
export interface RenderJob {
    id: string;
    backend: string;
    state: "IN_QUEUE" | "IN_PROGRESS" | "COMPLETED" | "FAILED" | "CANCELLED";
    progress: number;
    provider_ref: string;
    output_refs: string[];
    cost_micros: number;
    error: string;
}
export interface StartRenderRequest {
    backend: string;
    spec: Record<string, unknown>;
    max_cost_micros: number;
    workflow_version?: string;
    workspace_id?: string | null;
}
/** Async-GPU render — start, poll status, advance (settle/refund on terminal). */
export declare class RenderResource {
    private readonly request;
    constructor(request: Requester);
    start(body: StartRenderRequest): Promise<RenderJob>;
    get(jobId: string): Promise<RenderJob>;
    advance(jobId: string): Promise<RenderJob>;
}
