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
import { BrollResource } from "./resources/broll.js";
import { JobsResource, } from "./resources/jobs.js";
import { UploadsResource } from "./resources/uploads.js";
import { WebhooksResource } from "./resources/webhooks.js";
import { WorkspacesResource } from "./resources/workspaces.js";
import { TemplatesResource } from "./resources/templates.js";
import { RenderResource } from "./resources/render.js";
import { ClipmarketResource } from "./resources/clipmarket.js";
import { MediaResource } from "./resources/media.js";
// --------------------------------------------------------------------------- //
// Types
// --------------------------------------------------------------------------- //
/** Supported webhook event types (mirrors the server catalog). */
export const WEBHOOK_EVENT_TYPES = [
    "job.completed",
    "publish.succeeded",
    "publish.failed",
    "performance.ingested",
];
// --------------------------------------------------------------------------- //
// Errors
// --------------------------------------------------------------------------- //
/** Raised for any non-2xx API response. Carries the HTTP status + server message. */
export class ReelForgeApiError extends Error {
    status;
    body;
    correlationId;
    constructor(status, message, body, correlationId) {
        super(correlationId && !message.includes(correlationId)
            ? `${message} (correlation ${correlationId})`
            : message);
        this.name = "ReelForgeApiError";
        this.status = status;
        this.body = body;
        this.correlationId = correlationId || undefined;
    }
}
// --------------------------------------------------------------------------- //
// Client
// --------------------------------------------------------------------------- //
const DEFAULT_BASE_URL = "https://api.menivor.com";
export class ReelForgeClient {
    apiKey;
    baseUrl;
    fetchImpl;
    timeoutMs;
    jobs;
    broll;
    uploads;
    webhooks;
    workspaces;
    templates;
    render;
    clipmarket;
    media;
    constructor(options) {
        if (!options || !options.apiKey) {
            throw new Error("ReelForgeClient: `apiKey` is required");
        }
        this.apiKey = options.apiKey;
        this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
        const globalFetch = options.fetch ??
            (typeof fetch !== "undefined" ? fetch : undefined);
        if (!globalFetch) {
            throw new Error("ReelForgeClient: no global `fetch` found; pass `options.fetch`");
        }
        this.fetchImpl = globalFetch;
        this.timeoutMs = options.timeoutMs;
        const requester = (method, path, requestOptions = {}) => this.request(method, path, requestOptions);
        this.jobs = new JobsResource(requester);
        this.broll = new BrollResource(requester);
        this.uploads = new UploadsResource(requester);
        this.webhooks = new WebhooksResource(requester);
        this.workspaces = new WorkspacesResource(requester);
        this.templates = new TemplatesResource(requester);
        this.render = new RenderResource(requester);
        this.clipmarket = new ClipmarketResource(requester);
        this.media = new MediaResource(requester);
    }
    // ----------------------------------------------------------------------- //
    // Current user
    // ----------------------------------------------------------------------- //
    /** `GET /me` — the authenticated caller's profile + credit balance. */
    me() {
        return this.request("GET", "/me");
    }
    // ----------------------------------------------------------------------- //
    // Jobs
    // ----------------------------------------------------------------------- //
    /** `POST /jobs` — create (and enqueue) one or more avatar jobs. */
    createJob(body, options) {
        return this.jobs.create(body, options);
    }
    /** `GET /jobs/{id}` — fetch a single job's status. */
    getJob(jobId) {
        return this.jobs.get(jobId);
    }
    /** `GET /jobs` — list the caller's jobs (newest first). */
    listJobs(params = {}) {
        return this.jobs.list(params);
    }
    /** `POST /jobs/{id}/retry` — re-enqueue a failed job from its failed stage. */
    retryJob(jobId) {
        return this.jobs.retry(jobId);
    }
    /** `POST /jobs/{id}/rerun` — clone a job's params with tweaks into a new job. */
    rerunJob(jobId, body = {}) {
        return this.jobs.rerun(jobId, body);
    }
    /** `GET /batches/{id}` — review every variant job of a batch. */
    getBatch(batchId) {
        return this.jobs.getBatch(batchId);
    }
    /** `POST /jobs/{id}/exports` — enqueue an exact non-destructive reel cut. */
    exportEditorCut(jobId, body, options) {
        return this.jobs.exportCut(jobId, body, options);
    }
    /** Canonical `POST /generation/broll/generate`. */
    generateBroll(body, options) {
        return this.broll.generate(body, options);
    }
    /** Canonical B-roll generation status lookup. */
    getBrollGeneration(generationId) {
        return this.broll.get(generationId);
    }
    /** List the caller's durable B-roll generation history. */
    listBrollGenerations() {
        return this.broll.list();
    }
    // ----------------------------------------------------------------------- //
    // Uploads
    // ----------------------------------------------------------------------- //
    /** `POST /uploads/presign` — presigned PUT + GET URLs for a client-side upload. */
    presignUpload(body) {
        return this.uploads.presign(body);
    }
    /** Register a completed direct upload as a caller-owned media asset. */
    registerUpload(body) {
        return this.uploads.register(body);
    }
    // ----------------------------------------------------------------------- //
    // Webhook subscriptions (workspace/tenant-scoped)
    // ----------------------------------------------------------------------- //
    /**
     * `POST /me/workspaces/{id}/webhooks` — create a subscription.
     * The signing `secret` is returned exactly once, here. Store it now.
     */
    createWebhookSubscription(workspaceId, body) {
        return this.webhooks.create(workspaceId, body);
    }
    /** `GET /me/workspaces/{id}/webhooks` — list subscriptions (secret-free). */
    listWebhookSubscriptions(workspaceId) {
        return this.webhooks.list(workspaceId);
    }
    /** `DELETE /me/workspaces/{id}/webhooks/{subId}` — revoke a subscription. */
    deleteWebhookSubscription(workspaceId, subscriptionId) {
        return this.webhooks.delete(workspaceId, subscriptionId);
    }
    /** `POST /me/workspaces/{id}/webhooks/{subId}/test` — send a signed test event. */
    testWebhookSubscription(workspaceId, subscriptionId) {
        return this.webhooks.test(workspaceId, subscriptionId);
    }
    /** `GET /me/workspaces/{id}/webhooks/{subId}/deliveries` — recent deliveries. */
    listWebhookDeliveries(workspaceId, subscriptionId, limit) {
        return this.webhooks.deliveries(workspaceId, subscriptionId, limit);
    }
    // ----------------------------------------------------------------------- //
    // Developer portal
    // ----------------------------------------------------------------------- //
    /** `GET /me/developer` — the caller-scoped developer portal summary. */
    getDeveloperPortal() {
        return this.request("GET", "/me/developer");
    }
    // ----------------------------------------------------------------------- //
    // Usage + entitlements (workspace/tenant-scoped)
    // ----------------------------------------------------------------------- //
    /** `GET /me/workspaces/{id}/usage` — metered usage + overage for a period. */
    getUsage(workspaceId, period) {
        return this.workspaces.usage(workspaceId, period);
    }
    /** `GET /me/workspaces/{id}/entitlements` — the workspace's active-plan bundle. */
    getEntitlements(workspaceId) {
        return this.workspaces.entitlements(workspaceId);
    }
    // ----------------------------------------------------------------------- //
    // Transport
    // ----------------------------------------------------------------------- //
    buildUrl(path, query) {
        let url = `${this.baseUrl}/api/v1${path}`;
        if (query) {
            const pairs = [];
            for (const [key, value] of Object.entries(query)) {
                if (value === undefined)
                    continue;
                pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
            }
            if (pairs.length > 0)
                url += `?${pairs.join("&")}`;
        }
        return url;
    }
    async request(method, path, opts = {}) {
        const url = this.buildUrl(path, opts.query);
        const headers = {
            "x-api-key": this.apiKey,
            accept: "application/json",
            ...opts.headers,
        };
        const init = { method, headers };
        if (opts.body !== undefined) {
            headers["content-type"] = "application/json";
            init.body = JSON.stringify(opts.body);
        }
        let controller;
        let timer;
        if (this.timeoutMs !== undefined && typeof AbortController !== "undefined") {
            controller = new AbortController();
            init.signal = controller.signal;
            timer = setTimeout(() => controller?.abort(), this.timeoutMs);
        }
        let response;
        try {
            response = await this.fetchImpl(url, init);
        }
        finally {
            if (timer !== undefined)
                clearTimeout(timer);
        }
        const text = await response.text();
        let parsed;
        if (text) {
            try {
                parsed = JSON.parse(text);
            }
            catch {
                parsed = undefined;
            }
        }
        if (!response.ok) {
            const message = (parsed && parsed.message) ||
                `ReelForge API error ${response.status}`;
            throw new ReelForgeApiError(response.status, message, parsed ?? text, response.headers.get("X-Correlation-ID") || undefined);
        }
        // Unwrap the `{ status, data }` envelope. `data` may be absent for empty
        // payloads (the server omits it when falsy), so fall back to the envelope.
        if (parsed && "data" in parsed) {
            return parsed.data;
        }
        return (parsed ?? undefined);
    }
}
// Menivor names (the product was renamed from ReelForge). These are the
// canonical exports; the ReelForge* names stay as aliases so existing code
// keeps compiling.
export { ReelForgeClient as MenivorClient, ReelForgeApiError as MenivorApiError };
export default ReelForgeClient;
