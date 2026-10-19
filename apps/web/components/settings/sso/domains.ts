/**
 * Parsing helpers for the multi-value security-policy fields (allowed email
 * domains, IP allowlist). The UI edits them as free text (one entry per line or
 * comma-separated); these normalize to/from the API's `string[]` shape. Pure and
 * side-effect free so they are trivially unit-testable.
 */

/**
 * Split free-form text into a de-duplicated, trimmed list of entries. Accepts
 * newline- OR comma-separated input; blank lines and surrounding whitespace are
 * dropped. Order is preserved (first occurrence wins) so the list reads as typed.
 */
export function parseList(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/[\n,]/)) {
    const value = raw.trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

/** Render a `string[]` back into newline-separated text for a textarea. */
export function formatList(values: readonly string[] | null | undefined): string {
  return (values ?? []).join("\n");
}
