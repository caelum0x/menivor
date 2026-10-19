import type { Metadata } from "next";
import Link from "next/link";
import {
  LEGAL_CONTACT_EMAIL,
  LegalPage,
  type LegalSection,
} from "@/components/marketing/LegalPage";
import { EXPORT_LINK_MINUTES, RESPONSE_DAYS, VERBIS_STATUS } from "./constants";

export const metadata: Metadata = {
  title: "Your data requests",
  description:
    "How to export or delete your Menivor data, what each step does, how long it takes, what is kept, and how to use your GDPR and KVKK rights.",
  alternates: { canonical: "/legal/data-requests" },
};

const SECTIONS: readonly LegalSection[] = [
  {
    id: "export",
    heading: "Export your data",
    body: (
      <>
        <p>
          Signed in, open <Link href="/settings/privacy">Settings, Privacy</Link>{" "}
          and choose <strong>Export my data</strong>. You get a private download
          link at once; it works for {EXPORT_LINK_MINUTES} minutes, and you can
          make a new one any time.
        </p>
        <p>
          The file is JSON and holds your profile, your videos and render jobs,
          the details of your uploads, your credit history, the billing records
          of workspaces you own, your consent choices and your workspace
          memberships. The videos and uploads themselves can be downloaded
          from your library.
        </p>
      </>
    ),
  },
  {
    id: "delete",
    heading: "Delete your account",
    body: (
      <>
        <p>
          In <Link href="/settings/privacy">Settings, Privacy</Link> choose{" "}
          <strong>Delete my account</strong> and type DELETE to confirm. It
          cannot be undone. When you confirm, we:
        </p>
        <ul>
          <li>cancel your live plan (and any team plan only you own) with the payment provider;</li>
          <li>stop any renders that are queued or running;</li>
          <li>delete your stored media: uploads, voice samples, renders and job files;</li>
          <li>delete your sign-in account, which ends every session;</li>
          <li>replace your name, email and other personal details in our records with anonymous values, and clear your scripts and prompts;</li>
          <li>send one confirmation email to the address you had.</li>
        </ul>
        <p>
          If a provider is briefly unavailable, the remaining steps are retried
          automatically until they finish.
        </p>
        <p>
          We keep invoices and payment records for as long as tax law
          requires, without your name or email on our side. Paid credits you
          have not used are not kept for you after deletion; if you want a
          refund of unused credits, ask before you delete (see the{" "}
          <Link href="/refunds">Refund Policy</Link>).
        </p>
      </>
    ),
  },
  {
    id: "other-rights",
    heading: "Other rights and requests by email",
    body: (
      <>
        <p>
          You can also ask us to correct your data, restrict or object to how
          we use it, tell you which data we hold and who received it, or do any
          of the above for you. Write to{" "}
          <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>{" "}
          from the email on your account (or tell us how to reach you). We may
          ask you to confirm it is you. We answer free of charge within{" "}
          {RESPONSE_DAYS} days.
        </p>
        <p>
          No account, but think we hold data about you? Email us with what you
          know (for example a video link) and we will look.
        </p>
      </>
    ),
  },
  {
    id: "kvkk",
    heading: "For people in Turkey (KVKK)",
    body: (
      <>
        <p>
          Under Law No. 6698 on the Protection of Personal Data (KVKK),
          Article 11, you can learn whether we process your data, ask for
          information about it, learn why and whether it is used for that
          purpose, learn who in Turkey or abroad receives it, ask for
          correction or deletion and for those changes to be passed on, object
          to a result that is against you and comes only from automated
          analysis, and claim compensation for damage from unlawful processing.
        </p>
        <p>
          Send your request in writing to{" "}
          <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>. We
          answer within {RESPONSE_DAYS} days (KVKK Article 13), free of charge.
          If you are not satisfied with the answer you can complain to the
          Personal Data Protection Board (
          <a href="https://www.kvkk.gov.tr/" rel="noopener noreferrer" target="_blank">
            kvkk.gov.tr
          </a>
          ).
        </p>
        <p>{VERBIS_STATUS}</p>
        <p>
          Our servers are in Germany and some providers are in the United
          States; the list is on{" "}
          <Link href="/legal/subprocessors">Subprocessors</Link>.
        </p>
      </>
    ),
  },
  {
    id: "eu",
    heading: "For people in the EU and UK (GDPR)",
    body: (
      <p>
        The export covers your rights of access and portability (Articles 15
        and 20) and deletion covers erasure (Article 17). For the other rights,
        write to us as above. You can also complain to the data protection
        authority where you live or work.
      </p>
    ),
  },
];

export default function DataRequestsPage() {
  return (
    <LegalPage
      kicker="Legal"
      title="Your data requests"
      intro={
        <p>
          You can export or delete your Menivor data yourself, in a few
          clicks. This page explains each step, what it does and what we keep.
          How we use data is in the <Link href="/privacy">Privacy Policy</Link>.
        </p>
      }
      sections={SECTIONS}
    />
  );
}
