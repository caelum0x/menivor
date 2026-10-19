import { CREATOR_CONTRACT, LegalDocumentScreen } from "@/src/shared/legal";

/**
 * Route: /legal/creator-contract — the bundled Creator Contract (no session
 * required): credits never expire, failed renders refunded automatically, no
 * training on your content, per-reel pricing, cancel anytime.
 */
export default function CreatorContractScreen() {
  return <LegalDocumentScreen document={CREATOR_CONTRACT} />;
}
