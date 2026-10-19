import type { Metadata } from "next";
import Link from "next/link";
import { CreditCard, LifeBuoy, Mail, ShieldCheck } from "lucide-react";
import { GENERAL_CONTACT_EMAIL, LEGAL_CONTACT_EMAIL } from "@/components/marketing/LegalPage";

export const metadata: Metadata = {
  title: "Contact",
  description:
    "Contact Menivor for support, billing and refunds, privacy requests, and partnerships.",
  alternates: { canonical: "/contact" },
};

interface ContactTopic {
  readonly title: string;
  readonly body: string;
  readonly subject: string;
  readonly icon: React.ComponentType<{ className?: string }>;
}

const TOPICS: readonly ContactTopic[] = [
  {
    title: "Product support",
    body: "Render problems, account access, or questions about a feature. Include the job link if it is about a specific reel.",
    subject: "Support",
    icon: LifeBuoy,
  },
  {
    title: "Billing and refunds",
    body: "Receipts, invoices, plan changes and refund requests. Send from the email on your account.",
    subject: "Billing",
    icon: CreditCard,
  },
  {
    title: "Privacy and data requests",
    body: "Access, export or deletion requests you can't complete from Privacy settings.",
    subject: "Privacy request",
    icon: ShieldCheck,
  },
  {
    title: "Sales and partnerships",
    body: "Volume pricing, Enterprise workspaces with SSO, agencies and integrations.",
    subject: "Sales",
    icon: Mail,
  },
];

export default function ContactPage() {
  return (
    <div className="container py-16 lg:py-24">
      <div className="max-w-3xl">
        <p className="kicker text-muted-foreground">Contact</p>
        <h1 className="mt-4 text-display-lg font-bold">Talk to a human</h1>
        <p className="mt-4 text-pretty text-lg leading-relaxed text-muted-foreground">
          Email{" "}
          <a
            href={`mailto:${LEGAL_CONTACT_EMAIL}`}
            className="font-medium text-primary underline underline-offset-4"
          >
            {LEGAL_CONTACT_EMAIL}
          </a>{" "}
          for support, billing and refunds, or{" "}
          <a
            href={`mailto:${GENERAL_CONTACT_EMAIL}`}
            className="font-medium text-primary underline underline-offset-4"
          >
            {GENERAL_CONTACT_EMAIL}
          </a>{" "}
          for anything else — we answer within 3 business days, usually much
          faster. Pick a topic below to pre-fill the subject.
        </p>

        <ul className="mt-10 grid gap-4 sm:grid-cols-2">
          {TOPICS.map((topic) => {
            const Icon = topic.icon;
            return (
              <li key={topic.subject}>
                <a
                  href={`mailto:${LEGAL_CONTACT_EMAIL}?subject=${encodeURIComponent(`[${topic.subject}] `)}`}
                  className="flex h-full flex-col gap-2 rounded-lg border border-border p-5 transition-colors hover:border-primary/60 hover:bg-secondary/40"
                >
                  <Icon className="size-5 text-primary" aria-hidden />
                  <span className="font-medium text-foreground">{topic.title}</span>
                  <span className="text-sm text-muted-foreground">{topic.body}</span>
                </a>
              </li>
            );
          })}
        </ul>

        <p className="mt-10 text-sm text-muted-foreground">
          See also our{" "}
          <Link href="/terms" className="underline underline-offset-4">Terms</Link>,{" "}
          <Link href="/privacy" className="underline underline-offset-4">Privacy Policy</Link>,{" "}
          <Link href="/legal/acceptable-use" className="underline underline-offset-4">Acceptable Use Policy</Link>{" "}
          and{" "}
          <Link href="/refunds" className="underline underline-offset-4">Refund Policy</Link>
          , or check live service health on the{" "}
          <Link href="/status" className="underline underline-offset-4">status page</Link>.
        </p>
      </div>
    </div>
  );
}
