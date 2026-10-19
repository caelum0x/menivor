import type { Presign, PresignRequest, RegisteredUpload, RegisterUploadRequest } from "../client.js";
import type { Requester } from "../transport.js";
export declare class UploadsResource {
    private readonly request;
    constructor(request: Requester);
    presign(body: PresignRequest): Promise<Presign>;
    register(body: RegisterUploadRequest): Promise<RegisteredUpload>;
}
