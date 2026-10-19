/** Async-GPU render — start, poll status, advance (settle/refund on terminal). */
export class RenderResource {
    request;
    constructor(request) {
        this.request = request;
    }
    start(body) {
        return this.request("POST", "/render/jobs", { body });
    }
    get(jobId) {
        return this.request("GET", `/render/jobs/${encodeURIComponent(jobId)}`);
    }
    advance(jobId) {
        return this.request("POST", `/render/jobs/${encodeURIComponent(jobId)}/advance`);
    }
}
