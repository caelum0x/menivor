import type { Entitlements, Usage } from "../client.js";
import type { Requester } from "../transport.js";
export declare class WorkspacesResource {
    private readonly request;
    constructor(request: Requester);
    usage(workspaceId: string, period?: string): Promise<Usage>;
    entitlements(workspaceId: string): Promise<Entitlements>;
}
