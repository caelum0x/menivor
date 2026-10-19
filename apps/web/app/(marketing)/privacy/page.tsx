import type { Metadata } from "next";
import Link from "next/link";
import {
  LEGAL_CONTACT_EMAIL,
  LegalPage,
  type LegalSection,
} from "@/components/marketing/LegalPage";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description:
    "What personal data Menivor collects, why, which processors handle it, how long it is kept, and how to export or delete it.",
  alternates: { canonical: "/privacy" },
};

const SECTIONS: readonly LegalSection[] = [
  {
    id: "collect",
    heading: "What we collect",
    body: (
      <ul>
        <li><strong>Account data</strong> — email address, name and sign-in identifiers from our authentication provider (Clerk), or a random guest-session identifier stored in your browser if you have not signed up.</li>
        <li><strong>Your content</strong> — recordings, audio, images, prompts, brand assets and the videos we render for you.</li>
        <li><strong>Billing data</strong> — purchases, plan, credit balance and invoices. Card and bank details are collected by the payment provider, never by Menivor.</li>
        <li><strong>Usage data</strong> — render jobs, API-key usage, audit events, device and browser information and IP address, used for security, fraud prevention and reliability.</li>
        <li><strong>Connected accounts</strong> — if you connect a social platform for publishing, the access tokens and profile data that platform returns.</li>
      </ul>
    ),
  },
  {
    id: "use",
    heading: "How we use it",
    body: (
      <>
        <ul>
          <li>to run the service: store uploads, generate and render videos, and publish them where you ask us to (contract);</li>
          <li>to process payments, grant credits and keep accounting records (contract and legal obligation);</li>
          <li>to secure the service, prevent abuse of the free tier and investigate incidents (legitimate interest);</li>
          <li>to send service emails and, only with your consent, product updates (consent — withdraw any time).</li>
        </ul>
        <p>
          We do not sell personal data and we do not use your uploads to train
          our own models.
        </p>
      </>
    ),
  },
  {
    id: "processors",
    heading: "Who processes it",
    body: (
      <>
        <p>
          We share data only with providers that help us operate Menivor, under
          data-processing terms:
        </p>
        <ul>
          <li>Hosting, storage and delivery — Cloudflare (web app, object storage) and our application servers and database hosts.</li>
          <li>Authentication — Clerk.</li>
          <li>Payments — Dodo Payments, which acts as merchant of record for your purchase (earlier purchases were sold by Creem).</li>
          <li>AI processing — the voice, avatar, transcription, language and video-generation providers you select or that a render requires (for example ElevenLabs for voice and HeyGen for avatar presenters). They receive only the material needed for that step.</li>
          <li>Publishing — the social platforms you connect and ask us to post to.</li>
        </ul>
        <p>
          Our servers and main database are in Germany. Some providers are
          outside your country, including in the United States; transfers rely
          on standard contractual clauses or equivalent safeguards.
        </p>
        <p>
          The full list, with what each company receives, when, where, and a
          link to its data processing terms, is on{" "}
          <Link href="/legal/subprocessors">Subprocessors</Link>.
        </p>
      </>
    ),
  },
  {
    id: "retention",
    heading: "How long we keep it",
    body: (
      <p>
        Account data is kept while your account is open. Uploads and renders
        are kept until you delete them, your account is deleted, or a
        workspace&apos;s configured retention window expires. Billing records
        are kept as long as tax law requires. Security logs are kept for a
        limited period and then deleted or anonymized.
      </p>
    ),
  },
  {
    id: "rights",
    heading: "Your rights and controls",
    body: (
      <>
        <p>
          Depending on where you live (including under the GDPR and
          Turkey&apos;s KVKK) you can access, correct, export, restrict or
          delete your personal data, object to processing and withdraw
          consent. Signed-in users can do most of this themselves in{" "}
          <Link href="/settings/privacy">Privacy settings</Link>: export all
          your data, manage consent choices and permanently delete your
          account. <Link href="/legal/data-requests">Your data requests</Link>{" "}
          explains each step, what is deleted and what is kept.
        </p>
        <p>
          For anything else, email{" "}
          <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>.
          You may also complain to your local data-protection authority.
        </p>
      </>
    ),
  },
  {
    id: "kvkk",
    heading: "Turkey (KVKK)",
    body: (
      <p>
        If you are in Turkey, Law No. 6698 (KVKK) gives you the rights in
        Article 11. How to use them, our 30-day answer time and how to
        complain to the Personal Data Protection Board are on{" "}
        <Link href="/legal/data-requests#kvkk">Your data requests</Link>.
      </p>
    ),
  },
  {
    id: "ai-marking-voice",
    heading: "AI marking and voice checks",
    body: (
      <>
        <p>
          Every final video we render carries a mark that it was made with AI
          and signed Content Credentials (C2PA) with a content id, so a copy
          can be traced back to its record here for a takedown report. The
          mark holds no name or email. Anyone can read it on{" "}
          <Link href="/legal/content-credentials">Check a video</Link>.
        </p>
        <p>
          Before you create a brand voice, you record yourself reading a short
          phrase. We use that recording only to check that the words were
          said and that it is the same voice as your sample (speech
          recognition and a speaker check run on our own servers). It is never
          sent to the voice provider. It is kept with your uploads and
          deleted with your account.
        </p>
      </>
    ),
  },
  {
    id: "cookies",
    heading: "Cookies and local storage",
    body: (
      <p>
        We use strictly necessary cookies and browser storage for sign-in, your
        guest session, language preference and security. We do not use
        third-party advertising cookies.
      </p>
    ),
  },
  {
    id: "children",
    heading: "Children",
    body: (
      <p>
        Menivor is not directed at children under 16 and we do not knowingly
        collect their data. If you believe a child has given us data, contact
        us and we will delete it.
      </p>
    ),
  },
  {
    id: "changes",
    heading: "Changes to this policy",
    body: (
      <p>
        We will post updates here and change the effective date. Material
        changes are announced by email or in the product before they apply.
      </p>
    ),
  },
];

export default function PrivacyPolicyPage() {
  return (
    <LegalPage
      kicker="Legal"
      title="Privacy Policy"
      intro={
        <p>
          This policy explains how Menivor handles personal data when you use
          menivor.com, our API and our apps. Menivor is the controller of this
          data.
        </p>
      }
      sections={SECTIONS}
    />
  );
}
