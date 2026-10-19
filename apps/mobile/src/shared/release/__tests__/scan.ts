import fs from "node:fs";
import path from "node:path";

import { normalizeRoute } from "../surface";

export const ROOT = path.resolve(__dirname, "../../../..");

export function walk(dir: string, out: string[] = []): string[] {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) {
      if (name !== "node_modules" && name !== "__tests__") walk(full, out);
    } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      out.push(full);
    }
  }
  return out;
}

/** Every screen file under app/ (layouts excluded). */
export function screenFiles(): string[] {
  return walk(path.join(ROOT, "app")).filter((file) => !file.endsWith("_layout.tsx"));
}

/** Route path for an app/ screen file, e.g. app/(tabs)/me.tsx -> /me. */
export function routeForFile(file: string): string {
  const rel = path.relative(path.join(ROOT, "app"), file).replace(/\.tsx?$/, "");
  return normalizeRoute(`/${rel}`);
}

const ROUTE_LITERAL =
  /(?:push|replace|navigate|href=|href:|route:)\s*\(?\s*\{?\s*(?:pathname:\s*)?["`](\/[^"`?$]*)/g;

/** Internal route literals used for navigation in a source file. */
export function routeLiterals(source: string): string[] {
  const found: string[] = [];
  for (const match of source.matchAll(ROUTE_LITERAL)) {
    const raw = match[1] ?? "";
    found.push(raw.endsWith("/") ? `${raw}x` : raw);
  }
  return found;
}

/** True when `route` names a real screen under app/. */
export function isKnownScreen(route: string, screens: readonly string[]): boolean {
  const segments = normalizeRoute(route).split("/").filter(Boolean);
  return screens.some((screen) => {
    const parts = screen.split("/").filter(Boolean);
    return (
      parts.length === segments.length &&
      parts.every((part, i) => part.startsWith("[") || part === segments[i])
    );
  });
}
