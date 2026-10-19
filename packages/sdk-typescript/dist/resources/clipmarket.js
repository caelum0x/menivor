/** Clipping marketplace — campaigns, submissions, fraud-gated CPM payout. */
export class ClipmarketResource {
    request;
    constructor(request) {
        this.request = request;
    }
    createCampaign(body) {
        return this.request("POST", "/clipmarket/campaigns", { body });
    }
    listCampaigns(params = {}) {
        return this.request("GET", "/clipmarket/campaigns", { query: params });
    }
    submit(campaignId, clipUrl) {
        return this.request("POST", `/clipmarket/campaigns/${encodeURIComponent(campaignId)}/submit`, {
            body: { clip_url: clipUrl },
        });
    }
    review(submissionId, body) {
        return this.request("POST", `/clipmarket/submissions/${encodeURIComponent(submissionId)}/review`, {
            body,
        });
    }
}
