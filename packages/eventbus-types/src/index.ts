/**
 * `@reelforge/eventbus-types` — canonical event catalog + envelopes + push map.
 *
 * The single shared source of event names and payloads, byte-identical to the
 * Python port (`reelforge_eventbus`, golden fixtures) so the outbox, SDK
 * webhooks and the client notification router all agree.
 */

export {
  EVENT_TYPES,
  PUSH_MAP,
  isEventType,
  makeEnvelope,
  pushFor,
  validateEnvelope,
  type EventType,
  type PushDescriptor,
  type EventEnvelope,
  type MakeEnvelopeOptions,
} from "./events.js";
