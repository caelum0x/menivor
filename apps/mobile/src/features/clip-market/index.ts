/**
 * ClipMarket feature group (Wave 2) — Marketplace & Earnings. Screens are
 * backend-wired to `lib/clipmarket.ts` (campaigns + submissions) and the
 * read-only `lib/earnings.ts` (wallet balance + activity). Public surface for
 * routing + reuse.
 */

export { MarketplaceScreen } from "./MarketplaceScreen";
export { EarningsScreen } from "./EarningsScreen";

export { CampaignCard, type CampaignCardProps } from "./components/CampaignCard";
export {
  CreateCampaignForm,
  type CreateCampaignFormProps,
} from "./components/CreateCampaignForm";
export {
  SubmitClipSheet,
  type SubmitClipSheetProps,
} from "./components/SubmitClipSheet";
export {
  EarningsSummary,
  type EarningsSummaryProps,
} from "./components/EarningsSummary";
export { ActivityRow, type ActivityRowProps } from "./components/ActivityRow";

export {
  USD_TO_MICROS,
  usdToMicros,
  parseCampaignForm,
  isHttpUrl,
  statusActions,
  summarizeSpend,
  parseReviewForm,
  type CampaignFormInput,
  type ParseResult,
  type SpendSummary,
  type ReviewFormInput,
} from "./logic";
