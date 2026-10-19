/** Genre shot-template engine — browse + compile + instantiate viral formats. */
export class TemplatesResource {
    request;
    constructor(request) {
        this.request = request;
    }
    list() {
        return this.request("GET", "/templates");
    }
    get(slug) {
        return this.request("GET", `/templates/${encodeURIComponent(slug)}`);
    }
    compile(slug, body) {
        return this.request("POST", `/templates/${encodeURIComponent(slug)}/compile`, { body });
    }
    instantiate(slug, body) {
        return this.request("POST", `/templates/${encodeURIComponent(slug)}/instantiate`, { body });
    }
}
