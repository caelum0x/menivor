/**
 * Deterministic workflow pinning (mirror of `pin.py`). FNV-1a-32 over the
 * canonical identity — byte-identical to the Python port.
 */

export interface InputSlot {
  name: string;
  type: "int" | "string" | "image" | "video" | "audio";
  default?: number | string;
  required?: boolean;
  min?: number;
  max?: number;
}

export interface WorkflowDescriptor {
  slug: string;
  category: string;
  description: string;
  node_commits: Record<string, string>;
  weight_refs: string[];
  inputs: InputSlot[];
}

function canon(d: WorkflowDescriptor): string {
  const commits = Object.keys(d.node_commits)
    .sort()
    .map((k) => `${k}=${d.node_commits[k]}`)
    .join(";");
  const weights = [...(d.weight_refs ?? [])].sort().join(",");
  const inputs = (d.inputs ?? [])
    .map((s) => `${s.name}:${s.type}:${s.default ?? ""}:${s.required ? 1 : 0}`)
    .join(";");
  return `${d.slug}|${d.category}|${commits}|${weights}|${inputs}`;
}

/** FNV-1a-32 hex pin of a workflow descriptor. */
export function graphHash(d: WorkflowDescriptor): string {
  let h = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(canon(d))) {
    h ^= byte;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

/** Validate submitted values against the workflow's input contract. */
export function validateInputs(
  d: WorkflowDescriptor,
  values: Record<string, unknown>,
): string[] {
  const errors: string[] = [];
  for (const slot of d.inputs ?? []) {
    const present = Object.prototype.hasOwnProperty.call(values, slot.name);
    if (slot.required && !present) {
      errors.push(`missing required input '${slot.name}'`);
      continue;
    }
    if (!present) continue;
    const v = values[slot.name];
    if (slot.type === "int") {
      if (typeof v !== "number" || !Number.isInteger(v)) {
        errors.push(`input '${slot.name}' must be an int`);
        continue;
      }
      if (slot.min !== undefined && v < slot.min) errors.push(`input '${slot.name}' below min ${slot.min}`);
      if (slot.max !== undefined && v > slot.max) errors.push(`input '${slot.name}' above max ${slot.max}`);
    } else if (slot.type === "string" && typeof v !== "string") {
      errors.push(`input '${slot.name}' must be a string`);
    }
  }
  return errors;
}
