/** TS≡Python parity — compiled TS descriptors/pins/validation must match golden. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const m = await import(join(here, "..", "dist", "index.js"));
const golden = JSON.parse(readFileSync(join(here, "fixtures", "golden", "workflows.json"), "utf8"));

function canon(v) {
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(",")}}`;
  return JSON.stringify(v);
}
let failures = 0, checked = 0;
const check = (label, got, want) => { checked++; if (canon(got) !== canon(want)) { failures++; console.error(`MISMATCH ${label}\n  TS ${canon(got)}\n  PY ${canon(want)}`); } };

for (const [slug, c] of Object.entries(golden.workflows)) {
  const w = m.getWorkflow(slug);
  check(`${slug}.descriptor`, w, c.descriptor);
  check(`${slug}.hash`, m.graphHash(w), c.hash);
}
for (const [name, c] of Object.entries(golden.validation)) {
  check(`validate.${name}`, m.validateInputs(m.getWorkflow(c.slug), c.values), c.errors);
}
if (failures) { console.error(`\ncomfy-workflow-schema parity FAILED: ${failures}/${checked}`); process.exit(1); }
console.log(`comfy-workflow-schema TS≡Python parity OK (${checked} cases incl. FNV-1a pins)`);
