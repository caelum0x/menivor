import type {
  BrollGenerateInput,
  BrollGenerationSnapshot,
} from "@reelforge/api-contract";
import type { Requester } from "../transport.js";

export interface GenerateBrollOptions {
  /** Stable key to reuse when a create response is ambiguous. */
  idempotencyKey?: string;
}

export class BrollResource {
  constructor(private readonly request: Requester) {}

  generate(
    body: BrollGenerateInput,
    options: GenerateBrollOptions = {},
  ): Promise<BrollGenerationSnapshot> {
    return this.request("POST", "/generation/broll/generate", {
      body,
      headers: options.idempotencyKey
        ? { "Idempotency-Key": options.idempotencyKey }
        : undefined,
    });
  }

  get(generationId: string): Promise<BrollGenerationSnapshot> {
    return this.request(
      "GET",
      `/generation/broll/generations/${encodeURIComponent(generationId)}`,
    );
  }

  async list(): Promise<BrollGenerationSnapshot[]> {
    const data = await this.request<
      BrollGenerationSnapshot[] | { generations?: BrollGenerationSnapshot[] }
    >("GET", "/generation/broll/generations");
    return Array.isArray(data) ? data : (data.generations ?? []);
  }
}
