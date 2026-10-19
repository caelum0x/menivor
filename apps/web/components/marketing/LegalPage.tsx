import type { ReactNode } from "react";
import Link from "next/link";

/**
 * Public support / billing / legal inbox shown on every policy page. Matches
 * the support email on our Dodo Payments brand (receipts and statements).
 */
export const LEGAL_CONTACT_EMAIL = "support@menivor.com";

/** General hello inbox (partnerships, press, anything else). */
export const GENERAL_CONTACT_EMAIL = "hello@menivor.com";

/**
 * Transparency disclosure required wherever we mention the AI models we use.
 * Shown on every legal page and in the marketing footer.
 */
export const INDEPENDENT_PRODUCT_DISCLOSURE =
  "Menivor is an independent product built on third-party AI models. It is not affiliated with or endorsed by the makers of those models.";

/** Date the current policy texts took effect (ISO yyyy-mm-dd). */
export const LEGAL_EFFECTIVE_DATE = "2026-09-23";

export interface LegalSection {
  readonly id: string;
  readonly heading: string;
  readonly body: ReactNode;
}

interface LegalPageProps {
  readonly kicker: string;
  readonly title: string;
  readonly intro: ReactNode;
  readonly sections: readonly LegalSection[];
}

const RELATED: ReadonlyArray<{ readonly href: string; readonly label: string }> = [
  { href: "/terms", label: "Terms of Service" },
  { href: "/privacy", label: "Privacy Policy" },
  { href: "/refunds", label: "Refund Policy" },
  { href: "/legal/acceptable-use", label: "Acceptable Use Policy" },
  { href: "/contact", label: "Contact" },
];

/**
 * Shared layout for the public legal pages (terms, privacy, refunds): a
 * table of contents, numbered sections with stable anchors, the effective
 * date and cross-links between the policies.
 */
export function LegalPage({ kicker, title, intro, sections }: LegalPageProps) {
  return (
    <div className="container py-16 lg:py-24">
      <div className="max-w-3xl">
        <p className="kicker text-muted-foreground">{kicker}</p>
        <h1 className="mt-4 text-display-lg font-bold">{title}</h1>
        <p className="mt-3 text-sm text-muted-foreground">
          Effective {LEGAL_EFFECTIVE_DATE}
        </p>
        <div className="mt-6 text-pretty leading-relaxed text-muted-foreground">
          {intro}
        </div>

        <nav aria-label="On this page" className="mt-10 rounded-lg border border-border p-5">
          <p className="text-sm font-medium text-foreground">On this page</p>
          <ol className="mt-3 grid gap-1.5 text-sm sm:grid-cols-2">
            {sections.map((section, index) => (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  className="text-muted-foreground transition-colors hover:text-foreground"
                >
                  {index + 1}. {section.heading}
                </a>
              </li>
            ))}
          </ol>
        </nav>

        <div className="mt-12 space-y-10">
          {sections.map((section, index) => (
            <section key={section.id} id={section.id} className="scroll-mt-24">
              <h2 className="text-xl font-semibold text-foreground">
                {index + 1}. {section.heading}
              </h2>
              <div className="mt-3 space-y-3 leading-relaxed text-muted-foreground [&_a]:text-primary [&_a]:underline [&_a]:underline-offset-4 [&_li]:ml-5 [&_ul]:list-disc [&_ul]:space-y-1.5">
                {section.body}
              </div>
            </section>
          ))}
        </div>

        <div className="mt-14 border-t border-border pt-8 text-sm text-muted-foreground">
          <p>
            Questions about this policy? Email{" "}
            <a
              href={`mailto:${LEGAL_CONTACT_EMAIL}`}
              className="font-medium text-primary underline underline-offset-4"
            >
              {LEGAL_CONTACT_EMAIL}
            </a>
            .
          </p>
          <p className="mt-3">{INDEPENDENT_PRODUCT_DISCLOSURE}</p>
          <ul className="mt-4 flex flex-wrap gap-x-6 gap-y-2">
            {RELATED.map((link) => (
              <li key={link.href}>
                <Link href={link.href} className="hover:text-foreground">
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
