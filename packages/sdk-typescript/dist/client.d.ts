/**
 * ReelForge TypeScript SDK.
 *
 * A tiny, dependency-free, `fetch`-based client for the public ReelForge
 * `/api/v1` surface (jobs, presigned uploads, webhook subscriptions, developer
 * portal, workspace usage, and the current-user profile).
 *
 * Every ReelForge response uses the envelope `{ status, data?, message? }`; the
 * client unwraps and returns the `data` payload directly, and raises
 * {@link ReelForgeApiError} for any non-2xx status.
 *
 * @example
 * ```ts
 * import { ReelForgeClient } from "@reelforge/sdk";
 *
 * const rf = new ReelForgeClient({ apiKey: process.env.REELFORGE_API_KEY! });
 * const me = await rf.me();
 * const job = await rf.createJob({ params: { script: "hello world" } });
 * const status = await rf.getJob(job.job_id);
 * ```
 */
import { BrollResource, type GenerateBrollOptions } from "./resources/broll.js";
import { JobsResource, type CreateEditorExportOptions, type CreateJobOptions } from "./resources/jobs.js";
import { UploadsResource } from "./resources/uploads.js";
import { WebhooksResource } from "./resources/webhooks.js";
import { WorkspacesResource } from "./resources/workspaces.js";
import { TemplatesResource } from "./resources/templates.js";
import { RenderResource } from "./resources/render.js";
import { ClipmarketResource } from "./resources/clipmarket.js";
import { MediaResource } from "./resources/media.js";
import type { BrollGenerateInput, BrollGenerationSnapshot, EditorExportRequest } from "@reelforge/api-contract";
/** Supported webhook event types (mirrors the server catalog). */
export declare const WEBHOOK_EVENT_TYPES: readonly ["job.completed", "publish.succeeded", "publish.failed", "performance.ingested"];
export type WebhookEventType = (typeof WEBHOOK_EVENT_TYPES)[number];
/** The MPT-style response envelope every endpoint returns. */
export interface ResponseEnvelope<T> {
    status: number;
    data?: T;
    message?: string;
}
/** The authenticated caller's profile (`GET /me`). */
export interface Me {
    user_id: string;
    email: string;
    credits: number;
    jobs_count: number;
    [key: string]: unknown;
}
/** Request body for `POST /jobs`. `params` carries a ReelForgeParams mapping. */
export interface JobCreateRequest {
    params?: Record<string, unknown>;
    avatar_id?: string;
    voice_id?: string;
    caption_style?: string;
    music_id?: string;
    webhook_url?: string;
    webhook_secret?: string;
    music_prompt?: string;
    bgm_provider?: string;
    variants?: number;
    tos_disclosure?: boolean;
    [key: string]: unknown;
}
/** A job status record (`POST /jobs`, `GET /jobs/{id}`). */
export interface Job {
    job_id: string;
    state: string;
    progress: number;
    stages?: Record<string, unknown>;
    failed_stage?: string;
    error?: string;
    result_url?: string;
    /** Present when a batch (`variants > 1`) was created. */
    job_ids?: string[];
    batch_id?: string;
    [key: string]: unknown;
}
/** The `GET /jobs` list payload. */
export interface JobList {
    jobs: Job[];
}
/** A single job in a batch review (`GET /batches/{id}`). */
export interface BatchJob {
    job_id: string;
    state: string;
    progress: number;
    result_url?: string;
    poster_key?: string;
}
/** The `GET /batches/{id}` payload. */
export interface Batch {
    batch_id: string;
    jobs: BatchJob[];
}
/** Overrides accepted by `POST /jobs/{id}/rerun`. */
export interface RerunOverrides {
    voice_id?: string;
    avatar_id?: string;
    layout?: string;
    caption_style?: string;
    music_id?: string;
    language?: string;
}
/** Request body for `POST /jobs/{id}/rerun`. */
export interface RerunRequest {
    overrides?: RerunOverrides;
}
/** Request body for `POST /uploads/presign`. */
export interface PresignRequest {
    filename: string;
    content_type: string;
    size: number;
}
/** Presigned upload payload (`POST /uploads/presign`). */
export interface Presign {
    upload_url: string;
    get_url: string;
    key: string;
    headers: Record<string, string>;
}
export interface RegisterUploadRequest {
    key: string;
    kind?: string;
}
export interface RegisteredUpload {
    asset_id: string;
    key: string;
    kind: string;
}
/** Request body for `POST /me/workspaces/{id}/webhooks`. */
export interface WebhookSubscribeRequest {
    url: string;
    event_types: (WebhookEventType | string)[];
}
/** A webhook subscription (secret-free — as returned by list). */
export interface WebhookSubscription {
    id: string;
    workspace_id: string;
    url: string;
    event_types: string[];
    enabled: boolean;
    created_at: string | null;
    updated_at: string | null;
}
/** A created webhook subscription — carries the one-time signing `secret`. */
export interface CreatedWebhookSubscription extends WebhookSubscription {
    /** The HMAC signing secret. Returned exactly once, on create. Store it now. */
    secret: string;
}
/** A webhook delivery record (metadata only; the signed body is never returned). */
export interface WebhookDelivery {
    id: string;
    subscription_id: string;
    event_type: string;
    event_id: string;
    status: string;
    attempts: number;
    last_attempt_at: string | null;
    response_code: number | null;
    created_at: string | null;
}
/** The developer-portal API-key footprint. */
export interface DeveloperApiKeysSummary {
    total: number;
    active: number;
    period_ym: string;
    requests_this_month: number;
}
/** The developer-portal webhook footprint. */
export interface DeveloperWebhooksSummary {
    total: number;
    active: number;
    event_types: string[];
}
/** The `GET /me/developer` payload. */
export interface DeveloperPortal {
    api_keys: DeveloperApiKeysSummary;
    webhooks: DeveloperWebhooksSummary;
    workspaces: number;
    webhook_event_types: string[];
    api_base_url: string;
    openapi_url: string;
    docs_url: string;
    api_version: string;
}
/** A per-metric overage line in a usage report. */
export interface UsageOverage {
    metric: string;
    used: number;
    limit: number | null;
    overage: number;
}
/** The `GET /me/workspaces/{id}/usage` payload. */
export interface Usage {
    workspace_id: string;
    period: string;
    usage: Record<string, number>;
    overage: UsageOverage[];
}
/** The `GET /me/workspaces/{id}/entitlements` payload. */
export interface Entitlements {
    workspace_id: string;
    plan_key: string;
    entitlements: Record<string, unknown>;
}
/** Options for constructing a {@link ReelForgeClient}. */
export interface ReelForgeClientOptions {
    /** Per-user API key sent as the `x-api-key` header. */
    apiKey: string;
    /** API origin. Defaults to `https://api.menivor.com`. No trailing slash needed. */
    baseUrl?: string;
    /** Optional custom `fetch` (defaults to the global `fetch`). */
    fetch?: typeof fetch;
    /** Optional request timeout in milliseconds. */
    timeoutMs?: number;
}
/** Raised for any non-2xx API response. Carries the HTTP status + server message. */
export declare class ReelForgeApiError extends Error {
    readonly status: number;
    readonly body: unknown;
    readonly correlationId?: string;
    constructor(status: number, message: string, body: unknown, correlationId?: string);
}
export declare class ReelForgeClient {
    private readonly apiKey;
    private readonly baseUrl;
    private readonly fetchImpl;
    private readonly timeoutMs?;
    readonly jobs: JobsResource;
    readonly broll: BrollResource;
    readonly uploads: UploadsResource;
    readonly webhooks: WebhooksResource;
    readonly workspaces: WorkspacesResource;
    readonly templates: TemplatesResource;
    readonly render: RenderResource;
    readonly clipmarket: ClipmarketResource;
    readonly media: MediaResource;
    constructor(options: ReelForgeClientOptions);
    /** `GET /me` — the authenticated caller's profile + credit balance. */
    me(): Promise<Me>;
    /** `POST /jobs` — create (and enqueue) one or more avatar jobs. */
    createJob(body: JobCreateRequest, options?: CreateJobOptions): Promise<Job>;
    /** `GET /jobs/{id}` — fetch a single job's status. */
    getJob(jobId: string): Promise<Job>;
    /** `GET /jobs` — list the caller's jobs (newest first). */
    listJobs(params?: {
        limit?: number;
        offset?: number;
    }): Promise<JobList>;
    /** `POST /jobs/{id}/retry` — re-enqueue a failed job from its failed stage. */
    retryJob(jobId: string): Promise<Job>;
    /** `POST /jobs/{id}/rerun` — clone a job's params with tweaks into a new job. */
    rerunJob(jobId: string, body?: RerunRequest): Promise<Job>;
    /** `GET /batches/{id}` — review every variant job of a batch. */
    getBatch(batchId: string): Promise<Batch>;
    /** `POST /jobs/{id}/exports` — enqueue an exact non-destructive reel cut. */
    exportEditorCut(jobId: string, body: EditorExportRequest, options?: CreateEditorExportOptions): Promise<Job>;
    /** Canonical `POST /generation/broll/generate`. */
    generateBroll(body: BrollGenerateInput, options?: GenerateBrollOptions): Promise<BrollGenerationSnapshot>;
    /** Canonical B-roll generation status lookup. */
    getBrollGeneration(generationId: string): Promise<BrollGenerationSnapshot>;
    /** List the caller's durable B-roll generation history. */
    listBrollGenerations(): Promise<BrollGenerationSnapshot[]>;
    /** `POST /uploads/presign` — presigned PUT + GET URLs for a client-side upload. */
    presignUpload(body: PresignRequest): Promise<Presign>;
    /** Register a completed direct upload as a caller-owned media asset. */
    registerUpload(body: RegisterUploadRequest): Promise<RegisteredUpload>;
    /**
     * `POST /me/workspaces/{id}/webhooks` — create a subscription.
     * The signing `secret` is returned exactly once, here. Store it now.
     */
    createWebhookSubscription(workspaceId: string, body: WebhookSubscribeRequest): Promise<CreatedWebhookSubscription>;
    /** `GET /me/workspaces/{id}/webhooks` — list subscriptions (secret-free). */
    listWebhookSubscriptions(workspaceId: string): Promise<WebhookSubscription[]>;
    /** `DELETE /me/workspaces/{id}/webhooks/{subId}` — revoke a subscription. */
    deleteWebhookSubscription(workspaceId: string, subscriptionId: string): Promise<{
        id: string;
        revoked: boolean;
    }>;
    /** `POST /me/workspaces/{id}/webhooks/{subId}/test` — send a signed test event. */
    testWebhookSubscription(workspaceId: string, subscriptionId: string): Promise<WebhookDelivery>;
    /** `GET /me/workspaces/{id}/webhooks/{subId}/deliveries` — recent deliveries. */
    listWebhookDeliveries(workspaceId: string, subscriptionId: string, limit?: number): Promise<WebhookDelivery[]>;
    /** `GET /me/developer` — the caller-scoped developer portal summary. */
    getDeveloperPortal(): Promise<DeveloperPortal>;
    /** `GET /me/workspaces/{id}/usage` — metered usage + overage for a period. */
    getUsage(workspaceId: string, period?: string): Promise<Usage>;
    /** `GET /me/workspaces/{id}/entitlements` — the workspace's active-plan bundle. */
    getEntitlements(workspaceId: string): Promise<Entitlements>;
    private buildUrl;
    private request;
}
export { ReelForgeClient as MenivorClient, ReelForgeApiError as MenivorApiError };
export type MenivorClientOptions = ReelForgeClientOptions;
export default ReelForgeClient;
