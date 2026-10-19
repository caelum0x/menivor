/**
 * Typed client for Settings > Integrations (apps/api `domains/integrations/router.py`).
 *
 * Secrets (ad-platform API keys, Shopify tokens, Medusa keys) are sent once and
 * never returned; the API stores them encrypted and only shows a masked hint.
 * Ad changes are proposals: nothing reaches an ad platform until someone
 * approves the proposal.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export interface Scope {
  readonly workspaceId?: string | null;
  readonly brandSpaceId?: string | null;
}

export interface AdAccount {
  readonly id: string;
  readonly provider: string;
  readonly external_id: string;
  readonly name: string;
  readonly currency: string;
  readonly status: string;
  readonly brand_space_ids: readonly string[];
  readonly last_pulled_at: string | null;
}

export interface ProviderCard {
  readonly provider: string;
  readonly label: string;
  readonly capabilities: string;
  readonly auth: "oauth" | "api_key";
  readonly configured: boolean;
  readonly delivery: boolean;
  readonly connected: boolean;
  readonly status: string;
  readonly token_hint: string;
  readonly last_error: string | null;
  readonly account_count: number;
  readonly accounts: readonly AdAccount[];
}

export interface OnboardingStep {
  readonly key: string;
  readonly label: string;
  readonly credits: number;
  readonly done: boolean;
}

export interface SocialPlatform {
  readonly provider: string;
  readonly label: string;
  readonly ready: boolean;
  readonly notes: readonly string[];
  readonly account: { readonly id: string; readonly handle: string; readonly display_name: string; readonly status: string } | null;
}

export interface IntegrationsOverview {
  readonly ads: { readonly providers: readonly ProviderCard[]; readonly can_manage: boolean };
  readonly agent: {
    readonly name: string;
    readonly plan_allows: boolean;
    readonly plan_message: string;
    readonly onboarding: { readonly steps: readonly OnboardingStep[]; readonly earned: number; readonly total: number };
  };
  readonly slack: {
    readonly configured: boolean;
    readonly plan_allows: boolean;
    readonly connected: boolean;
    readonly team_name: string | null;
    readonly approvers: readonly string[];
    readonly command: string;
  };
  readonly social: { readonly platforms: readonly SocialPlatform[]; readonly can_manage: boolean };
  readonly products: { readonly sources: readonly { provider: string; name: string; token_hint: string }[] };
  readonly brand_spaces: readonly { id: string; name: string }[];
}

export interface Proposal {
  readonly id: string;
  readonly title: string;
  readonly summary: string;
  readonly status: string;
  readonly risk: string;
  readonly error: string;
  readonly payload: { readonly reason?: string; readonly provider?: string; readonly entity_name?: string };
}

export interface AgentAnswer {
  readonly answer: string;
  readonly used_llm: boolean;
  readonly credits_granted: number;
  readonly suggestions: readonly { entity_name: string; reason: string }[];
}

export interface ProductImport {
  readonly id: string;
  readonly provider: string;
  readonly store_name: string;
  readonly product_count: number;
}

/** Query string for the caller's workspace / Brand space (empty when personal). */
export function scopeQuery(scope: Scope = {}, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams();
  if (scope.workspaceId) params.set("workspace_id", scope.workspaceId);
  if (scope.brandSpaceId) params.set("brand_space_id", scope.brandSpaceId);
  for (const [key, value] of Object.entries(extra)) if (value) params.set(key, value);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** ``path`` plus the scope query (kept separate so the route literal stays greppable for the API audit). */
export function scoped(path: string, scope: Scope = {}): string {
  return `${path}${scopeQuery(scope)}`;
}

/** The card's status line, Creatify style: "Not connected" / "No Meta accounts" / "2 accounts". */
export function cardStatus(card: ProviderCard): string {
  if (!card.connected) return card.configured || card.auth === "api_key" ? "Not connected" : "Not available yet";
  if (card.status === "needs_reauth") return "Reconnect needed";
  if (card.account_count === 0) return `No ${card.label} accounts`;
  return card.account_count === 1 ? "1 account" : `${card.account_count} accounts`;
}

/** Client-side check before a key leaves the browser. */
export function validateSecret(value: string, what = "key"): string | null {
  const secret = value.trim();
  if (secret.length < 8) return `Paste the full ${what}.`;
  if (secret.length > 4096) return `That ${what} is too long.`;
  if (/\s/.test(secret)) return `A ${what} does not contain spaces.`;
  return null;
}

export function getIntegrations(scope: Scope, options?: RequestOptions): Promise<IntegrationsOverview> {
  return request<IntegrationsOverview>(scoped(`/integrations`, scope), { options });
}

// Path parts are encoded first so each route stays one plain template literal (the API audit reads them).
export function startAdConnect(provider: string, scope: Scope, options?: RequestOptions) {
  const slug = encodeURIComponent(provider);
  return request<{ authorize_url: string }>(
    scoped(`/integrations/ads/${slug}/connect`, scope),
    { method: "POST", options },
  );
}

export function connectAdKey(provider: string, apiKey: string, scope: Scope, options?: RequestOptions) {
  const slug = encodeURIComponent(provider);
  return request<{ provider: string; credits_granted: number }>(
    scoped(`/integrations/ads/${slug}/key`, scope),
    { method: "POST", body: { api_key: apiKey.trim() }, options },
  );
}

export function finishCallback(code: string, state: string, options?: RequestOptions) {
  return request<{ provider: string }>("/integrations/callback", { method: "POST", body: { code, state }, options });
}

export function disconnectAd(provider: string, scope: Scope, options?: RequestOptions) {
  const slug = encodeURIComponent(provider);
  return request<{ disconnected: boolean }>(
    scoped(`/integrations/ads/${slug}`, scope),
    { method: "DELETE", options },
  );
}

export function setBrandSpaces(adAccountId: string, brandSpaceIds: readonly string[], scope: Scope,
  options?: RequestOptions) {
  const accountId = encodeURIComponent(adAccountId);
  return request<AdAccount>(
    scoped(`/integrations/ad-accounts/${accountId}/brand-spaces`, scope),
    { method: "PUT", body: { brand_space_ids: brandSpaceIds }, options },
  );
}

export function refreshReports(scope: Scope, options?: RequestOptions) {
  return request<{ accounts: number; rows: number; errors: { message: string }[] }>(
    scoped(`/integrations/ads/refresh`, scope),
    { method: "POST", body: { days: 7 }, options },
  );
}

export function askAgent(question: string, scope: Scope, options?: RequestOptions) {
  return request<AgentAnswer>(scoped(`/integrations/agent/ask`, scope), {
    method: "POST", body: { question: question.trim() }, options,
  });
}

export function proposeChanges(scope: Scope, options?: RequestOptions) {
  return request<{ proposals: Proposal[] }>(scoped(`/integrations/agent/propose`, scope), {
    method: "POST", body: { days: 7 }, options,
  });
}

export async function listProposals(scope: Scope, options?: RequestOptions): Promise<Proposal[]> {
  const data = await request<{ items?: Proposal[] }>(scoped(`/integrations/agent/proposals`, scope), { options });
  return data.items ?? [];
}

export function decideProposal(id: string, decision: "approve" | "reject", scope: Scope, options?: RequestOptions) {
  const itemId = encodeURIComponent(id);
  return request<{ item: Proposal }>(
    decision === "approve"
      ? scoped(`/integrations/agent/proposals/${itemId}/approve`, scope)
      : scoped(`/integrations/agent/proposals/${itemId}/reject`, scope),
    { method: "POST", body: {}, options },
  );
}

export function installSlack(scope: Scope, options?: RequestOptions) {
  return request<{ authorize_url: string }>(scoped(`/integrations/slack/install`, scope), {
    method: "POST", options,
  });
}

export function disconnectSlack(scope: Scope, options?: RequestOptions) {
  return request<{ disconnected: boolean }>(scoped(`/integrations/slack`, scope), { method: "DELETE", options });
}

/** Social connect reuses multi-account publishing (one account per platform, shared by the workspace). */
export function startSocialConnect(provider: string, scope: Scope, options?: RequestOptions) {
  const slug = encodeURIComponent(provider);
  return request<{ authorize_url: string }>(
    scoped(`/multipost/connect/${slug}/authorize`, { workspaceId: scope.workspaceId }),
    { options },
  );
}

export function importShopify(shop: string, token: string, scope: Scope, options?: RequestOptions) {
  return request<ProductImport>(scoped(`/integrations/products/shopify`, scope), {
    method: "POST", body: { shop: shop.trim(), token: token.trim(), limit: 250 }, options,
  });
}

export function importMedusa(baseUrl: string, publishableKey: string, storefrontUrl: string, scope: Scope,
  options?: RequestOptions) {
  return request<ProductImport>(scoped(`/integrations/products/medusa`, scope), {
    method: "POST",
    body: { base_url: baseUrl.trim(), publishable_key: publishableKey.trim(), storefront_url: storefrontUrl.trim(),
      limit: 250 },
    options,
  });
}

/** Re-import from a saved Shopify or Medusa source (the stored token is used server-side). */
export function resyncProducts(provider: "shopify" | "medusa", scope: Scope, options?: RequestOptions) {
  const slug = encodeURIComponent(provider);
  return request<ProductImport>(scoped(`/integrations/products/${slug}/resync`, scope), { method: "POST", options });
}

export function importCsv(input: { text?: string; url?: string; currency?: string }, scope: Scope,
  options?: RequestOptions) {
  return request<ProductImport>(scoped(`/integrations/products/csv`, scope), {
    method: "POST",
    body: { text: input.text || null, url: input.url || null, currency: input.currency || "USD", limit: 250 },
    options,
  });
}

// --------------------------------------------------------------------------- #
// Phase 3 "Connect your store" (apps/api `domains/store_connect/router.py`).
// Per-caller, not workspace-scoped: a credential is written once, validated
// server-side against Apple/Google, and never echoed back.
// --------------------------------------------------------------------------- #
export interface StoreConnection {
  readonly provider: "appstore" | "play";
  readonly account_name: string;
  readonly status: string;
  readonly status_note: string;
  readonly connected_at: string | null;
  readonly package_names: readonly string[] | null;
}

export interface StoreApp {
  readonly id?: string;
  readonly package_name?: string;
  readonly name?: string;
  readonly bundle_id?: string;
  readonly version?: string;
  readonly version_name?: string;
  readonly version_code?: string | null;
  readonly state?: string;
  readonly average_rating: number | null;
  readonly sample_size: number;
  readonly approximate: boolean;
}

export function listStoreConnections(options?: RequestOptions) {
  return request<{ connections: StoreConnection[] }>(`/store-connect`, { options });
}

export function connectAppStore(
  issuerId: string, keyId: string, privateKeyPem: string, options?: RequestOptions,
) {
  return request<StoreConnection>(`/store-connect/appstore`, {
    method: "POST",
    body: { issuer_id: issuerId.trim(), key_id: keyId.trim(), private_key_pem: privateKeyPem.trim() },
    options,
  });
}

export function connectPlay(serviceAccountJson: string, options?: RequestOptions) {
  return request<StoreConnection>(`/store-connect/play`, {
    method: "POST", body: { service_account_json: serviceAccountJson.trim() }, options,
  });
}

export function disconnectStore(provider: "appstore" | "play", options?: RequestOptions) {
  return request<{ disconnected: boolean }>(`/store-connect/${provider}`, { method: "DELETE", options });
}

export function listAppStoreApps(options?: RequestOptions) {
  return request<{ apps: StoreApp[] }>(`/store-connect/appstore/apps`, { options });
}

export function listPlayApps(options?: RequestOptions) {
  return request<{ apps: StoreApp[] }>(`/store-connect/play/apps`, { options });
}

export function addPlayApp(packageName: string, options?: RequestOptions) {
  return request<StoreApp>(`/store-connect/play/apps`, {
    method: "POST", body: { package_name: packageName.trim() }, options,
  });
}
