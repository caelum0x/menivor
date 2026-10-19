/** Funnel read-out client helpers (MR1). */

import { apiRequest } from "@/src/shared/api";

export interface FunnelRow {
  readonly user_id: string;
  readonly email: string;
  readonly signed_up: string | null;
  readonly card_check: string | null;
  readonly first_render: string | null;
  readonly first_kept: string | null;
  readonly first_payment: string | null;
  readonly plan: string;
  readonly source: string;
  readonly utm_source: string;
  readonly utm_medium: string;
  readonly utm_campaign: string;
  readonly referrer: string;
}

export interface FunnelPayload {
  readonly since: string;
  readonly totals: {
    readonly users: number;
    readonly reach: Readonly<Record<string, number>>;
    readonly by_source: Readonly<Record<string, number>>;
    readonly by_plan: Readonly<Record<string, number>>;
  };
  readonly rows: readonly FunnelRow[];
}

export const STEP_LABELS: readonly (readonly [keyof FunnelRow, string])[] = [
  ["signed_up", "Signed up"],
  ["card_check", "Card check"],
  ["first_render", "First render"],
  ["first_kept", "First kept"],
  ["first_payment", "First payment"],
];

export function dayOrNo(value: string | null): string {
  return value ? value.slice(0, 10) : "no";
}

export function fetchFunnel(since: string, token: string | undefined): Promise<FunnelPayload> {
  return apiRequest<FunnelPayload>(`/admin/funnel/readout?since=${encodeURIComponent(since)}`, {
    options: { token },
  });
}
