import { dark } from "@clerk/themes";

/**
 * Clerk theming for the "dark glass" design system (see app/globals.css).
 *
 * Clerk styles its components with runtime CSS-in-JS, which outranks plain
 * class names of equal specificity, so the glass card and neumorphic controls
 * are expressed as style objects here rather than as `.glass-*` classes. The
 * values mirror the CSS tokens: a frosted card over the ambient light blobs,
 * a raised yellow primary button, and recessed input wells. Solid fallbacks
 * apply under prefers-reduced-transparency.
 */
const REDUCED_TRANSPARENCY = "@media (prefers-reduced-transparency: reduce)";

export const clerkAppearance = {
  baseTheme: dark,
  variables: {
    colorPrimary: "#FFD93D",
    colorTextOnPrimaryBackground: "#111114",
    colorBackground: "#121217",
    colorInputBackground: "#0b0b0e",
    colorText: "#efece6",
    colorTextSecondary: "#a39f99",
    borderRadius: "0.75rem",
    fontFamily: "inherit",
  },
  elements: {
    cardBox: {
      backgroundColor: "hsl(240 8% 9% / 0.72)",
      backdropFilter: "blur(22px) saturate(150%)",
      WebkitBackdropFilter: "blur(22px) saturate(150%)",
      border: "1px solid hsl(40 40% 96% / 0.13)",
      borderRadius: "1rem",
      boxShadow:
        "inset 0 1px 0 hsl(0 0% 100% / 0.07), 0 1px 2px hsl(0 0% 0% / 0.4), 0 24px 60px -20px hsl(0 0% 0% / 0.75)",
      [REDUCED_TRANSPARENCY]: {
        backgroundColor: "hsl(240 5% 8%)",
        backdropFilter: "none",
        WebkitBackdropFilter: "none",
      },
    },
    card: {
      backgroundColor: "transparent",
      boxShadow: "none",
      border: "none",
    },
    footer: {
      background: "transparent",
      borderTop: "1px solid hsl(40 30% 96% / 0.08)",
    },
    formButtonPrimary: {
      backgroundImage:
        "linear-gradient(180deg, hsl(0 0% 100% / 0.2), hsl(0 0% 100% / 0) 55%, hsl(30 100% 30% / 0.1))",
      boxShadow:
        "inset 0 1px 0 hsl(0 0% 100% / 0.5), inset 0 -2px 0 hsl(38 90% 38% / 0.25), 0 10px 24px -10px hsl(48 100% 55% / 0.55)",
      "&:active": {
        boxShadow: "inset 0 2px 5px hsl(38 90% 28% / 0.45)",
      },
    },
    formFieldInput: {
      backgroundColor: "hsl(240 6% 5% / 0.62)",
      border: "1px solid hsl(40 30% 96% / 0.09)",
      boxShadow: "inset 0 2px 5px hsl(0 0% 0% / 0.5), inset 0 -1px 0 hsl(0 0% 100% / 0.04)",
    },
    socialButtonsBlockButton: {
      backgroundColor: "hsl(0 0% 100% / 0.04)",
      border: "1px solid hsl(0 0% 100% / 0.12)",
      boxShadow: "inset 0 1px 0 hsl(0 0% 100% / 0.06)",
      "&:hover": { backgroundColor: "hsl(0 0% 100% / 0.08)" },
    },
    // Three labelled provider buttons in one row truncate to "Ap… Git… Go…" on
    // a 390px phone. Stack labelled buttons on narrow screens; icon-only rows
    // (sign-in) keep their single row.
    socialButtons: {
      "@media (max-width: 480px)": {
        "&:has(.cl-socialButtonsBlockButton)": { gridTemplateColumns: "1fr" },
      },
    },
    dividerLine: { backgroundColor: "hsl(40 30% 96% / 0.1)" },
  },
} as const;

/**
 * Copy overrides for Clerk's components. Without these the sign-in card reads
 * "Sign in to My Application" when the Clerk instance's application name has
 * not been set in the dashboard.
 */
export const clerkLocalization = {
  signIn: {
    start: {
      title: "Sign in to Menivor",
      subtitle: "Welcome back. Sign in to continue.",
    },
  },
  signUp: {
    start: {
      title: "Create your Menivor account",
    },
  },
};
