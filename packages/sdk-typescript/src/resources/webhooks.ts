import type {
  CreatedWebhookSubscription,
  WebhookDelivery,
  WebhookSubscribeRequest,
  WebhookSubscription,
} from "../client.js";
import type { Requester } from "../transport.js";

export class WebhooksResource {
  constructor(private readonly request: Requester) {}

  private base(workspaceId: string): string {
    return `/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks`;
  }

  create(workspaceId: string, body: WebhookSubscribeRequest): Promise<CreatedWebhookSubscription> {
    return this.request("POST", this.base(workspaceId), { body });
  }

  list(workspaceId: string): Promise<WebhookSubscription[]> {
    return this.request("GET", this.base(workspaceId));
  }

  delete(workspaceId: string, subscriptionId: string): Promise<{ id: string; revoked: boolean }> {
    return this.request("DELETE", `${this.base(workspaceId)}/${encodeURIComponent(subscriptionId)}`);
  }

  test(workspaceId: string, subscriptionId: string): Promise<WebhookDelivery> {
    return this.request("POST", `${this.base(workspaceId)}/${encodeURIComponent(subscriptionId)}/test`);
  }

  deliveries(workspaceId: string, subscriptionId: string, limit?: number): Promise<WebhookDelivery[]> {
    return this.request(
      "GET",
      `${this.base(workspaceId)}/${encodeURIComponent(subscriptionId)}/deliveries`,
      { query: limit === undefined ? {} : { limit } },
    );
  }
}
