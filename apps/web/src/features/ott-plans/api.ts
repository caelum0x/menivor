/** OTT caps and usage (MV7). Included in the creator's plan with caps; overage only after an opt-in. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface MeterView {
  readonly meter: "gb_stored" | "minutes_delivered" | "encode_minutes" | "ai_minutes";
  readonly unit: string;
  readonly used: number;
  readonly included: number;
  readonly cap_is_target: boolean;
  readonly at_cap: boolean;
}

export interface OttPlanView {
  readonly plan: string;
  readonly month: string;
  readonly meters: readonly MeterView[];
  readonly overage: { readonly opted_in: boolean; readonly terms_version: string };
  readonly ott_plans_sellable: boolean;
}

export const getOttPlan = (options?: RequestOptions) => apiRequest<OttPlanView>("/ott/studio/plan", { options });

export const setOttOverage = (optIn: boolean, options?: RequestOptions) =>
  apiRequest<OttPlanView>("/ott/studio/plan/overage", { method: "POST", body: { opt_in: optIn }, options });

export const METER_LABELS: Record<MeterView["meter"], string> = {
  gb_stored: "Storage",
  minutes_delivered: "Streaming",
  encode_minutes: "Encoding",
  ai_minutes: "AI minutes",
};
