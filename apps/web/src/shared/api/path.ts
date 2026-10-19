/**
 * Tagged template for API paths: every interpolated value is URI-encoded.
 *
 *   apiPath`/actors/${actorId}/face`  ->  "/actors/<encoded id>/face"
 *
 * Writing the path as one template literal (no calls inside `${}`) also keeps it
 * readable for the API-surface audit (apps/api/tools/ops/api_surface_audit.py),
 * which allowlists routes from the path literals the clients contain.
 */
export function apiPath(strings: TemplateStringsArray, ...values: (string | number)[]): string {
  return strings.reduce(
    (out, part, i) => out + part + (i < values.length ? encodeURIComponent(String(values[i])) : ""),
    "",
  );
}
