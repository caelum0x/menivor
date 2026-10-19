import type { FaqEntry } from "@/lib/seo";

/**
 * Renders a page's FAQ as accessible, always-expanded content (good for both
 * readers and crawlers). The same entries are emitted as FAQPage JSON-LD by the
 * page, so the on-page copy and the structured data always match.
 */
interface FaqSectionProps {
  readonly faqs: readonly FaqEntry[];
  readonly heading?: string;
}

export function FaqSection({
  faqs,
  heading = "Frequently asked questions",
}: FaqSectionProps) {
  if (faqs.length === 0) return null;

  return (
    <section aria-labelledby="faq-heading" className="mt-14">
      <h2
        id="faq-heading"
        className="text-2xl font-bold tracking-tight sm:text-3xl"
      >
        {heading}
      </h2>
      <dl className="glass-subtle mt-6 divide-y divide-white/[0.07] rounded-2xl">
        {faqs.map((faq) => (
          <div key={faq.question} className="p-5">
            <dt className="font-semibold text-foreground">{faq.question}</dt>
            <dd className="mt-2 text-pretty text-muted-foreground">
              {faq.answer}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
