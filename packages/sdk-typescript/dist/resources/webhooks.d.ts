import type { CreatedWebhookSubscription, WebhookDelivery, WebhookSubscribeRequest, WebhookSubscription } from "../client.js";
import type { Requester } from "../transport.js";
export declare class WebhooksResource {
    private readonly request;
    constructor(request: Requester);
    private base;
    create(workspaceId: string, body: WebhookSubscribeRequest): Promise<CreatedWebhookSubscription>;
    list(workspaceId: string): Promise<WebhookSubscription[]>;
    delete(workspaceId: string, subscriptionId: string): Promise<{
        id: string;
        revoked: boolean;
    }>;
    test(workspaceId: string, subscriptionId: string): Promise<WebhookDelivery>;
    deliveries(workspaceId: string, subscriptionId: string, limit?: number): Promise<WebhookDelivery[]>;
}
