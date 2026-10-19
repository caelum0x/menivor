export class UploadsResource {
    request;
    constructor(request) {
        this.request = request;
    }
    presign(body) {
        return this.request("POST", "/uploads/presign", { body });
    }
    register(body) {
        return this.request("POST", "/uploads/register", { body });
    }
}
