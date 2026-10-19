/**
 * Source files -> copy-check text units (CLAIMS-RULES section 4.2, "source
 * files, when a rendered build is not available"): string literals and JSX
 * text only. Class names, URLs, ids and import paths are out of scope.
 *
 * Test-only helper (imports the TypeScript compiler); never bundled.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import ts from "typescript";
import type { Surface, TextUnit } from "./copy-check";

/** JSX attributes and object keys whose string values are never copy. */
const NON_COPY_NAMES = new Set([
  "className",
  "class",
  "href",
  "src",
  "poster",
  "id",
  "key",
  "slug",
  "type",
  "variant",
  "size",
  "rel",
  "target",
  "role",
  "as",
  "method",
  "name",
  "htmlFor",
  "autoComplete",
  "inputMode",
  "icon",
  "styleId",
  "layout",
  "preset",
  "format",
  "path",
  "url",
  "canonical",
  "source",
  "tone",
  "kind",
  "mode",
  "status",
  "code",
  "provider",
  "voice",
  "voice_name",
  "background_id",
  "templateId",
  "template",
  "videoSrc",
  "image",
  "asset",
  "file",
  "locale",
]);

/** Calls whose string arguments are class names or keys, not copy. */
const NON_COPY_CALLS = new Set(["cn", "clsx", "cva", "require", "fetch", "apiRequest", "t", "useTranslations"]);

function propertyName(node: ts.Node): string {
  if (ts.isIdentifier(node) || ts.isStringLiteral(node) || ts.isPrivateIdentifier(node)) return node.text;
  return "";
}

function calleeName(expr: ts.Expression): string {
  if (ts.isIdentifier(expr)) return expr.text;
  if (ts.isPropertyAccessExpression(expr)) return expr.name.text;
  return "";
}

/** True when a string literal is structural (class names, ids, keys, paths). */
function isStructural(node: ts.Node): boolean {
  const parent = node.parent;
  if (!parent) return false;
  if (ts.isImportDeclaration(parent) || ts.isExportDeclaration(parent) || ts.isImportTypeNode(parent)) return true;
  if (ts.isLiteralTypeNode(parent)) return true;
  if (ts.isElementAccessExpression(parent)) return true;
  if (ts.isJsxAttribute(parent)) return NON_COPY_NAMES.has(propertyName(parent.name as ts.Node));
  if (ts.isJsxExpression(parent) && parent.parent && ts.isJsxAttribute(parent.parent)) {
    return NON_COPY_NAMES.has(propertyName(parent.parent.name as ts.Node));
  }
  if (ts.isPropertyAssignment(parent)) {
    if (parent.name === node) return true;
    return NON_COPY_NAMES.has(propertyName(parent.name));
  }
  if (ts.isCallExpression(parent)) return NON_COPY_CALLS.has(calleeName(parent.expression));
  if (ts.isBinaryExpression(parent)) {
    const op = parent.operatorToken.kind;
    return (
      op === ts.SyntaxKind.EqualsEqualsEqualsToken ||
      op === ts.SyntaxKind.ExclamationEqualsEqualsToken ||
      op === ts.SyntaxKind.EqualsEqualsToken ||
      op === ts.SyntaxKind.ExclamationEqualsToken
    );
  }
  if (ts.isCaseClause(parent)) return true;
  if (ts.isArrayLiteralExpression(parent)) {
    // Arrays of ids (["a", "b"]) are structural when every element is an id.
    return parent.elements.every((el) => ts.isStringLiteral(el) && /^[a-z0-9_:\-./]+$/.test(el.text));
  }
  return false;
}

export interface SourceScan {
  readonly units: TextUnit[];
  /** String literals that look like i18n keys (`pricing.intro`). */
  readonly keys: string[];
}

/** String literals + JSX text of one file, with the raw line above as context. */
export function sourceUnits(code: string, file: string, surface: Surface = "marketing"): SourceScan {
  const sf = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const lines = code.split("\n");
  const units: TextUnit[] = [];
  const keys: string[] = [];
  const push = (node: ts.Node, text: string) => {
    const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line;
    units.push({ text, path: file, surface, context: `${lines[line - 1] ?? ""}\n${lines[line] ?? ""}` });
  };
  const visit = (node: ts.Node) => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      if (/^[a-z][a-zA-Z]*(\.[a-zA-Z0-9]+)+$/.test(node.text)) keys.push(node.text);
      if (!isStructural(node)) push(node, node.text);
    } else if (ts.isTemplateExpression(node)) {
      if (!isStructural(node)) {
        push(node, [node.head.text, ...node.templateSpans.map((span) => span.literal.text)].join(" "));
      }
    } else if (ts.isJsxText(node)) {
      if (node.text.trim()) push(node, node.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return { units, keys };
}

/** Resolve `@/x`, `./x` and `../x` imports to files inside `root`. */
function resolveImport(spec: string, fromFile: string, root: string): string | null {
  let base: string;
  if (spec.startsWith("@/")) base = path.join(root, spec.slice(2));
  else if (spec.startsWith(".")) base = path.resolve(path.dirname(fromFile), spec);
  else return null;
  for (const candidate of [base, `${base}.tsx`, `${base}.ts`, path.join(base, "index.tsx"), path.join(base, "index.ts")]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  return null;
}

function importsOf(code: string, file: string): string[] {
  const sf = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const out: string[] = [];
  sf.forEachChild((node) => {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier) {
      if (ts.isImportDeclaration(node) && node.importClause?.isTypeOnly) return;
      if (ts.isStringLiteral(node.moduleSpecifier)) out.push(node.moduleSpecifier.text);
    }
  });
  return out;
}

/**
 * Every first-party source file reachable from `entries` by static import,
 * skipping files for which `exclude` returns true (tests, API transport...).
 */
export function reachableFiles(
  entries: readonly string[],
  root: string,
  exclude: (relative: string) => boolean,
): string[] {
  const seen = new Set<string>();
  const queue = entries.map((entry) => path.resolve(root, entry));
  while (queue.length) {
    const file = queue.shift()!;
    if (seen.has(file)) continue;
    const rel = path.relative(root, file);
    if (exclude(rel)) continue;
    seen.add(file);
    const code = fs.readFileSync(file, "utf8");
    for (const spec of importsOf(code, file)) {
      const target = resolveImport(spec, file, root);
      if (target && !seen.has(target)) queue.push(target);
    }
  }
  return [...seen].map((file) => path.relative(root, file)).sort();
}
