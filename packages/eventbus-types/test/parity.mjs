/** TS≡Python parity — compiled TS catalog/envelopes must match the golden. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const m = await import(join(here, "..", "dist", "index.js"));
const golden = JSON.parse(readFileSync(join(here, "fixtures", "golden", "events.json"), "utf8"));

function canon(v) {
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(",")}}`;
  return JSON.stringify(v);
}
let failures = 0, checked = 0;
const check = (label, got, want) => { checked++; if (canon(got) !== canon(want)) { failures++; console.error(`MISMATCH ${label}`); } };

check("event_types", [...m.EVENT_TYPES], golden.event_types);
check("push_map", m.PUSH_MAP, golden.push_map);
for (const [et, env] of Object.entries(golden.envelopes)) {
  check(`envelope.${et}`, m.makeEnvelope(et, env.payload, { id: env.id, occurred_at: env.occurred_at, workspace_id: env.workspace_id, dedupe_key: env.dedupe_key }), env);
}
if (failures) { console.error(`\neventbus-types parity FAILED: ${failures}/${checked}`); process.exit(1); }
console.log(`eventbus-types TS≡Python parity OK (${checked} cases)`);
