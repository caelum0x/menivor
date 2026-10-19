import type { BrollGenerateInput, BrollGenerationSnapshot } from "@reelforge/api-contract";
import type { Requester } from "../transport.js";
export interface GenerateBrollOptions {
    /** Stable key to reuse when a create response is ambiguous. */
    idempotencyKey?: string;
}
export declare class BrollResource {
    private readonly request;
    constructor(request: Requester);
    generate(body: BrollGenerateInput, options?: GenerateBrollOptions): Promise<BrollGenerationSnapshot>;
    get(generationId: string): Promise<BrollGenerationSnapshot>;
    list(): Promise<BrollGenerationSnapshot[]>;
}
