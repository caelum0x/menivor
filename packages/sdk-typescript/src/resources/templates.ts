import type { Requester } from "../transport.js";

/** A seeded genre shot-template (gallery card). */
export interface TemplateSummary {
  slug: string;
  name: string;
  genre: string;
  description: string;
  aspect: string;
  min_duration_s: number;
  max_duration_s: number;
  loopable: boolean;
  slot_count: number;
}

export interface InstantiateResult {
  template: string;
  version: string;
  render_spec: Record<string, unknown>;
  reel_draft: Record<string, unknown>;
}

/** Genre shot-template engine — browse + compile + instantiate viral formats. */
export class TemplatesResource {
  constructor(private readonly request: Requester) {}

  list(): Promise<{ templates: TemplateSummary[] }> {
    return this.request("GET", "/templates");
  }

  get(slug: string): Promise<Record<string, unknown>> {
    return this.request("GET", `/templates/${encodeURIComponent(slug)}`);
  }

  compile(
    slug: string,
    body: { inputs: Record<string, unknown>; duration_s?: number; surface?: string },
  ): Promise<Record<string, unknown>> {
    return this.request("POST", `/templates/${encodeURIComponent(slug)}/compile`, { body });
  }

  instantiate(
    slug: string,
    body: { inputs: Record<string, unknown>; duration_s?: number; surface?: string },
  ): Promise<InstantiateResult> {
    return this.request("POST", `/templates/${encodeURIComponent(slug)}/instantiate`, { body });
  }
}
