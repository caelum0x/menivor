import type {
  Presign,
  PresignRequest,
  RegisteredUpload,
  RegisterUploadRequest,
} from "../client.js";
import type { Requester } from "../transport.js";

export class UploadsResource {
  constructor(private readonly request: Requester) {}

  presign(body: PresignRequest): Promise<Presign> {
    return this.request("POST", "/uploads/presign", { body });
  }


  register(body: RegisterUploadRequest): Promise<RegisteredUpload> {
    return this.request("POST", "/uploads/register", { body });
  }
}
