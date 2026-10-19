/**
 * Channel viewer API (MV6). The session rides in `X-OTT-Viewer`; every call is
 * for one channel handle. Money is not involved here.
 */

import { API_BASE } from "@/src/shared/api";
import type { PlaybackGrant } from "@menivor/ott-player";

export class ViewerApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export interface ViewerProfile {
  readonly id: string;
  readonly email: string;
  readonly display_name: string;
}

export interface ProgressView {
  readonly title_id: string;
  readonly position_s: number;
  readonly duration_s: number;
  readonly finished: boolean;
  readonly device: string | null;
  readonly title?: string;
}

async function viewerCall<T>(path: string, init: { method?: string; body?: unknown; session?: string } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (init.session) headers["X-OTT-Viewer"] = init.session;
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API_BASE}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: "no-store",
  });
  const payload = (await response.json().catch(() => ({}))) as { data?: T; message?: string };
  if (!response.ok) throw new ViewerApiError(payload.message || "Something went wrong. Try again.", response.status);
  return payload.data as T;
}

const enc = encodeURIComponent;

export function exchange(handle: string, accessToken: string, device = "web") {
  const h = enc(handle);
  return viewerCall<{ session: string; expires_at: number; viewer: ViewerProfile }>(`/ott/viewers/${h}/session`, {
    method: "POST",
    body: { access_token: accessToken, device },
  });
}

export function getMe(handle: string, session: string) {
  const h = enc(handle);
  return viewerCall<ViewerProfile>(`/ott/viewers/${h}/me`, { session });
}

export function renameMe(handle: string, session: string, displayName: string) {
  const h = enc(handle);
  return viewerCall<ViewerProfile>(`/ott/viewers/${h}/me`, { method: "PATCH", session, body: { display_name: displayName } });
}

export function deleteMe(handle: string, session: string) {
  const h = enc(handle);
  return viewerCall<{ deleted: boolean; history_deleted: number }>(`/ott/viewers/${h}/me`, { method: "DELETE", session });
}

export function signOutEverywhere(handle: string, session: string) {
  const h = enc(handle);
  return viewerCall<{ signed_out: boolean }>(`/ott/viewers/${h}/sign-out`, { method: "POST", session });
}

export function continueWatching(handle: string, session: string) {
  const h = enc(handle);
  return viewerCall<{ items: ProgressView[] }>(`/ott/viewers/${h}/continue`, { session });
}

export function getProgress(handle: string, session: string, titleId: string) {
  const h = enc(handle);
  const t = enc(titleId);
  return viewerCall<ProgressView>(`/ott/viewers/${h}/progress/${t}`, { session });
}

export function putProgress(handle: string, session: string, titleId: string, positionS: number, durationS: number) {
  const h = enc(handle);
  const t = enc(titleId);
  return viewerCall<ProgressView>(`/ott/viewers/${h}/progress/${t}`, {
    method: "PUT",
    session,
    body: { position_s: positionS, duration_s: durationS, device: "web" },
  });
}

export interface PurchaseView {
  readonly id: string;
  readonly offer: string;
  readonly kind: "svod" | "tvod" | "rental";
  readonly status: "active" | "revoked" | "expired";
  readonly expires_at: string | null;
}

export function myPurchases(handle: string, session: string) {
  const h = enc(handle);
  return viewerCall<{ items: PurchaseView[] }>(`/ott/viewers/${h}/entitlements`, { session });
}

export function approveTvCode(handle: string, session: string, userCode: string) {
  const h = enc(handle);
  return viewerCall<{ approved: boolean }>(`/ott/viewers/${h}/tv-codes/approve`, {
    method: "POST",
    session,
    body: { user_code: userCode },
  });
}

/** Start playback as the signed-in channel viewer (stream limits and access follow the viewer). */
export function startViewerPlayback(titleId: string, viewerId: string, session: string): Promise<PlaybackGrant> {
  const tid = enc(titleId);
  return viewerCall<PlaybackGrant>(`/ott/play/${tid}`, {
    method: "POST",
    session,
    body: { viewer_id: viewerId },
  });
}

/* ---- Wave Q QM1.5: my list and ratings on this channel ---- */

export interface Rating {
  readonly title_id: string;
  readonly mine: number | null;
  readonly count: number;
  readonly average: number | null;
}

export function myList(handle: string, session: string) {
  const h = enc(handle);
  return viewerCall<{ items: { id: string; title: string }[] }>(`/ott/viewers/${h}/watchlist`, { session });
}

export function setOnList(handle: string, session: string, titleId: string, on: boolean) {
  const h = enc(handle);
  const tid = enc(titleId);
  if (on) return viewerCall<{ title_id: string }>(`/ott/viewers/${h}/watchlist/${tid}`, { method: "PUT", session });
  return viewerCall<{ title_id: string }>(`/ott/viewers/${h}/watchlist/${tid}`, { method: "DELETE", session });
}

export function getRating(handle: string, session: string, titleId: string) {
  const h = enc(handle);
  const tid = enc(titleId);
  return viewerCall<Rating>(`/ott/viewers/${h}/ratings/${tid}`, { session });
}

export function rateTitle(handle: string, session: string, titleId: string, stars: number) {
  const h = enc(handle);
  const tid = enc(titleId);
  return viewerCall<Rating>(`/ott/viewers/${h}/ratings/${tid}`, { method: "PUT", session, body: { stars } });
}

export function unrateTitle(handle: string, session: string, titleId: string) {
  const h = enc(handle);
  const tid = enc(titleId);
  return viewerCall<Rating>(`/ott/viewers/${h}/ratings/${tid}`, { method: "DELETE", session });
}
