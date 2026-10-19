import type { Entitlements, Usage } from "../client.js";
import type { Requester } from "../transport.js";

export class WorkspacesResource {
  constructor(private readonly request: Requester) {}

  usage(workspaceId: string, period?: string): Promise<Usage> {
    return this.request(
      "GET",
      `/me/workspaces/${encodeURIComponent(workspaceId)}/usage`,
      { query: period === undefined ? {} : { period } },
    );
  }

  entitlements(workspaceId: string): Promise<Entitlements> {
    return this.request(
      "GET",
      `/me/workspaces/${encodeURIComponent(workspaceId)}/entitlements`,
    );
  }
}
