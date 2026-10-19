import type { Metadata } from "next";
import Link from "next/link";
import {
  LEGAL_CONTACT_EMAIL,
  LegalPage,
  type LegalSection,
} from "@/components/marketing/LegalPage";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { FaqSection } from "@/components/marketing/seo/FaqSection";
import { faqPageLd, graphDocument, type FaqEntry } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Creator Contract: credits never expire, failed renders refunded",
  description:
    "Menivor's four public promises to creators: credits never expire, failed renders are refunded automatically, we never train on your content, and you can cancel anytime.",
  alternates: { canonical: "/creator-contract" },
};

/**
 * The Creator Contract: four plain-language promises, each tied to how the
 * product actually enforces it. Every statement here matches shipped
 * behaviour (no expiry on credit balances, the automatic failure refund in
 * the render worker, the no-training line in the privacy policy and terms,
 * one-time packs and self-serve workspace cancellation).
 */
const SECTIONS: readonly LegalSection[] = [
  {
    id: "credits-never-expire",
    heading: "Your credits never expire",
    body: (
      <>
        <p>
          Credits you buy in a pack, and the free credits every new account
          starts with, stay in your balance until you use them. There is no
          90-day clock, no monthly reset and no &quot;use it or lose it&quot;.
          Packs are one-time purchases, not subscriptions.
        </p>
        <p>
          A workspace plan grants a recurring team allotment on top of that; the
          plan page states how that allotment works before you subscribe.
          Credits you bought yourself are never affected by a workspace plan.
        </p>
      </>
    ),
  },
  {
    id: "failed-renders-refunded",
    heading: "Failed renders are refunded automatically",
    body: (
      <>
        <p>
          One reel costs one credit, and you only pay for reels that finish. If
          a render fails on our side, the credit goes back to the balance it
          came from as soon as the job is marked failed. You don&apos;t need to
          open a ticket or ask. Cancelling a render that is still in progress
          refunds it too.
        </p>
        <p>
          The refund happens once per render attempt, so you never get charged
          twice for the same failure. If a render finished but is clearly
          broken, for example silent audio or a corrupt file, email{" "}
          <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>{" "}
          with the reel link and we restore the credit. Details are in the{" "}
          <Link href="/refunds">Refund Policy</Link>.
        </p>
      </>
    ),
  },
  {
    id: "never-train-on-your-content",
    heading: "We never train on your content",
    body: (
      <>
        <p>
          Your uploads, scripts, voice, face and the reels you make are used
          only to produce and deliver your reels. We do not use them to train
          any model, and we do not sell or license them to anyone who would.
          You keep ownership of what you upload and what you produce.
        </p>
        <p>
          Some render steps, such as the voiceover or the presenter, run on
          outside providers. They receive only what that one step needs, only to
          produce your reel. Who processes what is listed in our{" "}
          <Link href="/privacy">Privacy Policy</Link> and on the{" "}
          <Link href="/providers">providers page</Link>. The same promise is in
          our <Link href="/terms">Terms of Service</Link>.
        </p>
      </>
    ),
  },
  {
    id: "cancel-anytime",
    heading: "Cancel anytime",
    body: (
      <>
        <p>
          Credit packs have nothing to cancel: you pay once and that&apos;s it. A
          workspace subscription can be cancelled by its owner from{" "}
          <Link href="/billing">Billing</Link> in a few clicks, with no fee and
          no call. You keep access until the end of the period you paid for, and
          you keep every credit you bought.
        </p>
        <p>
          You can also export your data or delete your account yourself from
          your privacy settings at any time.
        </p>
      </>
    ),
  },
  {
    id: "why",
    heading: "Why we publish this",
    body: (
      <>
        <p>
          Expiring credits, failed generations that still cost you, and terms
          that claim broad rights to train on your uploads are common in AI
          video tools. We would rather tell you up front what we will and
          won&apos;t do. If we ever break one of these promises, email us and
          we will make it right.
        </p>
        <p>
          If this contract changes, we will say so on this page with a new
          effective date. A change will never take away credits you already
          hold.
        </p>
      </>
    ),
  },
];

const CONTRACT_FAQS: readonly FaqEntry[] = [
  {
    question: "Do Menivor credits expire?",
    answer:
      "No. Credits you buy in a pack and your free starter credits stay in your balance until you use them. Packs are one-time purchases, not subscriptions.",
  },
  {
    question: "What happens to my credit if a render fails?",
    answer:
      "It is refunded automatically to the balance it came from as soon as the render is marked failed. You don't need to contact support.",
  },
  {
    question: "Does Menivor train AI models on my videos or my face?",
    answer:
      "No. Your uploads, scripts, voice, likeness and finished reels are used only to produce your reels. We don't use them for training and don't sell or license them to anyone who would.",
  },
];

export default function CreatorContractPage() {
  return (
    <>
      <JsonLd data={graphDocument([faqPageLd(CONTRACT_FAQS)])} />
      <LegalPage
        kicker="Creator Contract"
        title="Four promises we make to every creator"
        intro={
          <>
            <p>
              Credits never expire. Failed renders are refunded automatically. We
              never train on your content. You can cancel anytime.
            </p>
            <p className="mt-3">
              This page explains what each promise means and how the product
              keeps it. It sits alongside our{" "}
              <Link href="/terms" className="text-primary underline underline-offset-4">
                Terms
              </Link>{" "}
              and{" "}
              <Link href="/pricing" className="text-primary underline underline-offset-4">
                pricing
              </Link>
              .
            </p>
          </>
        }
        sections={SECTIONS}
      />
      <div className="container pb-20">
        <div className="max-w-3xl">
          <FaqSection faqs={CONTRACT_FAQS} />
        </div>
      </div>
    </>
  );
}
