/**
 * In-app Terms of Service, Privacy Policy and Creator Contract.
 *
 * These are shipped inside the binary so the links shown at account creation
 * and on every subscription surface are always functional (Apple Guideline
 * 3.1.2), including offline and before the public web pages exist. When a build
 * sets EXPO_PUBLIC_TERMS_URL / EXPO_PUBLIC_PRIVACY_URL, LegalLinks opens the
 * hosted page instead; keep both copies in sync when the text changes.
 */

export interface LegalSection {
  readonly heading: string;
  readonly paragraphs: readonly string[];
}

export interface LegalDocument {
  readonly title: string;
  readonly updated: string;
  readonly intro: string;
  readonly sections: readonly LegalSection[];
}

export const LEGAL_CONTACT_EMAIL = "hello@menivor.com";

export const TERMS_OF_SERVICE: LegalDocument = {
  title: "Terms of Service",
  updated: "September 2026",
  intro:
    "These Terms govern your use of the Menivor mobile app, website and API (together, the Service). By creating an account or using the Service you agree to them. If you do not agree, do not use the Service.",
  sections: [
    {
      heading: "1. Your account",
      paragraphs: [
        "You can start with a device account that is tied to this installation, or sign in with Apple or Google for a named account. You are responsible for activity under your account and for keeping any access key private.",
        "You must be at least 13 years old (or the minimum age of digital consent where you live) to use the Service.",
      ],
    },
    {
      heading: "2. Your content",
      paragraphs: [
        "You keep ownership of the recordings, images, audio, scripts and other material you upload (Your Content) and of the videos the Service generates from it.",
        "You grant Menivor a limited licence to host, process and transform Your Content only as needed to provide the Service to you, including sending it to the AI generation providers that render your videos.",
        "You confirm you have the rights to everything you upload, including the voices and likenesses of any people who appear in it. Do not clone a voice or create an avatar of anyone without their permission.",
      ],
    },
    {
      heading: "3. Acceptable use",
      paragraphs: [
        "Do not use the Service to create unlawful, deceptive, defamatory, hateful, sexually explicit or infringing content, to impersonate others, to spread misinformation presented as fact, or to harass anyone.",
        "Do not attempt to reverse engineer, overload, or bypass the limits and security of the Service. We may suspend accounts that break these rules.",
      ],
    },
    {
      heading: "4. Subscriptions and credits",
      paragraphs: [
        "Menivor Pro is an auto-renewing subscription sold through the App Store or Google Play. Payment is charged to your store account at confirmation of purchase. The subscription renews automatically unless you turn off auto-renew at least 24 hours before the end of the current period; your account is charged for renewal within 24 hours before the period ends.",
        "You can manage or cancel a subscription in your store account settings. Refunds are handled by Apple or Google under their policies.",
        "Generation credits are consumed when a render starts and are released back automatically if the render fails. Credits you buy do not expire. Credits have no cash value and cannot be transferred except where the Service explicitly allows it. Our Creator Contract, shown in the app, explains these promises in plain language.",
      ],
    },
    {
      heading: "5. AI output",
      paragraphs: [
        "Generated videos, captions, voices and scripts are produced by machine-learning models and may contain mistakes. Review everything before you publish it. You are responsible for what you publish.",
      ],
    },
    {
      heading: "6. Availability and changes",
      paragraphs: [
        "We work to keep the Service available but do not guarantee it will be uninterrupted. We may change or discontinue features, and we may update these Terms; material changes will be announced in the app.",
      ],
    },
    {
      heading: "7. Termination",
      paragraphs: [
        "You can stop using the Service and erase your account at any time from Privacy settings in the app. We may suspend or terminate access for breach of these Terms.",
      ],
    },
    {
      heading: "8. Disclaimers and liability",
      paragraphs: [
        "The Service is provided as is. To the extent permitted by law, Menivor is not liable for indirect or consequential losses, and our total liability for any claim is limited to the amount you paid us in the 12 months before the claim.",
      ],
    },
    {
      heading: "9. Contact",
      paragraphs: [`Questions about these Terms: ${LEGAL_CONTACT_EMAIL}.`],
    },
  ],
};

export const PRIVACY_POLICY: LegalDocument = {
  title: "Privacy Policy",
  updated: "September 2026",
  intro:
    "This policy explains what Menivor collects when you use the app, why, who it is shared with, and the controls you have. We do not sell your personal data.",
  sections: [
    {
      heading: "What we collect",
      paragraphs: [
        "Account data: a random installation identifier created on your device, the access key derived from it, and, if you sign in with Apple or Google, the email address and account identifier that provider shares with us.",
        "Content: the recordings, images, audio samples, scripts and settings you upload, and the videos, captions and covers generated from them.",
        "Usage and device data: job history, app version, platform and, if you allow notifications, a push token used to tell you when a render finishes.",
        "Purchases: subscription status from the App Store or Google Play via RevenueCat. We never receive your card details.",
      ],
    },
    {
      heading: "How we use it",
      paragraphs: [
        "To provide the Service: render your videos, keep your library, deliver notifications, verify your subscription and prevent abuse.",
        "To support you when you contact us, and to keep the Service secure and reliable.",
        "We never use your uploads, scripts, voice, face or generated videos to train AI models, and we do not sell or license them to anyone who would.",
      ],
    },
    {
      heading: "Who we share it with",
      paragraphs: [
        "AI generation providers that render voice, avatar and video on our behalf receive only the content needed for the job you requested.",
        "Infrastructure processors: cloud hosting and storage, Supabase (sign-in), RevenueCat (subscription status), Apple and Google (sign-in, purchases, push delivery).",
        "Social platforms only when you connect an account and ask us to publish to it.",
        "Authorities when required by law.",
      ],
    },
    {
      heading: "Retention",
      paragraphs: [
        "We keep your account and content while your account is active. When you erase your account, your content and personal data are deleted from active systems, and from backups on their normal rotation.",
      ],
    },
    {
      heading: "Your controls",
      paragraphs: [
        "In the app, open Privacy settings to download a copy of your data, change consent choices, or permanently erase your account.",
        "Depending on where you live you may also have rights to access, correct, restrict or object to processing. Contact us to exercise them.",
      ],
    },
    {
      heading: "Children",
      paragraphs: [
        "The Service is not directed to children under 13 and we do not knowingly collect their data.",
      ],
    },
    {
      heading: "Contact",
      paragraphs: [`Privacy questions or requests: ${LEGAL_CONTACT_EMAIL}.`],
    },
  ],
};

/**
 * The Creator Contract: plain-language promises, each tied to how the product
 * keeps it (no expiry on credit balances, the automatic failure refund in the
 * render worker, the no-training line in the Privacy Policy, one-time packs
 * and store-managed subscriptions). Mirrors the web page at /creator-contract
 * minus anything about web checkout, which store builds must not reference.
 */
export const CREATOR_CONTRACT: LegalDocument = {
  title: "Creator Contract",
  updated: "September 2026",
  intro:
    "Five promises we make to every creator. Credits never expire. Failed renders are refunded automatically. We never train on your face, voice or content. Pricing is per reel, with no fake unlimited plans. You can cancel anytime. Below is what each one means and how the app keeps it.",
  sections: [
    {
      heading: "1. Your credits never expire",
      paragraphs: [
        "Credits you buy in a pack, and the free credits every new account starts with, stay in your balance until you use them. There is no 90-day clock, no monthly reset and no use-it-or-lose-it.",
        "Credit packs are one-time purchases, not subscriptions. Subscribing to or cancelling Menivor Pro never removes credits you bought.",
      ],
    },
    {
      heading: "2. Failed renders are refunded automatically",
      paragraphs: [
        "One reel costs one credit, and you only pay for reels that finish. If a render fails on our side, the credit goes back to your balance as soon as the job is marked failed. You don't need to open a ticket or ask. Cancelling a render that is still in progress refunds it too.",
        `The refund happens once per render attempt, so you are never charged twice for the same failure. If a render finished but is clearly broken, for example silent audio or a corrupt file, email ${LEGAL_CONTACT_EMAIL} with the reel link and we restore the credit.`,
        "Refunds of the store purchase itself are handled by Apple or Google under their policies.",
      ],
    },
    {
      heading: "3. We never train on your face, voice or content",
      paragraphs: [
        "Your uploads, scripts, voice, face and the reels you make are used only to produce and deliver your reels. We do not use them to train any model, and we do not sell or license them to anyone who would. You keep ownership of what you upload and what you produce.",
        "Some render steps, such as the voiceover or the presenter, run on outside providers. They receive only what that one step needs, only to produce your reel. Who processes what is listed in our Privacy Policy.",
      ],
    },
    {
      heading: "4. One credit, one reel. No fake unlimited",
      paragraphs: [
        "One credit makes one finished reel, including the script, voiceover, presenter, captions and final render. Reel length doesn't change the price, and there are no separate credit types for reels.",
        "Every credit pack says how many reels it makes and shows its price per reel before you buy. We don't sell unlimited plans that quietly cap or slow you down. Other tools, such as B-roll generation or clipping, show what they cost before you start them.",
      ],
    },
    {
      heading: "5. Cancel anytime",
      paragraphs: [
        "Credit packs have nothing to cancel: you pay once. Menivor Pro renews through your App Store or Google Play account, and you can turn off auto-renew there at any time with no fee. You keep Pro until the end of the period you paid for, and you keep every credit you bought.",
        "You can also export your data or erase your account yourself from Privacy settings in the app at any time.",
      ],
    },
    {
      heading: "Why we publish this",
      paragraphs: [
        "Expiring credits, failed generations that still cost you, and terms that claim broad rights to train on your uploads are common in AI video tools. We would rather tell you up front what we will and won't do. If we ever break one of these promises, email us and we will make it right.",
        "If this contract changes, we will say so here with a new date. A change will never take away credits you already hold.",
      ],
    },
  ],
};
