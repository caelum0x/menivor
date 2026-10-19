export function apiErrorCategory(status) {
    if (status === 400 || status === 422)
        return "validation";
    if (status === 401)
        return "authentication";
    if (status === 402)
        return "payment_required";
    if (status === 403)
        return "forbidden";
    if (status === 404)
        return "not_found";
    if (status === 409)
        return "conflict";
    if (status === 429)
        return "rate_limited";
    if (status >= 500)
        return "unavailable";
    return "unknown";
}
export class ReelForgeApiError extends Error {
    status;
    category;
    correlationId;
    retryEligible;
    body;
    constructor(options) {
        super(options.message);
        this.name = "ReelForgeApiError";
        this.status = options.status;
        this.category = apiErrorCategory(options.status);
        this.correlationId = options.correlationId;
        this.retryEligible = options.retryEligible ?? options.status >= 500;
        this.body = options.body;
    }
}
