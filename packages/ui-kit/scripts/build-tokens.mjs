/** Emit the framework-free tokens.json from the built TS tokens (the source of
 * truth), so mobile + the Rust/GPUI desktop theme re-map ONE palette. */
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const here = dirname(fileURLToPath(import.meta.url));
const t = await import(join(here, "..", "dist", "tokens", "index.js"));
const out = {
  colors: t.colors, platformColors: t.platformColors,
  spacing: t.spacing, radii: t.radii,
  fontSizes: t.fontSizes, fontWeights: t.fontWeights, zIndex: t.zIndex,
};
const dest = join(here, "..", "src", "tokens", "tokens.json");
writeFileSync(dest, JSON.stringify(out, null, 2) + "\n");
console.log("wrote", dest, "with", Object.keys(out.colors).length, "colors");
