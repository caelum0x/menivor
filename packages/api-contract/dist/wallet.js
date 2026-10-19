/** Shared person-to-person AI-token contract used by web, Expo and desktop. */
/** Canonical wallet endpoint paths relative to the `/api/v1` base. */
export const WALLET_PATHS = {
    wallet: "/wallet",
    activity: "/wallet/activity",
    purchaseQuotes: "/wallet/purchase-quotes",
    checkout: "/wallet/checkout",
    recipients: (handle) => `/wallet/recipients/${encodeURIComponent(handle)}`,
    sources: "/wallet/sources",
    receiveAddresses: "/wallet/receive-addresses",
    destinations: "/wallet/destinations",
    destination: (destinationId) => `/wallet/destinations/${encodeURIComponent(destinationId)}`,
    destinationBalance: (destinationId) => `/wallet/destinations/${encodeURIComponent(destinationId)}/balance`,
    destinationActivity: (destinationId) => `/wallet/destinations/${encodeURIComponent(destinationId)}/activity`,
    transferPolicy: "/wallet/transfer-policy",
    transferChallenges: "/wallet/transfer-challenges",
    savedRecipients: "/wallet/saved-recipients",
    savedRecipient: (savedRecipientId) => `/wallet/saved-recipients/${encodeURIComponent(savedRecipientId)}`,
    transfers: "/wallet/transfers",
    transfer: (transferId) => `/wallet/transfers/${encodeURIComponent(transferId)}`,
};
/** Render a handle with `@` while leaving a shareable Mint address intact. */
export function formatWalletDestination(value) {
    const destination = value.trim().replace(/^@/, "");
    return destination.startsWith("ait1") || /^(workspace|agent|service):/.test(destination)
        ? destination
        : `@${destination}`;
}
/** Parse a positive decimal USD string into exact integer micros. */
export function parseUsdMicros(value) {
    const match = /^(\d+)(?:\.(\d{0,6}))?$/.exec(value.trim());
    if (!match)
        return null;
    const whole = Number(match[1]);
    const fraction = Number((match[2] ?? "").padEnd(6, "0"));
    const micros = whole * 1_000_000 + fraction;
    if (!Number.isSafeInteger(micros) || micros <= 0)
        return null;
    return micros;
}
