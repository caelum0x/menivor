import { CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { CopyButton } from "@/components/marketing/free-tools/shared";
import type { AuditResult, CheckStatus, PackagingCheck } from "@/src/features/app-audit/api";

function scoreVariant(score: number): "success" | "default" | "destructive" {
  if (score >= 80) return "success";
  if (score >= 50) return "default";
  return "destructive";
}

function StatusIcon({ status }: { readonly status: CheckStatus }) {
  if (status === "pass") return <CheckCircle2 className="size-5 shrink-0 text-success" aria-hidden />;
  if (status === "warn") return <AlertTriangle className="size-5 shrink-0 text-amber-500" aria-hidden />;
  return <XCircle className="size-5 shrink-0 text-destructive" aria-hidden />;
}

function CheckRow({ check }: { readonly check: PackagingCheck }) {
  return (
    <li className="flex items-start gap-3 rounded-md border border-border px-3 py-2.5">
      <StatusIcon status={check.status} />
      <div>
        <p className="font-medium">
          {check.label}
          {check.heuristic ? <span className="ml-2 text-xs font-normal text-muted-foreground">(heuristic)</span> : null}
        </p>
        <p className="mt-0.5 text-sm text-muted-foreground">{check.why}</p>
      </div>
    </li>
  );
}

/** The 5-point packaging score + checklist. Shared by the hero preview and both /tools pages. */
export function PackagingScoreView({ result }: { readonly result: AuditResult }) {
  const { packaging_score: score, listing } = result;
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">Packaging score</p>
          <p className="text-4xl font-bold tracking-tight">{score.score}<span className="text-lg text-muted-foreground">/100</span></p>
        </div>
        <Badge variant={scoreVariant(score.score)}>
          {listing.title || "This listing"} · {listing.store === "app_store" ? "App Store" : "Google Play"}
        </Badge>
      </div>
      <ul className="mt-4 space-y-2">
        {score.checks.map((check) => (
          <CheckRow key={check.id} check={check} />
        ))}
      </ul>
    </div>
  );
}

export function ListingFacts({ result }: { readonly result: AuditResult }) {
  const { listing } = result;
  return (
    <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
      <div><dt className="text-muted-foreground">Rating</dt><dd>{listing.rating ? `${listing.rating} (${listing.rating_count ?? 0})` : "No ratings yet"}</dd></div>
      <div><dt className="text-muted-foreground">Price</dt><dd>{listing.price_label || "—"}</dd></div>
      <div><dt className="text-muted-foreground">Screenshots</dt><dd>{listing.screenshot_count}</dd></div>
      <div><dt className="text-muted-foreground">Description length</dt><dd>{listing.description_length} chars</dd></div>
      <div><dt className="text-muted-foreground">Category</dt><dd>{listing.genre || "—"}</dd></div>
      <div><dt className="text-muted-foreground">Last updated</dt><dd>{listing.last_updated ? new Date(listing.last_updated).toLocaleDateString() : "Not available"}</dd></div>
      <div><dt className="text-muted-foreground">Subtitle</dt><dd>{listing.subtitle_available ? listing.subtitle : "Not public via this data source"}</dd></div>
      <div><dt className="text-muted-foreground">Developer</dt><dd>{listing.developer || "—"}</dd></div>
    </dl>
  );
}

/** Keyword-rank table + top competitors. Shared by the hero preview and both /tools pages. */
export function SearchVisibilityView({ result }: { readonly result: AuditResult }) {
  const visibility = result.search_visibility;
  if (!visibility.available) {
    return (
      <p className="mt-5 rounded-md border border-border bg-muted/30 px-3 py-2.5 text-sm text-muted-foreground">
        {visibility.reason}
      </p>
    );
  }
  return (
    <div className="mt-5">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-base font-semibold">
          Search visibility (top 50, {visibility.terms.length} terms{visibility.cached ? ", cached" : ""})
        </h3>
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[420px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="py-1.5 pr-3 font-medium">Term</th>
              <th className="py-1.5 pr-3 font-medium">Position</th>
              <th className="py-1.5 font-medium">Checked</th>
            </tr>
          </thead>
          <tbody>
            {visibility.results.map((row) => (
              <tr key={row.term} className="border-b border-border/60">
                <td className="py-1.5 pr-3">{row.term}</td>
                <td className="py-1.5 pr-3">{row.position ? `#${row.position}` : "not in top 50"}</td>
                <td className="py-1.5 text-muted-foreground">{row.checked_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {visibility.top_competitors.length > 0 ? (
        <div className="mt-4">
          <p className="text-sm font-medium">Top competitors across these terms</p>
          <ol className="mt-1.5 space-y-1 text-sm text-muted-foreground">
            {visibility.top_competitors.map((c, index) => (
              <li key={c.app_id}>{index + 1}. {c.title} — appears in {c.count} of {visibility.terms.length} terms</li>
            ))}
          </ol>
        </div>
      ) : null}
      {visibility.errors.length > 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">Some terms could not be checked: {visibility.errors.join("; ")}</p>
      ) : null}
    </div>
  );
}

/** The exact rewrite suggestion (promo text + subtitle), with copy buttons. */
export function RewriteView({ result }: { readonly result: AuditResult }) {
  const { rewrite } = result;
  return (
    <div className="mt-5 space-y-3">
      <h3 className="text-base font-semibold">
        Rewrite suggestion
        <span className="ml-2 text-xs font-normal text-muted-foreground">
          {rewrite.source === "relay" ? "written by Menivor's AI from this listing's own facts" : "built from this listing's own text (AI writer unavailable right now)"}
        </span>
      </h3>
      <div className="rounded-md border border-border px-3 py-2.5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-xs text-muted-foreground">Subtitle ({rewrite.subtitle.length}/30)</p>
            <p className="font-medium">{rewrite.subtitle}</p>
          </div>
          <CopyButton text={rewrite.subtitle} />
        </div>
      </div>
      <div className="rounded-md border border-border px-3 py-2.5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-xs text-muted-foreground">Promo text ({rewrite.promo_text.length}/170)</p>
            <p className="font-medium">{rewrite.promo_text}</p>
          </div>
          <CopyButton text={rewrite.promo_text} />
        </div>
      </div>
    </div>
  );
}

/** The full audit: score, listing facts, visibility and rewrite, in one card. */
export function FullAuditView({ result }: { readonly result: AuditResult }) {
  return (
    <div>
      <PackagingScoreView result={result} />
      <ListingFacts result={result} />
      <SearchVisibilityView result={result} />
      <RewriteView result={result} />
    </div>
  );
}
