import type { Metadata } from "next";
import Link from "next/link";
import {
  LEGAL_CONTACT_EMAIL,
  LegalPage,
  type LegalSection,
} from "@/components/marketing/LegalPage";

export const metadata: Metadata = {
  title: "Terms of Service",
  description:
    "The terms that govern your use of Menivor, the AI video creation and editing service at menivor.com.",
  alternates: { canonical: "/terms" },
};

const SECTIONS: readonly LegalSection[] = [
  {
    id: "service",
    heading: "The service",
    body: (
      <>
        <p>
          Menivor (&quot;Menivor&quot;, &quot;we&quot;, &quot;us&quot;)
          provides an online service that turns screen recordings, voice
          memos, prompts and other material you supply into short-form videos
          using automated editing and third-party AI models (scripts,
          voiceovers, avatar presenters, captions and generated footage). The
          service is available at menivor.com, through our API at
          api.menivor.com, and in our mobile and desktop apps.
        </p>
        <p>
          By creating an account or otherwise using the service you agree to these terms. If you use Menivor on behalf of
          an organization, you confirm you are authorized to bind it.
        </p>
      </>
    ),
  },
  {
    id: "accounts",
    heading: "Accounts",
    body: (
      <>
        <p>
          You need an account to create reels. Your reels and credits belong
          to your account and follow you across devices. If you used an
          earlier browser-only guest session, you can move that work into
          your account when you sign in from the same browser.
        </p>
        <p>
          You are responsible for activity under your account and API keys.
          Keep credentials confidential and revoke keys you no longer use. You
          must be at least 16 years old (or the age of digital consent where
          you live) to use Menivor.
        </p>
      </>
    ),
  },
  {
    id: "content",
    heading: "Your content",
    body: (
      <>
        <p>
          You keep ownership of the material you upload and the videos you
          produce. You grant us a limited licence to host, process, transform
          and deliver that material solely to operate the service for you —
          including sending it to the processing providers listed in our{" "}
          <Link href="/privacy">Privacy Policy</Link>.
        </p>
        <p>
          We do not use your uploads, scripts, voice, likeness or produced
          videos to train any model, and we do not sell or license them to
          anyone who would. This is one of the promises in our{" "}
          <Link href="/creator-contract">Creator Contract</Link>.
        </p>
        <p>
          You confirm you have the rights to everything you upload, including
          the likeness and voice of any person who appears in it, and that your
          content does not infringe anyone&apos;s rights. Share pages you
          publish are public to anyone with the link until you revoke them.
        </p>
      </>
    ),
  },
  {
    id: "acceptable-use",
    heading: "Acceptable use",
    body: (
      <>
        <p>You must not use Menivor to create or distribute content that:</p>
        <ul>
          <li>impersonates a real person without their consent, or is deceptive in a way that could cause harm (including political or financial deception);</li>
          <li>is NSFW, sexually explicit or sexually suggestive, including nudity or pornographic material of any kind;</li>
          <li>is sexual content involving minors (zero tolerance, reported to authorities), non-consensual intimate imagery, or harassment;</li>
          <li>is a deepfake or face-swap of a real person, or uses someone&apos;s face, voice or likeness without their documented consent;</li>
          <li>is hateful, graphically violent or gory, or targets people based on a protected characteristic;</li>
          <li>infringes intellectual property or violates privacy or publicity rights;</li>
          <li>promotes violence, terrorism or illegal goods and services;</li>
          <li>attempts to abuse, reverse-engineer, overload or circumvent limits of the service or the free tier.</li>
        </ul>
        <p>
          The full rules are in our{" "}
          <Link href="/legal/acceptable-use">Acceptable Use Policy</Link>, which
          forms part of these terms. Every prompt and script is screened by
          automated moderation before anything is generated; blocked requests
          are never charged.
        </p>
        <p>
          We may remove content, suspend renders, or close accounts that break
          these rules, and we cooperate with lawful requests from authorities.
        </p>
      </>
    ),
  },
  {
    id: "credits",
    heading: "Credits, packs and workspace plans",
    body: (
      <>
        <p>
          Rendering a reel consumes credits. New users receive a small number
          of free credits. You can buy one-time credit packs, which are added
          to your personal balance, or subscribe a workspace to a monthly or
          yearly plan, which grants a recurring credit allotment and plan
          features. Prices are shown before checkout and may include taxes
          calculated by the payment provider.
        </p>
        <p>
          Payments are processed by Dodo Payments, which acts as merchant of
          record; Dodo Payments&apos; terms of sale also apply to your purchase
          (earlier purchases were sold by Creem). Subscriptions renew
          automatically until cancelled; you can cancel any time from{" "}
          <Link href="/billing">Billing</Link> and keep access until the end of
          the paid period. Refunds are covered by our{" "}
          <Link href="/refunds">Refund Policy</Link>. Credits have no cash
          value and cannot be transferred except where the product explicitly
          supports it.
        </p>
      </>
    ),
  },
  {
    id: "ai-output",
    heading: "AI-generated output",
    body: (
      <p>
        Generated scripts, voices, avatars and footage are produced by
        third-party AI models and can be inaccurate or unexpected. Menivor is
        an independent product and is not affiliated with or endorsed by the
        makers of those models. Review every
        video before you publish it. You are responsible for how you use
        output, including platform disclosure rules for AI-generated or
        sponsored content.
      </p>
    ),
  },
  {
    id: "availability",
    heading: "Availability and changes",
    body: (
      <p>
        We work to keep Menivor available but do not guarantee uninterrupted
        service; renders can fail or be delayed, in which case credits for
        failed renders are returned. We may change or discontinue features and
        will give reasonable notice of material changes to these terms by
        email or in the product.
      </p>
    ),
  },
  {
    id: "liability",
    heading: "Disclaimers and liability",
    body: (
      <p>
        The service is provided &quot;as is&quot;. To the extent permitted by
        law, we are not liable for indirect or consequential losses, and our
        total liability for any claim is limited to the amount you paid us in
        the 12 months before the claim. Nothing in these terms limits
        liability that cannot be limited by law or your statutory rights as a
        consumer.
      </p>
    ),
  },
  {
    id: "termination",
    heading: "Ending your use",
    body: (
      <p>
        You can stop using Menivor at any time and delete your account from{" "}
        <Link href="/settings/privacy">Privacy settings</Link>. We may suspend
        or terminate access for serious or repeated breaches of these terms.
        Sections that by their nature should survive termination (content
        licences needed to finish pending deliveries, liability limits) do so.
      </p>
    ),
  },
  {
    id: "contact",
    heading: "Contact",
    body: (
      <p>
        Questions about these terms: <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>.
      </p>
    ),
  },
];

export default function TermsPage() {
  return (
    <LegalPage
      kicker="Legal"
      title="Terms of Service"
      intro={
        <p>
          These terms explain what you can expect from Menivor and what we
          expect from you. Please read them together with our{" "}
          <Link href="/privacy" className="text-primary underline underline-offset-4">
            Privacy Policy
          </Link>{" "}
          and{" "}
          <Link href="/refunds" className="text-primary underline underline-offset-4">
            Refund Policy
          </Link>
          .
        </p>
      }
      sections={SECTIONS}
    />
  );
}
