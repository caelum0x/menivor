import type { Metadata } from "next";
import Link from "next/link";
import {
  INDEPENDENT_PRODUCT_DISCLOSURE,
  LEGAL_CONTACT_EMAIL,
  LegalPage,
  type LegalSection,
} from "@/components/marketing/LegalPage";

export const metadata: Metadata = {
  title: "Acceptable Use Policy",
  description:
    "What you may and may not create with Menivor. No NSFW, sexual, violent, hateful, deepfake, impersonation or illegal content.",
  alternates: { canonical: "/legal/acceptable-use" },
};

const SECTIONS: readonly LegalSection[] = [
  {
    id: "prohibited",
    heading: "What you must not create",
    body: (
      <>
        <p>
          Menivor is for marketing and creator videos. You must not use it to
          generate, edit or distribute content that is:
        </p>
        <ul>
          <li>
            <strong>NSFW or sexual</strong>: nudity, pornography, sexually
            explicit or sexually suggestive material of any kind, including
            &quot;artistic&quot; or &quot;tasteful&quot; framings.
          </li>
          <li>
            <strong>Sexual content involving minors</strong>: zero tolerance.
            We close the account immediately and report it to the relevant
            authorities.
          </li>
          <li>
            <strong>Violent or gory</strong>: graphic violence, gore,
            self-harm, or content that promotes or glorifies violence or
            terrorism.
          </li>
          <li>
            <strong>Hateful or harassing</strong>: content that attacks or
            demeans people based on race, ethnicity, religion, gender, sexual
            orientation, disability or any other protected characteristic, or
            that bullies, threatens or harasses anyone.
          </li>
          <li>
            <strong>Deepfakes and face swaps</strong>: putting a real
            person&apos;s face, body or voice into content they did not
            consent to, or cloning a voice or likeness you are not authorized
            to use.
          </li>
          <li>
            <strong>Impersonation</strong>: pretending to be a real person,
            public figure, company or brand, or implying an endorsement that
            does not exist.
          </li>
          <li>
            <strong>Illegal</strong>: content that facilitates illegal goods,
            services or activity, infringes copyright or trademarks, or
            violates privacy or publicity rights.
          </li>
          <li>
            <strong>Deceptive advertising</strong>: false health, financial
            or product claims, fake reviews or testimonials, scams, or
            political disinformation.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "moderation",
    heading: "How we enforce it",
    body: (
      <>
        <p>
          Every prompt, script and text you submit for generation is screened
          by automated moderation before any image or video is generated. A
          request that breaks this policy is blocked with a clear message and
          is never charged.
        </p>
        <p>
          Repeated attempts to generate prohibited content, or attempts to get
          around moderation, lead to suspension or permanent closure of the
          account without refund of unused credits. We may remove content and
          cooperate with lawful requests from authorities.
        </p>
      </>
    ),
  },
  {
    id: "your-responsibility",
    heading: "Your responsibility",
    body: (
      <p>
        You are responsible for what you create and publish. Only upload
        material you have the rights to, get consent from anyone whose face or
        voice appears, and follow each platform&apos;s rules for AI-generated
        and sponsored content. See our{" "}
        <Link href="/terms">Terms of Service</Link> for the full agreement.
      </p>
    ),
  },
  {
    id: "ai-models",
    heading: "AI models",
    body: <p>{INDEPENDENT_PRODUCT_DISCLOSURE}</p>,
  },
  {
    id: "report",
    heading: "Report a problem",
    body: (
      <p>
        To report content that breaks this policy, or if you think a request
        was blocked by mistake, email{" "}
        <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>.
      </p>
    ),
  },
];

export default function AcceptableUsePage() {
  return (
    <LegalPage
      kicker="Legal"
      title="Acceptable Use Policy"
      intro={
        <p>
          Short version: make honest videos about things you have the right
          to show. No NSFW, sexual, violent, hateful, deepfake, impersonation
          or illegal content.
        </p>
      }
      sections={SECTIONS}
    />
  );
}
