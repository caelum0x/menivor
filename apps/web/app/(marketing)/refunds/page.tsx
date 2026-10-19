import type { Metadata } from "next";
import Link from "next/link";
import {
  LEGAL_CONTACT_EMAIL,
  LegalPage,
  type LegalSection,
} from "@/components/marketing/LegalPage";

export const metadata: Metadata = {
  title: "Refund Policy",
  description:
    "How refunds work for Menivor credit packs and workspace subscriptions, including failed renders and how to request a refund.",
  alternates: { canonical: "/refunds" },
};

const SECTIONS: readonly LegalSection[] = [
  {
    id: "failed-renders",
    heading: "Failed renders",
    body: (
      <p>
        If a render fails on our side, the credit it reserved is returned to
        your balance automatically — no request needed. If a render finished
        but is clearly broken (for example missing audio or corrupt video),
        email us with the job link and we will restore the credit.
      </p>
    ),
  },
  {
    id: "credit-packs",
    heading: "Credit packs",
    body: (
      <p>
        You can request a full refund of a credit pack within 14 days of
        purchase as long as none of that pack&apos;s credits have been used.
        If some credits were used, we refund the unused portion pro rata.
        Refunded credits are removed from your balance.
      </p>
    ),
  },
  {
    id: "subscriptions",
    heading: "Workspace subscriptions",
    body: (
      <>
        <p>
          You can cancel a workspace plan any time from{" "}
          <Link href="/billing">Billing</Link>. Cancellation stops the next
          renewal; the workspace keeps its plan and remaining monthly credits
          until the end of the period already paid.
        </p>
        <p>
          A first subscription payment can be refunded in full within 14 days
          if the workspace has not used any of that period&apos;s plan
          credits. Renewals are not refunded once the new period has started,
          except where required by law.
        </p>
      </>
    ),
  },
  {
    id: "consumer-rights",
    heading: "Statutory rights",
    body: (
      <p>
        Nothing in this policy limits rights you have under consumer law where
        you live. Our merchant of record (Dodo Payments, or Creem for earlier
        purchases) sold you the purchase, so their refund process also
        applies and we will coordinate with them.
      </p>
    ),
  },
  {
    id: "request",
    heading: "How to request a refund",
    body: (
      <p>
        Email <a href={`mailto:${LEGAL_CONTACT_EMAIL}?subject=Refund%20request`}>{LEGAL_CONTACT_EMAIL}</a>{" "}
        from the address on your account with the purchase date and, if you
        have it, the receipt or invoice number. We reply within 3 business
        days. Approved refunds go back to the original payment method; your
        bank may take 5–10 business days to show them.
      </p>
    ),
  },
];

export default function RefundPolicyPage() {
  return (
    <LegalPage
      kicker="Legal"
      title="Refund Policy"
      intro={
        <p>
          We want every credit you buy to turn into a reel you are happy with.
          Here is exactly when and how you can get your money back.
        </p>
      }
      sections={SECTIONS}
    />
  );
}
