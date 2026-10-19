/**
 * Canonical event catalog + envelope + push mapping (mirror of `events.py`).
 * Single source of event names, the `EventEnvelope` shape, and the event→push
 * table. Byte-identical to the Python port (golden fixtures).
 */

export const EVENT_TYPES = [
  "job.completed",
  "job.failed",
  "publish.succeeded",
  "publish.failed",
  "retention.ingested",
  "performance.ingested",
  "experiment.winner_selected",
  "gateway.key_spend_exceeded",
  "gateway.plan_changed",
  "marketplace.submission_approved",
  "marketplace.payout_paid",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

export interface PushDescriptor {
  channel: string;
  title: string;
  deep_link: string;
}

export const PUSH_MAP: Record<string, PushDescriptor> = {
  "job.completed": { channel: "push", title: "Your reel is ready", deep_link: "/jobs/{job_id}" },
  "job.failed": { channel: "push", title: "Reel generation failed", deep_link: "/jobs/{job_id}" },
  "publish.succeeded": { channel: "push", title: "Published", deep_link: "/publish/{job_id}" },
  "publish.failed": { channel: "push", title: "Publish failed", deep_link: "/publish/{job_id}" },
  "retention.ingested": { channel: "in_app", title: "New retention data", deep_link: "/insights/{job_id}" },
  "performance.ingested": { channel: "in_app", title: "Performance updated", deep_link: "/performance/{job_id}" },
  "experiment.winner_selected": { channel: "push", title: "A/B winner picked", deep_link: "/experiments/{experiment_key}" },
  "gateway.key_spend_exceeded": { channel: "email", title: "Spend cap reached", deep_link: "/gateway" },
  "gateway.plan_changed": { channel: "in_app", title: "Plan updated", deep_link: "/plan" },
  "marketplace.submission_approved": { channel: "push", title: "Submission approved", deep_link: "/clipmarket" },
  "marketplace.payout_paid": { channel: "push", title: "You got paid", deep_link: "/wallet" },
};

export interface EventEnvelope<T = Record<string, unknown>> {
  id: string;
  type: string;
  occurred_at: string;
  workspace_id: string | null;
  dedupe_key: string;
  payload: T;
}

export function isEventType(name: string): name is EventType {
  return (EVENT_TYPES as readonly string[]).includes(name);
}

export interface MakeEnvelopeOptions {
  id: string;
  occurred_at: string;
  workspace_id?: string | null;
  dedupe_key?: string;
}

export function makeEnvelope<T extends Record<string, unknown>>(
  eventType: string,
  payload: T,
  opts: MakeEnvelopeOptions,
): EventEnvelope<T> {
  if (!isEventType(eventType)) throw new Error(`unknown event type ${eventType}`);
  return {
    id: opts.id,
    type: eventType,
    occurred_at: opts.occurred_at,
    workspace_id: opts.workspace_id ?? null,
    dedupe_key: opts.dedupe_key ?? `${eventType}:${opts.id}`,
    payload,
  };
}

export function pushFor(eventType: string): PushDescriptor | undefined {
  return PUSH_MAP[eventType];
}

export function validateEnvelope(env: Partial<EventEnvelope>): string[] {
  const errors: string[] = [];
  for (const field of ["id", "type", "occurred_at", "dedupe_key", "payload"] as const) {
    if (!(field in env)) errors.push(`missing field ${field}`);
  }
  if (env.type !== undefined && !isEventType(String(env.type))) {
    errors.push(`unknown event type ${env.type}`);
  }
  if (env.payload !== undefined && (typeof env.payload !== "object" || env.payload === null)) {
    errors.push("payload must be an object");
  }
  return errors;
}
