export class BrollResource {
    request;
    constructor(request) {
        this.request = request;
    }
    generate(body, options = {}) {
        return this.request("POST", "/generation/broll/generate", {
            body,
            headers: options.idempotencyKey
                ? { "Idempotency-Key": options.idempotencyKey }
                : undefined,
        });
    }
    get(generationId) {
        return this.request("GET", `/generation/broll/generations/${encodeURIComponent(generationId)}`);
    }
    async list() {
        const data = await this.request("GET", "/generation/broll/generations");
        return Array.isArray(data) ? data : (data.generations ?? []);
    }
}
