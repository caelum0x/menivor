import type { Batch, Job, JobCreateRequest, JobList, RerunRequest } from "../client.js";
import type { EditorExportRequest } from "@reelforge/api-contract";
import type { Requester } from "../transport.js";
export interface CreateJobOptions {
    /** Stable key to reuse when a create response is ambiguous. */
    idempotencyKey?: string;
}
export type CreateEditorExportOptions = CreateJobOptions;
export declare class JobsResource {
    private readonly request;
    constructor(request: Requester);
    create(body: JobCreateRequest, options?: CreateJobOptions): Promise<Job>;
    get(jobId: string): Promise<Job>;
    list(params?: {
        limit?: number;
        offset?: number;
    }): Promise<JobList>;
    retry(jobId: string): Promise<Job>;
    rerun(jobId: string, body?: RerunRequest): Promise<Job>;
    getBatch(batchId: string): Promise<Batch>;
    exportCut(jobId: string, body: EditorExportRequest, options?: CreateEditorExportOptions): Promise<Job>;
}
