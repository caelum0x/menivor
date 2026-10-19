import { LegalDocumentScreen, TERMS_OF_SERVICE } from "@/src/shared/legal";

/** Route: /legal/terms — bundled Terms of Service (no session required). */
export default function TermsScreen() {
  return <LegalDocumentScreen document={TERMS_OF_SERVICE} />;
}
