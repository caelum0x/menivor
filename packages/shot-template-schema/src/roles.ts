/** Canonical slot roles + ordering (mirror of `roles.py`). */

// Superset of the backend `templates` domain's `SlotSpec` roles
// (`app.domains.templates.slots`) so every seeded system template projects onto
// a valid schema blueprint; the backend enforces that parity at registry load
// (`presets/__init__.py`), keeping the picker and the seeded templates in sync.
export const ROLE_ORDER = [
  "hook",
  "setup",
  "proof1",
  "proof2",
  "rising",
  "body",
  "escalation",
  "exchange",
  "climax",
  "payoff",
  "button",
  "cta",
  "loop",
  "seam",
] as const;

export type SlotRole = (typeof ROLE_ORDER)[number];

const INDEX = new Map<string, number>(ROLE_ORDER.map((r, i) => [r, i]));

export function isRole(role: string): role is SlotRole {
  return INDEX.has(role);
}

export function roleIndex(role: string): number {
  const i = INDEX.get(role);
  if (i === undefined) throw new Error(`unknown slot role ${role}`);
  return i;
}
