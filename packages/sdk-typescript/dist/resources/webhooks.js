export class WebhooksResource {
    request;
    constructor(request) {
        this.request = request;
    }
    base(workspaceId) {
        return `/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks`;
    }
    create(workspaceId, body) {
        return this.request("POST", this.base(workspaceId), { body });
    }
    list(workspaceId) {
        return this.request("GET", this.base(workspaceId));
    }
    delete(workspaceId, subscriptionId) {
        return this.request("DELETE", `${this.base(workspaceId)}/${encodeURIComponent(subscriptionId)}`);
    }
    test(workspaceId, subscriptionId) {
        return this.request("POST", `${this.base(workspaceId)}/${encodeURIComponent(subscriptionId)}/test`);
    }
    deliveries(workspaceId, subscriptionId, limit) {
        return this.request("GET", `${this.base(workspaceId)}/${encodeURIComponent(subscriptionId)}/deliveries`, { query: limit === undefined ? {} : { limit } });
    }
}
