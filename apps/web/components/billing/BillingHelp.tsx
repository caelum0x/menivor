import { LEGAL_CONTACT_EMAIL } from "@/components/marketing/LegalPage";

/**
 * Dodo Payments' hosted customer portal (static email-login link for our
 * business): cancel, change card, download invoices.
 */
export const DODO_CUSTOMER_PORTAL_URL =
  "https://customer.dodopayments.com/login/bus_EKm0SScXc8Tpc3ZDoTbnn";

/** Creem's hosted customer portal, for purchases made before the move. */
export const CREEM_CUSTOMER_PORTAL_URL = "https://www.creem.io/my-orders/login";

interface BillingHelpProps {
  readonly className?: string;
}

const LINK = "font-medium text-primary underline underline-offset-4";

/**
 * Always-visible billing help: where to cancel a subscription yourself and
 * how to reach a human. Shown on every billing surface.
 */
export function BillingHelp({ className }: BillingHelpProps) {
  return (
    <div
      className={
        className ??
        "rounded-lg border border-border p-4 text-sm text-muted-foreground"
      }
      data-testid="billing-help"
    >
      <p>
        Cancel or manage any subscription yourself in the{" "}
        <a href={DODO_CUSTOMER_PORTAL_URL} target="_blank" rel="noopener noreferrer" className={LINK}>
          Dodo Payments customer portal
        </a>{" "}
        (sign in with the email you paid with). Payments are handled by Dodo
        Payments, our merchant of record. Bought before the move? Use the{" "}
        <a href={CREEM_CUSTOMER_PORTAL_URL} target="_blank" rel="noopener noreferrer" className={LINK}>
          Creem customer portal
        </a>
        .
      </p>
      <p className="mt-2">
        Questions about billing? Email{" "}
        <a href={`mailto:${LEGAL_CONTACT_EMAIL}`} className={LINK}>
          {LEGAL_CONTACT_EMAIL}
        </a>
        .
      </p>
    </div>
  );
}
