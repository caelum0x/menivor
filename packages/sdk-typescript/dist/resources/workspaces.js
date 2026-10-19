export class WorkspacesResource {
    request;
    constructor(request) {
        this.request = request;
    }
    usage(workspaceId, period) {
        return this.request("GET", `/me/workspaces/${encodeURIComponent(workspaceId)}/usage`, { query: period === undefined ? {} : { period } });
    }
    entitlements(workspaceId) {
        return this.request("GET", `/me/workspaces/${encodeURIComponent(workspaceId)}/entitlements`);
    }
}
