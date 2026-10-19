import type { Metadata } from "next";
import Link from "next/link";
import {
  LEGAL_CONTACT_EMAIL,
  LegalPage,
  type LegalSection,
} from "@/components/marketing/LegalPage";
import { SUBPROCESSORS, SUBPROCESSORS_UPDATED } from "./subprocessors";

export const metadata: Metadata = {
  title: "Subprocessors",
  description:
    "The companies that process personal data for Menivor, what each one does, which data it receives, where, and a link to its data processing terms.",
  alternates: { canonical: "/legal/subprocessors" },
};

const SECTIONS: readonly LegalSection[] = [
  {
    id: "list",
    heading: "Current subprocessors",
    body: (
      <>
        <p>Last updated {SUBPROCESSORS_UPDATED}.</p>
        <div className="not-prose overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="py-2 pr-4 font-medium text-foreground">Company</th>
                <th className="py-2 pr-4 font-medium text-foreground">What it does for us</th>
                <th className="py-2 pr-4 font-medium text-foreground">Data it receives</th>
                <th className="py-2 pr-4 font-medium text-foreground">When</th>
                <th className="py-2 pr-4 font-medium text-foreground">Where</th>
                <th className="py-2 font-medium text-foreground">Terms</th>
              </tr>
            </thead>
            <tbody>
              {SUBPROCESSORS.map((sp) => (
                <tr key={sp.name} className="border-b border-border align-top">
                  <td className="py-3 pr-4 text-foreground">{sp.name}</td>
                  <td className="py-3 pr-4">{sp.purpose}</td>
                  <td className="py-3 pr-4">{sp.data}</td>
                  <td className="py-3 pr-4">{sp.when === "always" ? "Always" : sp.when}</td>
                  <td className="py-3 pr-4">{sp.location}</td>
                  <td className="py-3">
                    <a href={sp.termsUrl} rel="noopener noreferrer" target="_blank" className="underline">
                      {sp.termsLabel}
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>
    ),
  },
  {
    id: "not-subprocessors",
    heading: "What is not on this list",
    body: (
      <>
        <p>
          Social platforms you connect (for example YouTube, TikTok or
          Instagram) receive your videos because you ask us to post there; they
          process them under their own terms, as independent controllers.
        </p>
        <p>
          Our own voice server, speech recognition, speaker check and error
          tracking run on our servers at Oracle Cloud in Frankfurt and are
          covered by that row.
        </p>
      </>
    ),
  },
  {
    id: "changes",
    heading: "Changes and your data processing agreement",
    body: (
      <>
        <p>
          We add a company here before it receives personal data and update
          the date above. Business customers who need a data processing
          agreement with Menivor, or want notice of changes to this list, can
          write to{" "}
          <a href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>.
        </p>
        <p>
          How we use personal data is explained in the{" "}
          <Link href="/privacy">Privacy Policy</Link>, and how to export or
          delete yours in <Link href="/legal/data-requests">Your data requests</Link>.
        </p>
      </>
    ),
  },
];

export default function SubprocessorsPage() {
  return (
    <LegalPage
      kicker="Legal"
      title="Subprocessors"
      intro={
        <p>
          These are the companies that process personal data on Menivor&apos;s
          behalf, what each one does, which data it gets, and when.
        </p>
      }
      sections={SECTIONS}
    />
  );
}
