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
export class RenderResource {
  constructor(private readonly request: Requester) {}

  start(body: StartRenderRequest): Promise<RenderJob> {
    return this.request("POST", "/render/jobs", { body });
  }

  get(jobId: string): Promise<RenderJob> {
    return this.request("GET", `/render/jobs/${encodeURIComponent(jobId)}`);
  }

  advance(jobId: string): Promise<RenderJob> {
    return this.request("POST", `/render/jobs/${encodeURIComponent(jobId)}/advance`);
  }
}
