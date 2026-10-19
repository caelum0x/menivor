/** TS≡Python parity — compiled TS templates (incl. FNV-1a hash) must match golden. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const m = await import(join(here, "..", "dist", "index.js"));
const golden = JSON.parse(readFileSync(join(here, "fixtures", "golden", "templates.json"), "utf8"));

function canon(v) {
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(",")}}`;
  return JSON.stringify(v);
}
let failures = 0, checked = 0;
const check = (label, got, want) => { checked++; if (canon(got) !== canon(want)) { failures++; console.error(`MISMATCH ${label}\n  TS ${canon(got)}\n  PY ${canon(want)}`); } };

check("role_order", [...m.ROLE_ORDER], golden.role_order);
for (const [slug, c] of Object.entries(golden.presets)) {
  const t = m.getPreset(slug);
  check(`${slug}.template`, t, c.template);
  check(`${slug}.hash`, m.contentHash(t), c.hash);
  check(`${slug}.valid`, m.validateTemplate(t).length === 0, c.valid);
}
if (failures) { console.error(`\nshot-template-schema parity FAILED: ${failures}/${checked}`); process.exit(1); }
console.log(`shot-template-schema TS≡Python parity OK (${checked} cases incl. FNV-1a hashes)`);
