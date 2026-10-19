import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { Crumb } from "@/lib/seo";

/**
 * Visible breadcrumb trail for the programmatic pages. Pairs with the
 * BreadcrumbList JSON-LD emitted separately so the same hierarchy is exposed to
 * both users and crawlers. The final crumb is the current page (not a link).
 */
interface BreadcrumbsProps {
  readonly crumbs: readonly Crumb[];
}

export function Breadcrumbs({ crumbs }: BreadcrumbsProps) {
  return (
    <nav aria-label="Breadcrumb" className="mb-6">
      <ol className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
        {crumbs.map((crumb, index) => {
          const isLast = index === crumbs.length - 1;
          return (
            <li key={crumb.path} className="flex items-center gap-1.5">
              {isLast ? (
                <span aria-current="page" className="text-foreground">
                  {crumb.name}
                </span>
              ) : (
                <>
                  <Link
                    href={crumb.path}
                    className="transition-colors hover:text-foreground"
                  >
                    {crumb.name}
                  </Link>
                  <ChevronRight className="size-3.5 shrink-0 opacity-60" />
                </>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
