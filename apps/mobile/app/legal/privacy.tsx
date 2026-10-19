import { LegalDocumentScreen, PRIVACY_POLICY } from "@/src/shared/legal";

/** Route: /legal/privacy — bundled Privacy Policy (no session required). */
export default function PrivacyPolicyScreen() {
  return <LegalDocumentScreen document={PRIVACY_POLICY} />;
}
