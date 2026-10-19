/**
 * TS≡Python parity — compiled TS `buildFiltergraph` must reproduce every golden
 * spec→filtergraph fixture from the Python port. Requires `npm run build` first.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const { buildFiltergraph } = await import(join(here, "..", "dist", "index.js"));

const golden = JSON.parse(
  readFileSync(join(here, "fixtures", "golden", "filtergraphs.json"), "utf8"),
);

let failures = 0;
let checked = 0;
for (const [name, case_] of Object.entries(golden)) {
  const got = buildFiltergraph(case_.spec);
  checked++;
  if (got !== case_.filtergraph) {
    failures++;
    console.error(`MISMATCH ${name}:\n  TS: ${got}\n  PY: ${case_.filtergraph}`);
  }
}

if (failures) {
  console.error(`\nrender-core parity FAILED: ${failures}/${checked} cases differ`);
  process.exit(1);
}
console.log(`render-core TS≡Python parity OK (${checked} spec→filtergraph fixtures)`);
