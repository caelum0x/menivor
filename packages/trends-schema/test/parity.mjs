/**
 * TS≡Python parity — compiled TS scoring must reproduce every golden score +
 * ad_safe fixture from the Python port. Requires `npm run build` first.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const { score, adSafe } = await import(join(here, "..", "dist", "index.js"));

const golden = JSON.parse(
  readFileSync(join(here, "fixtures", "golden", "scores.json"), "utf8"),
);

let failures = 0;
let checked = 0;
for (const [name, case_] of Object.entries(golden.scores)) {
  const got = score(case_.series);
  for (const k of Object.keys(case_.score)) {
    checked++;
    if (got[k] !== case_.score[k]) {
      failures++;
      console.error(`MISMATCH scores.${name}.${k}: TS ${got[k]} != PY ${case_.score[k]}`);
    }
  }
}
for (const [name, case_] of Object.entries(golden.ad_safe)) {
  checked++;
  if (adSafe(case_.sound) !== case_.ad_safe) {
    failures++;
    console.error(`MISMATCH ad_safe.${name}: TS ${adSafe(case_.sound)} != PY ${case_.ad_safe}`);
  }
}

if (failures) {
  console.error(`\ntrends-schema parity FAILED: ${failures}/${checked} values differ`);
  process.exit(1);
}
console.log(`trends-schema TS≡Python parity OK (${checked} values)`);
