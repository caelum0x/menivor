/**
 * `@reelforge/provider-adapter-kit` — the shared adapter contract + metadata:
 * license classes, deprecation/sunset registry, and the async job envelope
 * grammar. Byte-identical to the Python port (`reelforge_provider_adapter`,
 * golden fixtures) so the routing engine, SDKs, and burn-preview UIs agree.
 */

export {
  LICENSE_CLASSES,
  LICENSE_REGISTRY,
  licenseClass,
  canUseForPaid,
  type LicenseClass,
} from "./license.js";
export {
  DEPRECATION_REGISTRY,
  lifecycle,
  replacementFor,
  migrate,
  type Lifecycle,
  type DeprecationEntry,
  type MigrationHint,
} from "./deprecation.js";
export {
  STATES,
  normalizeState,
  isTerminal,
  normalizedUsage,
  type JobState,
  type NormalizedUsage,
} from "./envelope.js";
