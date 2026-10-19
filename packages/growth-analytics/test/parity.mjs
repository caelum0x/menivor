/**
 * TS≡Python parity — compiled TS analytics must reproduce every golden fixture
 * from the Python port. Requires `npm run build` first.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const m = await import(join(here, "..", "dist", "index.js"));
const golden = JSON.parse(
  readFileSync(join(here, "fixtures", "golden", "analytics.json"), "utf8"),
);

let failures = 0;
let checked = 0;
// Canonical (key-sorted) stringify so comparison ignores object key order.
function canon(v) {
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  if (v && typeof v === "object") {
    return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(",")}}`;
  }
  return JSON.stringify(v);
}
const eq = (a, b) => canon(a) === canon(b);
const check = (label, got, want) => {
  checked++;
  if (!eq(got, want)) {
    failures++;
    console.error(`MISMATCH ${label}:\n  TS: ${JSON.stringify(got)}\n  PY: ${JSON.stringify(want)}`);
  }
};

for (const [n, c] of Object.entries(golden.retention)) check(`retention.${n}`, m.normalizeCurve(c.samples), c.curve);
for (const [n, c] of Object.entries(golden.reach)) check(`reach.${n}`, m.reachTier(c.avg), c.tier);
for (const [n, c] of Object.entries(golden.dropoff)) check(`dropoff.${n}`, m.dropoff(c.curve), c.dropoff);
for (const [n, c] of Object.entries(golden.hook)) check(`hook.${n}`, m.hookScore(c.signals), c.result);
for (const [n, c] of Object.entries(golden.ab)) check(`ab.${n}`, m.selectWinner(c.variants), c.result);

if (failures) {
  console.error(`\ngrowth-analytics parity FAILED: ${failures}/${checked} cases differ`);
  process.exit(1);
}
console.log(`growth-analytics TS≡Python parity OK (${checked} cases)`);
