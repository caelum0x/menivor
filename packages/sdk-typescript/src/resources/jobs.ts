import type {
  Batch,
  Job,
  JobCreateRequest,
  JobList,
  RerunRequest,
} from "../client.js";
import type { EditorExportRequest } from "@reelforge/api-contract";
import type { Requester } from "../transport.js";

export interface CreateJobOptions {
  /** Stable key to reuse when a create response is ambiguous. */
  idempotencyKey?: string;
}

export type CreateEditorExportOptions = CreateJobOptions;

export class JobsResource {
  constructor(private readonly request: Requester) {}

  create(body: JobCreateRequest, options: CreateJobOptions = {}): Promise<Job> {
    return this.request("POST", "/jobs", {
      body,
      headers: options.idempotencyKey
        ? { "Idempotency-Key": options.idempotencyKey }
        : undefined,
    });
  }

  get(jobId: string): Promise<Job> {
    return this.request("GET", `/jobs/${encodeURIComponent(jobId)}`);
  }

  list(params: { limit?: number; offset?: number } = {}): Promise<JobList> {
    return this.request("GET", "/jobs", { query: params });
  }

  retry(jobId: string): Promise<Job> {
    return this.request("POST", `/jobs/${encodeURIComponent(jobId)}/retry`);
  }

  rerun(jobId: string, body: RerunRequest = {}): Promise<Job> {
    return this.request("POST", `/jobs/${encodeURIComponent(jobId)}/rerun`, {
      body,
    });
  }

  getBatch(batchId: string): Promise<Batch> {
    return this.request("GET", `/batches/${encodeURIComponent(batchId)}`);
  }

  exportCut(
    jobId: string,
    body: EditorExportRequest,
    options: CreateEditorExportOptions = {},
  ): Promise<Job> {
    return this.request("POST", `/jobs/${encodeURIComponent(jobId)}/exports`, {
      body,
      headers: options.idempotencyKey
        ? { "Idempotency-Key": options.idempotencyKey }
        : undefined,
    });
  }
}
