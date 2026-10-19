import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

export interface RelatedLink {
  readonly href: string;
  readonly title: string;
  readonly description?: string;
}

/**
 * A grid of internal links to related comparison / alternative / tool pages.
 * Drives crawlability and internal linking so the programmatic pages reinforce
 * each other instead of being orphaned.
 */
interface RelatedLinksProps {
  readonly heading: string;
  readonly links: readonly RelatedLink[];
}

export function RelatedLinks({ heading, links }: RelatedLinksProps) {
  if (links.length === 0) return null;

  return (
    <section aria-labelledby="related-heading" className="mt-14">
      <h2
        id="related-heading"
        className="text-2xl font-bold tracking-tight sm:text-3xl"
      >
        {heading}
      </h2>
      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {links.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className="group flex items-start justify-between gap-3 rounded-md border border-border bg-card p-4 transition-colors hover:border-primary/40"
          >
            <span>
              <span className="block font-semibold text-foreground">
                {link.title}
              </span>
              {link.description ? (
                <span className="mt-1 block text-sm text-muted-foreground">
                  {link.description}
                </span>
              ) : null}
            </span>
            <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
          </Link>
        ))}
      </div>
    </section>
  );
}
