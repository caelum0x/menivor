export class JobsResource {
    request;
    constructor(request) {
        this.request = request;
    }
    create(body, options = {}) {
        return this.request("POST", "/jobs", {
            body,
            headers: options.idempotencyKey
                ? { "Idempotency-Key": options.idempotencyKey }
                : undefined,
        });
    }
    get(jobId) {
        return this.request("GET", `/jobs/${encodeURIComponent(jobId)}`);
    }
    list(params = {}) {
        return this.request("GET", "/jobs", { query: params });
    }
    retry(jobId) {
        return this.request("POST", `/jobs/${encodeURIComponent(jobId)}/retry`);
    }
    rerun(jobId, body = {}) {
        return this.request("POST", `/jobs/${encodeURIComponent(jobId)}/rerun`, {
            body,
        });
    }
    getBatch(batchId) {
        return this.request("GET", `/batches/${encodeURIComponent(batchId)}`);
    }
    exportCut(jobId, body, options = {}) {
        return this.request("POST", `/jobs/${encodeURIComponent(jobId)}/exports`, {
            body,
            headers: options.idempotencyKey
                ? { "Idempotency-Key": options.idempotencyKey }
                : undefined,
        });
    }
}
