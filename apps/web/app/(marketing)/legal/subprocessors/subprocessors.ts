/**
 * M7.3: the companies that process personal data for Menivor.
 *
 * Source of truth for /legal/subprocessors and the privacy policy. Built from
 * the providers the API and web app call in production (2026-09-29). A new
 * provider is added here, with its date, before it receives personal data.
 * `when` says whether every user's data reaches it or only when a feature is
 * used. `location` is stated only where we know it; otherwise the provider's
 * own terms are linked.
 */

export interface Subprocessor {
  readonly name: string;
  readonly purpose: string;
  readonly data: string;
  readonly when: "always" | string;
  readonly location: string;
  readonly termsLabel: "Data processing terms" | "Commercial terms (include data processing terms)" | "Privacy policy";
  readonly termsUrl: string;
}

export const SUBPROCESSORS_UPDATED = "2026-09-29";

export const SUBPROCESSORS: readonly Subprocessor[] = [
  {
    name: "Oracle Cloud Infrastructure",
    purpose:
      "Application servers, rendering, our own database and queue servers, error tracking we run ourselves, and transactional email (OCI Email Delivery).",
    data: "Account data, your content while it is rendered, usage and security logs, email address for service email.",
    when: "always",
    location: "Germany (Frankfurt region)",
    termsLabel: "Data processing terms",
    termsUrl: "https://www.oracle.com/contracts/cloud-services/",
  },
  {
    name: "Cloudflare",
    purpose: "Web app hosting, content delivery, network security, and object storage for uploads and finished videos (R2).",
    data: "IP address and request data, your uploads and rendered videos.",
    when: "always",
    location: "Global network",
    termsLabel: "Data processing terms",
    termsUrl: "https://www.cloudflare.com/cloudflare-customer-dpa/",
  },
  {
    name: "Neon",
    purpose: "Managed Postgres for the account and credit ledger.",
    data: "Account data, purchases, plan and credit balance.",
    when: "always",
    location: "Germany (AWS eu-central-1, Frankfurt)",
    termsLabel: "Data processing terms",
    termsUrl: "https://neon.com/dpa",
  },
  {
    name: "Clerk",
    purpose: "Sign-in and account sessions.",
    data: "Email address, name, sign-in identifiers, session and device data.",
    when: "always",
    location: "United States",
    termsLabel: "Data processing terms",
    termsUrl: "https://clerk.com/legal/dpa",
  },
  {
    name: "Anthropic",
    purpose: "Writing scripts, hooks and captions from your link or topic (through our own AI gateway).",
    data: "The text of your prompt, product page or topic, and brand details you add.",
    when: "When you create a video that needs a script",
    location: "United States",
    termsLabel: "Commercial terms (include data processing terms)",
    termsUrl: "https://www.anthropic.com/legal/commercial-terms",
  },
  {
    name: "Microsoft",
    purpose: "Fallback text-to-speech narration when our own voice server is busy.",
    data: "The narration text of your video.",
    when: "When the fallback narration voice is used",
    location: "See the provider's terms",
    termsLabel: "Privacy policy",
    termsUrl: "https://privacy.microsoft.com/en-us/privacystatement",
  },
  {
    name: "fal.ai",
    purpose: "AI video and image generation for AI clips.",
    data: "The prompt and any images you supply for that clip.",
    when: "When a video includes AI-generated clips or images",
    location: "United States",
    termsLabel: "Privacy policy",
    termsUrl: "https://fal.ai/privacy",
  },
  {
    name: "ElevenLabs",
    purpose: "Premium narration voices and brand voice cloning.",
    data: "Narration text; for a brand voice, the voice sample you upload (never the verification recording).",
    when: "When you use a premium voice or create a brand voice",
    location: "United States",
    termsLabel: "Data processing terms",
    termsUrl: "https://elevenlabs.io/dpa",
  },
  {
    name: "HeyGen",
    purpose: "AI presenter videos.",
    data: "The script and the presenter settings for that video.",
    when: "When you use a presenter style",
    location: "United States",
    termsLabel: "Privacy policy",
    termsUrl: "https://www.heygen.com/policy",
  },
  {
    name: "Upload-Post",
    purpose: "Posting your videos to the social accounts you connect, for some platforms.",
    data: "The video, caption and the connected account's posting access.",
    when: "When you publish to a connected social account",
    location: "See the provider's terms",
    termsLabel: "Privacy policy",
    termsUrl: "https://www.upload-post.com/privacy",
  },
  {
    name: "Dodo Payments",
    purpose: "Checkout, invoices and tax as merchant of record.",
    data: "Name, email, billing country and address, purchase details. Card data goes to them, never to us.",
    when: "When you buy a plan or credits",
    location: "See the provider's terms",
    termsLabel: "Privacy policy",
    termsUrl: "https://dodopayments.com/privacy-policy",
  },
  {
    name: "Creem",
    purpose: "Merchant of record for earlier purchases; keeps the records of those purchases.",
    data: "Name, email, billing details and purchase history of those purchases.",
    when: "Only if you bought through Creem before we moved to Dodo Payments",
    location: "See the provider's terms",
    termsLabel: "Privacy policy",
    termsUrl: "https://www.creem.io/privacy",
  },
];
