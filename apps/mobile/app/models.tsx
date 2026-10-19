/** Route: /models — alias of the canonical Model Catalog: compare, detail, estimate (/catalog/model-catalog). */
import { Redirect } from "expo-router";

export default function LegacyRouteRedirect() {
  return <Redirect href="/catalog/model-catalog" />;
}
