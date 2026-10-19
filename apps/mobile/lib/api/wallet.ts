/**
 * Wallet domain — top-up, checkout, transfers, sources, destinations, recipients.
 * Re-exports from lib/wallet.ts with domain grouping.
 */

export {
  createTransferChallenge,
  createWalletCheckout,
  createWalletDestination,
  deleteTransferRecipient,
  formatWalletDestination,
  getWalletDestinationBalance,
  getWalletDestinations,
  getWalletReceiveAddress,
  getWalletSourceBalance,
  getWalletSources,
  getWalletTransfer,
  getSavedRecipients,
  isDefinitiveTransferFailureStatus,
  newIdempotencyKey,
  newTransferIdempotencyKey,
  parseUsdMicros,
  purchaseQuote,
  resolveTransferRecipient,
  saveTransferRecipient,
  sendWalletTransfer,
  setWalletDestinationActive,
  type PurchaseQuote,
  type WalletCheckoutIntent,
  type WalletCheckoutRequest,
  type WalletSourceBalance,
} from "@/lib/wallet";
