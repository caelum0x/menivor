/**
 * Typed client for drafting ad-platform campaigns (apps/api
 * `domains/integrations/router.py`, the ``/campaigns/draft`` route).
 *
 * Every draft is created PAUSED on the platform itself -- Menivor never
 * enables spend. The workspace reviews and launches it from the platform's
 * own dashboard (Google Ads / Meta Ads Manager / Apple Search Ads).
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export interface Scope {
  readonly workspaceId?: string | null;
}

export interface DraftCampaignResult {
  readonly provider: string;
  readonly ad_account_id: string;
  readonly external_id: string;
  readonly name: string;
  readonly status: "paused";
  readonly manage_url: string;
}

export interface DraftCampaignInput {
  readonly name: string;
  readonly dailyBudgetMinor: number;
  readonly countries?: readonly string[];
  readonly adamId?: string;
}

export interface DraftableAccount {
  readonly id: string;
  readonly provider: string;
  readonly name: string;
  readonly currency: string;
}

interface AdAccountRaw {
  readonly id: string;
  readonly name: string;
  readonly currency: string;
}

interface ProviderCardRaw {
  readonly provider: string;
  readonly label: string;
  readonly campaign_drafts?: boolean;
  readonly accounts?: readonly AdAccountRaw[];
}

interface IntegrationsOverviewRaw {
  readonly ads: { readonly providers: readonly ProviderCardRaw[] };
}

/** Every connected ad account whose platform supports drafting a new campaign. */
export async function listDraftableAccounts(scope: Scope, options?: RequestOptions): Promise<DraftableAccount[]> {
  const overview = await request<IntegrationsOverviewRaw>(`/integrations${scopeQuery(scope)}`, { options });
  return overview.ads.providers
    .filter((p) => p.campaign_drafts)
    .flatMap((p) => (p.accounts ?? []).map((a) => ({ id: a.id, provider: p.label, name: a.name, currency: a.currency })));
}

function scopeQuery(scope: Scope = {}): string {
  const params = new URLSearchParams();
  if (scope.workspaceId) params.set("workspace_id", scope.workspaceId);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** A new, always-PAUSED campaign on the ad account's own platform. */
export function draftCampaign(adAccountId: string, input: DraftCampaignInput, scope: Scope,
  options?: RequestOptions): Promise<DraftCampaignResult> {
  const id = encodeURIComponent(adAccountId);
  return request<DraftCampaignResult>(`/integrations/ad-accounts/${id}/campaigns/draft${scopeQuery(scope)}`, {
    method: "POST",
    body: {
      name: input.name.trim(),
      daily_budget_minor: input.dailyBudgetMinor,
      countries: (input.countries ?? []).map((c) => c.trim().toUpperCase()).filter(Boolean),
      adam_id: (input.adamId ?? "").trim(),
    },
    options,
  });
}

/** Client-side check before the request leaves the browser. */
export function validateDraftInput(name: string, dailyBudgetMinor: number): string | null {
  if (!name.trim()) return "Name the campaign.";
  if (!Number.isFinite(dailyBudgetMinor) || dailyBudgetMinor <= 0) return "Set a daily budget greater than zero.";
  return null;
}
