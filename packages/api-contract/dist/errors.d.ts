export type ApiErrorCategory = "validation" | "authentication" | "payment_required" | "forbidden" | "not_found" | "conflict" | "rate_limited" | "unavailable" | "unknown";
export declare function apiErrorCategory(status: number): ApiErrorCategory;
export declare class ReelForgeApiError extends Error {
    readonly status: number;
    readonly category: ApiErrorCategory;
    readonly correlationId?: string;
    readonly retryEligible: boolean;
    readonly body: unknown;
    constructor(options: {
        status: number;
        message: string;
        body?: unknown;
        correlationId?: string;
        retryEligible?: boolean;
    });
}
