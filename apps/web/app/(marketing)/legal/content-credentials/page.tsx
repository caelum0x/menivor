import type { Metadata } from "next";
import Link from "next/link";
import { CredentialsCheck } from "./CredentialsCheck";

export const metadata: Metadata = {
  title: "Check a video's Content Credentials",
  description:
    "Upload an MP4 to see whether it carries C2PA Content Credentials, who signed them, and whether it is marked as AI-generated.",
  alternates: { canonical: "/legal/content-credentials" },
};

/**
 * M7.1: public C2PA check. Every final video made with Menivor carries a
 * signed C2PA manifest that marks it as AI-generated. Anyone can check a file
 * here; the upload is read and deleted in the same request.
 */
export default function ContentCredentialsPage() {
  return (
    <main className="container py-16">
      <div className="mx-auto max-w-xl space-y-6">
        <div>
          <p className="text-sm font-medium text-muted-foreground">Legal</p>
          <h1 className="text-3xl font-bold tracking-tight">Check a video</h1>
          <p className="mt-3 text-muted-foreground">
            Every final video made with Menivor carries C2PA Content
            Credentials: a signed record, inside the file, that says it was
            made with AI. Pick an MP4 to read it. We do not keep the file.
          </p>
          <p className="mt-3 text-sm text-muted-foreground">
            Our signing certificate is issued by Menivor, not by a certificate
            authority on the C2PA trust list, so other readers may show the
            signer as unrecognised while the signature itself still checks out.
            To report a video, use the{" "}
            <Link href="/legal/report" className="underline">
              report form
            </Link>
            .
          </p>
        </div>
        <CredentialsCheck />
      </div>
    </main>
  );
}
