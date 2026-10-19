/** TS≡Python parity — compiled TS metadata must match the golden. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const m = await import(join(here, "..", "dist", "index.js"));
const golden = JSON.parse(readFileSync(join(here, "fixtures", "golden", "adapter.json"), "utf8"));

function canon(v) {
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(",")}}`;
  return JSON.stringify(v);
}
let failures = 0, checked = 0;
const check = (label, got, want) => { checked++; if (canon(got) !== canon(want)) { failures++; console.error(`MISMATCH ${label}: TS ${canon(got)} != PY ${canon(want)}`); } };

for (const [mm, cls] of Object.entries(golden.license)) check(`license.${mm}`, m.licenseClass(mm), cls);
for (const [mm, ok] of Object.entries(golden.paid)) check(`paid.${mm}`, m.canUseForPaid(mm), ok);
for (const [mm, byDate] of Object.entries(golden.deprecation)) for (const [d, hint] of Object.entries(byDate)) check(`migrate.${mm}.${d}`, m.migrate(mm, d), hint);
for (const [raw, exp] of Object.entries(golden.envelope)) { check(`state.${raw}`, m.normalizeState(raw), exp.state); check(`terminal.${raw}`, m.isTerminal(m.normalizeState(raw)), exp.terminal); }
check("usage.ok", m.normalizedUsage(5.0, 420000, true), golden.usage.ok);
check("usage.fail", m.normalizedUsage(5.0, 420000, false), golden.usage.fail);

if (failures) { console.error(`\nprovider-adapter-kit parity FAILED: ${failures}/${checked}`); process.exit(1); }
console.log(`provider-adapter-kit TS≡Python parity OK (${checked} cases)`);
