/** Shared person-to-person AI-token contract used by web, Expo and desktop. */
export interface WalletTransferRecipient {
    /** Exact public Menivor handle or Mint receive address; never an account id. */
    handle: string;
    display_name: string;
    kind: WalletPrincipalKind;
    can_receive: boolean;
}
export type WalletPrincipalKind = "personal" | "workspace" | "agent" | "service";
export type WalletDestinationKind = Exclude<WalletPrincipalKind, "personal">;
export interface WalletDestinationProfile {
    destination_id: string;
    handle: string;
    display_name: string;
    kind: WalletDestinationKind;
    scope: "personal" | "workspace";
    workspace_source_account_id: string | null;
    active: boolean;
    address: string;
}
export interface WalletDestinationProfileRequest {
    kind: WalletDestinationKind;
    slug: string;
    display_name: string;
    workspace_source_account_id?: string;
}
export interface WalletDestinationBalance {
    destination: WalletDestinationProfile;
    currency: "AIT";
    available_micros: number;
    held_micros: number;
}
export interface WalletTransferRequest {
    source_account_id: string;
    challenge_id: string;
    recipient_handle: string;
    /** Integer microdollars. One USD equals 1,000,000 micros. */
    amount_micros: number;
}
export interface WalletSource {
    source_account_id: string;
    kind: "personal" | "workspace";
    label: string;
    role: string;
    can_send: boolean;
    limits: {
        per_transfer_micros: number;
        /** Zero means no configured UTC-daily limit. */
        daily_micros: number;
        daily_used_micros: number;
        daily_remaining_micros: number | null;
    };
}
export interface WalletReceiveAddress {
    /** Public Mint destination; safe to share and never authorizes a debit. */
    address: string;
    source: WalletSource;
}
export interface WalletTransferChallengeRequest {
    source_account_id: string;
    recipient_handle: string;
    saved_recipient_id?: string;
    amount_micros: number;
}
export interface WalletTransferPolicyRequest {
    source_account_id: string;
    /** Zero disables the configured limit; the global hard maximum still applies. */
    per_transfer_limit_micros: number;
    /** Zero disables the UTC-daily limit. */
    daily_limit_micros: number;
}
export interface WalletTransferPolicyResult {
    source_account_id: string;
    limits: WalletSource["limits"];
}
export interface WalletTransferChallenge {
    challenge_id: string;
    source: WalletSource;
    recipient: {
        handle: string;
        display_name: string;
        kind: WalletPrincipalKind;
    };
    amount_micros: number;
    binding_sha256: string;
    expires_at: string;
}
export interface WalletSavedRecipient {
    saved_recipient_id: string;
    handle: string;
    display_name: string;
    label: string;
}
export interface WalletTransferBalance {
    available_micros: number;
    held_micros: number;
}
/** Sender-safe metadata projected from Mint's signed sender-chain receipt.
 * Independent privacy-safe verification is a separate attestation phase. */
export interface WalletTransferReceiptProof {
    sequence: number;
    operation: string;
    operation_hash: string;
    amount_micros: number;
    receipt_hash: string;
    signature: string;
}
export type WalletTransferVerification = {
    status: "pending";
} | {
    status: "verified";
    format: "mint-transfer-attestation-v1";
    signer_key_id: string;
    digest_sha256: string;
    verified_at: string | null;
};
export interface WalletTransferResult {
    transfer_id: string;
    source: Pick<WalletSource, "source_account_id" | "kind" | "label">;
    recipient: {
        handle: string;
        display_name: string;
        kind: WalletPrincipalKind;
    };
    amount_micros: number;
    amount_usd: string;
    status: string;
    mint_first_seq: number | null;
    idempotent_replay: boolean;
    created_at: string | null;
    completed_at: string | null;
    sender_balance?: WalletTransferBalance;
    /** Signed Mint receipt metadata when settlement is complete. */
    receipt_proof: WalletTransferReceiptProof | null;
    /** Sender-only verification of this transfer, not a global supply proof. */
    verification: WalletTransferVerification;
}
/** Canonical wallet endpoint paths relative to the `/api/v1` base. */
export declare const WALLET_PATHS: {
    readonly wallet: "/wallet";
    readonly activity: "/wallet/activity";
    readonly purchaseQuotes: "/wallet/purchase-quotes";
    readonly checkout: "/wallet/checkout";
    readonly recipients: (handle: string) => string;
    readonly sources: "/wallet/sources";
    readonly receiveAddresses: "/wallet/receive-addresses";
    readonly destinations: "/wallet/destinations";
    readonly destination: (destinationId: string) => string;
    readonly destinationBalance: (destinationId: string) => string;
    readonly destinationActivity: (destinationId: string) => string;
    readonly transferPolicy: "/wallet/transfer-policy";
    readonly transferChallenges: "/wallet/transfer-challenges";
    readonly savedRecipients: "/wallet/saved-recipients";
    readonly savedRecipient: (savedRecipientId: string) => string;
    readonly transfers: "/wallet/transfers";
    readonly transfer: (transferId: string) => string;
};
/** Render a handle with `@` while leaving a shareable Mint address intact. */
export declare function formatWalletDestination(value: string): string;
/** Parse a positive decimal USD string into exact integer micros. */
export declare function parseUsdMicros(value: string): number | null;
