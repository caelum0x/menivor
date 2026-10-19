import { PersonalPlans } from "@/src/features/plans";
import { CreditPacks } from "@/src/features/wallet/CreditPacks";
import { BillingHelp } from "@/components/billing/BillingHelp";

/** Wallet plans route: monthly plans first, then one-off credit packs for top-ups. */
export default function WalletPlansPage() {
  return (
    <>
      <div className="container max-w-5xl pt-10">
        <PersonalPlans />
      </div>
      <CreditPacks />
      <div className="container max-w-5xl pb-10">
        <BillingHelp />
      </div>
    </>
  );
}
