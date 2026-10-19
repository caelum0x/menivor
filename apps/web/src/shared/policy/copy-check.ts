/**
 * Claims-rules copy check (gtm/policy/CLAIMS-RULES.md section 4), shared by
 * the marketing copy test and the live-page check.
 *
 * The rules live in `policy/copy-denylist.json` at the repo root, vendored
 * verbatim from `gtm/policy/copy-denylist.json`. This module is the matcher:
 * normalise a text unit, apply product/surface/path/flag filters, strip
 * except tokens, match, then honour `copy-source` escapes. Pure; no I/O.
 */

export type Surface = "marketing" | "app-ui" | "outbound" | "docs" | "api-public" | "legal";
export type Severity = "error" | "warn";

export interface DenyRule {
  readonly id: string;
  readonly category?: string;
  readonly products: readonly string[];
  readonly surfaces: readonly Surface[];
  readonly match:
    | { readonly type: "regex"; readonly value: string; readonly caseSensitive?: boolean }
    | { readonly type: "codepoints"; readonly ranges: readonly (readonly [string, string])[] };
  readonly severity?: Severity;
  readonly sourceEscape?: boolean;
  readonly unlessFlags?: readonly string[];
  readonly allowPaths?: readonly string[];
  readonly exceptTokens?: readonly string[];
  readonly examples?: { readonly hit?: readonly string[]; readonly miss?: readonly string[] };
}

export interface Denylist {
  readonly version: string;
  readonly defaults?: { readonly caseSensitive?: boolean; readonly severity?: Severity; readonly sourceEscape?: boolean };
  readonly rules: readonly DenyRule[];
}

export interface TextUnit {
  /** The raw text (one text node, one string literal, one JSON string). */
  readonly text: string;
  /** Repo-relative file path or page URL path the unit came from. */
  readonly path: string;
  readonly surface: Surface;
  /** Raw text of the line directly above (source) or the element's attributes (HTML). */
  readonly context?: string;
}

export interface CopyHit {
  readonly ruleId: string;
  readonly severity: Severity;
  readonly path: string;
  /** Up to 60 characters around the hit; empty for secret-surface rules. */
  readonly excerpt: string;
}

export const PRODUCT = "menivor";

/** Step 1: straight quotes, normal spaces, collapsed whitespace. */
export function normalizeUnit(text: string): string {
  return text
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** `**` crosses folders, `*` stays inside one segment. */
export function globToRegExp(glob: string): RegExp {
  let out = "";
  for (let i = 0; i < glob.length; i += 1) {
    const ch = glob[i]!;
    if (ch === "*" && glob[i + 1] === "*") {
      out += ".*";
      i += 1;
      if (glob[i + 1] === "/") i += 1;
    } else if (ch === "*") {
      out += "[^/]*";
    } else {
      out += escapeRegExp(ch);
    }
  }
  return new RegExp(`^${out}$`);
}

function pathAllowed(rule: DenyRule, path: string): boolean {
  const clean = path.replace(/^\.?\//, "");
  return (rule.allowPaths ?? []).some((glob) => {
    const re = globToRegExp(glob);
    return re.test(clean) || re.test(`/${clean}`) || re.test(`${clean}/`) || re.test(`/${clean}/`);
  });
}

const SOURCE_ESCAPE = /copy-source:\s*\S|data-copy-source="[^"]+"/;

/** Step 6 only (after except tokens): does the text hit the rule's matcher? */
export function matchRule(rule: DenyRule, text: string, defaults: Denylist["defaults"] = {}): RegExpExecArray | null {
  let unit = text;
  for (const token of rule.exceptTokens ?? []) {
    unit = unit.replace(new RegExp(escapeRegExp(token), "gi"), " ");
  }
  if (rule.match.type === "regex") {
    const caseSensitive = rule.match.caseSensitive ?? defaults?.caseSensitive ?? false;
    return new RegExp(rule.match.value, caseSensitive ? "" : "i").exec(unit);
  }
  const ranges = rule.match.ranges.map(([lo, hi]) => [parseInt(lo, 16), parseInt(hi, 16)] as const);
  let index = 0;
  for (const ch of unit) {
    const code = ch.codePointAt(0)!;
    if (ranges.some(([lo, hi]) => code >= lo && code <= hi)) {
      const found = [ch] as unknown as RegExpExecArray;
      found.index = index;
      return found;
    }
    index += ch.length;
  }
  return null;
}

export interface CheckOptions {
  readonly product?: string;
  /** Real product flags (e.g. PRESENTER_LIVE) as read from the product config. */
  readonly flags?: Readonly<Record<string, string | boolean | undefined>>;
}

function flagOn(value: string | boolean | undefined): boolean {
  if (typeof value === "boolean") return value;
  return value === "1" || String(value ?? "").toLowerCase() === "true";
}

/** Run every applicable rule over one unit (steps 1-8). */
export function checkUnit(list: Denylist, unit: TextUnit, options: CheckOptions = {}): CopyHit[] {
  const product = options.product ?? PRODUCT;
  const normalized = normalizeUnit(unit.text);
  if (!normalized) return [];
  const hits: CopyHit[] = [];
  for (const rule of list.rules) {
    if (!rule.products.includes(product) || !rule.surfaces.includes(unit.surface)) continue;
    if (pathAllowed(rule, unit.path)) continue;
    if ((rule.unlessFlags ?? []).some((flag) => flagOn(options.flags?.[flag]))) continue;
    const found = matchRule(rule, normalized, list.defaults);
    if (!found) continue;
    const escape = rule.sourceEscape ?? list.defaults?.sourceEscape ?? false;
    if (escape && (SOURCE_ESCAPE.test(unit.text) || SOURCE_ESCAPE.test(unit.context ?? ""))) continue;
    const start = Math.max(0, (found.index ?? 0) - 20);
    hits.push({
      ruleId: rule.id,
      severity: rule.severity ?? list.defaults?.severity ?? "error",
      path: unit.path,
      excerpt: rule.category === "secret-surface" ? "" : normalized.slice(start, start + 60),
    });
  }
  return hits;
}

export function checkUnits(list: Denylist, units: readonly TextUnit[], options: CheckOptions = {}): CopyHit[] {
  return units.flatMap((unit) => checkUnit(list, unit, options));
}

/** Section 4.6: every example of every rule for this product behaves as labelled. */
export function selfTest(list: Denylist, product: string = PRODUCT): string[] {
  const failures: string[] = [];
  for (const rule of list.rules) {
    if (!rule.products.includes(product)) continue;
    for (const example of rule.examples?.hit ?? []) {
      const escaped = (rule.sourceEscape ?? list.defaults?.sourceEscape) && SOURCE_ESCAPE.test(example);
      if (!matchRule(rule, normalizeUnit(example), list.defaults) || escaped) {
        failures.push(`${rule.id}: expected a hit for ${JSON.stringify(example)}`);
      }
    }
    for (const example of rule.examples?.miss ?? []) {
      const escaped = (rule.sourceEscape ?? list.defaults?.sourceEscape) && SOURCE_ESCAPE.test(example);
      if (matchRule(rule, normalizeUnit(example), list.defaults) && !escaped) {
        failures.push(`${rule.id}: expected no hit for ${JSON.stringify(example)}`);
      }
    }
  }
  return failures;
}

// --------------------------------------------------------------------------- //
// Rendered HTML -> text units (section 4.2)
// --------------------------------------------------------------------------- //

const SCANNED_ATTRS = ["alt", "aria-label", "placeholder", "title"];

function decodeEntities(text: string): string {
  return text
    .replace(/&#x([0-9a-f]+);/gi, (_, hex: string) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec: string) => String.fromCodePoint(Number(dec)))
    .replace(/&quot;/g, '"')
    .replace(/&apos;|&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&");
}

function attributes(tag: string): Record<string, string> {
  const out: Record<string, string> = {};
  const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*("([^"]*)"|'([^']*)')/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(tag)) !== null) out[m[1]!.toLowerCase()] = decodeEntities(m[3] ?? m[4] ?? "");
  return out;
}

/**
 * Visible text nodes plus title, meta description, og and twitter content,
 * alt, aria-label and placeholder. Not script, style, class names or URLs.
 */
export function htmlUnits(html: string, path: string, surface: Surface = "marketing"): TextUnit[] {
  const units: TextUnit[] = [];
  const stripped = html
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<(script|style|noscript|template)\b[\s\S]*?<\/\1\s*>/gi, "");
  const re = /<[^>]+>|[^<]+/g;
  let lastTag = "";
  let m: RegExpExecArray | null;
  while ((m = re.exec(stripped)) !== null) {
    const token = m[0];
    if (token.startsWith("<")) {
      lastTag = token;
      if (token.startsWith("</")) continue;
      const attrs = attributes(token);
      for (const name of SCANNED_ATTRS) {
        if (attrs[name]) units.push({ text: attrs[name]!, path, surface, context: token });
      }
      if (/^<meta\b/i.test(token)) {
        const key = (attrs.name ?? attrs.property ?? "").toLowerCase();
        if ((key === "description" || key.startsWith("og:") || key.startsWith("twitter:")) && attrs.content) {
          if (!/^(og|twitter):(image|url|type|card|site|locale)/.test(key)) {
            units.push({ text: attrs.content, path, surface, context: token });
          }
        }
      }
      continue;
    }
    const text = decodeEntities(token);
    if (text.trim()) units.push({ text, path, surface, context: lastTag });
  }
  return units;
}
