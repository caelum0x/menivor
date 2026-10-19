/** OTT creator studio (MV1) API. Signed in; the routes answer 404 until the studio is live. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface OttTitle {
  readonly id: string;
  readonly title: string;
  readonly synopsis: string;
  readonly kind: string;
  readonly artwork_url: string;
  readonly duration_s: number;
  readonly genres: readonly string[];
  readonly rating: string;
  readonly access_tier: "free" | "paid";
  readonly status: "draft" | "published" | "hidden";
  readonly hidden_reason: string;
  readonly package_status: string;
  readonly source_job_id: string | null;
  readonly credits?: readonly Credit[];
}

/** One cast or crew line (Wave Q QM1.5). */
export interface Credit {
  readonly name: string;
  readonly role: string;
}

/** "Ana Lee, Director" per line to credits; lines without a role are dropped. At most 30. */
export function parseCredits(text: string): Credit[] {
  return text.split("\n").map((line) => {
    const at = line.lastIndexOf(",");
    return at < 0 ? null : { name: line.slice(0, at).trim().slice(0, 80), role: line.slice(at + 1).trim().slice(0, 40) };
  }).filter((c): c is Credit => Boolean(c && c.name && c.role)).slice(0, 30);
}

export function formatCredits(credits: readonly Credit[] | undefined): string {
  return (credits ?? []).map((c) => `${c.name}, ${c.role}`).join("\n");
}

export interface OttChannel {
  readonly id: string;
  readonly handle: string;
  readonly title: string;
  readonly tagline: string;
  readonly layout: "grid" | "rails" | "course";
  readonly brand_colors: readonly string[];
  readonly status: string;
  readonly storefront_path: string;
  readonly titles: readonly OttTitle[];
  readonly series: readonly { id: string; title: string }[];
  readonly collections: readonly { id: string; title: string; title_ids: readonly string[] }[];
}

export interface PublishAllResult {
  readonly channel: OttChannel;
  readonly published: readonly string[];
  readonly held: readonly { title_id: string; reason: string }[];
  readonly seconds: number;
  readonly target_seconds: number;
  readonly within_target: boolean;
}

export function getStudio(options?: RequestOptions): Promise<OttChannel> {
  return apiRequest<OttChannel>("/ott/studio", { options });
}

export function publishAll(options?: RequestOptions): Promise<PublishAllResult> {
  return apiRequest<PublishAllResult>("/ott/studio/publish-all", { method: "POST", body: {}, options });
}

export function updateChannel(body: Partial<Pick<OttChannel, "title" | "tagline" | "handle" | "layout">>, options?: RequestOptions) {
  return apiRequest<OttChannel>("/ott/studio/channel", { method: "PATCH", body, options });
}

export function updateTitle(titleId: string, body: Record<string, unknown>, options?: RequestOptions) {
  const tid = encodeURIComponent(titleId);
  return apiRequest<OttTitle>(`/ott/studio/titles/${tid}`, { method: "PATCH", body, options });
}

export function setPublished(titleId: string, published: boolean, options?: RequestOptions) {
  const tid = encodeURIComponent(titleId);
  return published
    ? apiRequest<OttTitle>(`/ott/studio/titles/${tid}/publish`, { method: "POST", options })
    : apiRequest<OttTitle>(`/ott/studio/titles/${tid}/unpublish`, { method: "POST", options });
}

export function packageTitle(titleId: string, options?: RequestOptions) {
  const tid = encodeURIComponent(titleId);
  return apiRequest<{ lane: string; status: string }>(`/ott/studio/titles/${tid}/package`, { method: "POST", options });
}
