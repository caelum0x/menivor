/**
 * `POST /experiments/runs`: link a link-mode run (one job per hook) into one
 * 1-body/N-hooks experiment so the remake-winner loop tracks it. Topic runs
 * are registered by `POST /jobs` itself and never call this.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

import type { RunRegistrationBody } from "./plan";

export interface RunRegistrationResult {
  readonly batch_id: string;
  readonly experiment_key: string;
  readonly created: boolean;
  readonly loop: { readonly status: string; readonly mode: string };
  readonly loop_error?: string;
}

export function registerRun(
  body: RunRegistrationBody,
  options?: RequestOptions,
): Promise<RunRegistrationResult> {
  return apiRequest<RunRegistrationResult>("/experiments/runs", {
    method: "POST",
    body,
    options,
  });
}
