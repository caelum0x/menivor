/**
 * Wording for the sign-out confirmation.
 *
 * Store builds are signup-first: every account has an Apple (or email/Google)
 * identity, so the prompt is a plain "Sign out?". The device-account warning
 * (an unlinked test account that can only be recovered from the internal
 * Account Access screen) exists only in lab sessions.
 */

export interface SignOutPrompt {
  title: string;
  message: string;
  /** Offer "Link sign-in first" (lab sessions only). */
  offerLink: boolean;
}

const LINKED: SignOutPrompt = {
  title: "Sign out?",
  message: "You can sign back in any time with the same account.",
  offerLink: false,
};

const DEVICE_ACCOUNT: SignOutPrompt = {
  title: "Sign out of this device account?",
  message:
    "This is a device account with no Apple or Google sign-in linked. After signing out you can only get back into it on this install from Account Access. Link a sign-in first to keep your reels and credits safe.",
  offerLink: true,
};

export function signOutPrompt({ linked, lab }: { linked: boolean; lab: boolean }): SignOutPrompt {
  return !linked && lab ? DEVICE_ACCOUNT : LINKED;
}
