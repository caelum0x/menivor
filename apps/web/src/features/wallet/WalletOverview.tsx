"use client";

import * as React from "react";
import Link from "next/link";
import { UserButton } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  Check,
  Coins,
  ExternalLink,
  ReceiptText,
  RefreshCw,
  Send,
  Wallet,
} from "lucide-react";
import {
  formatWalletDestination,
  parseUsdMicros,
} from "@reelforge/api-contract";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { WalletNav } from "@/components/wallet/WalletNav";
import { ApiError } from "@/src/shared/api";
import {
  formatUsdMicros,
  isDefinitiveTransferFailureStatus,
  microsToUsdString,
  newTransferIdempotencyKey,
  type CheckoutResult,
  type WalletBalance,
  type WalletSavedRecipient,
  type WalletSource,
  type WalletTransferChallenge,
  type WalletTransferResult,
} from "./api";
import { useWallet } from "./use-wallet";
import { WalletDestinations } from "./WalletDestinations";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Fixed top-up packages (micros) offered alongside a custom amount. */
const PACKAGES: ReadonlyArray<{ id: string; label: string; micros: number }> = [
  { id: "starter_10", label: "$10", micros: 10_000_000 },
  { id: "creator_25", label: "$25", micros: 25_000_000 },
  { id: "pro_100", label: "$100", micros: 100_000_000 },
];

const LAST_TRANSFER_ID = "menivor.wallet.lastTransferId";
const PENDING_TRANSFER = "menivor.wallet.pendingTransfer";

interface PendingTransferV2 {
  version: 2;
  sourceAccountId: string;
  sourceKind: "personal" | "workspace";
  sourceLabel: string;
  challengeId: string;
  challengeExpiresAt: string;
  recipientHandle: string;
  amountMicros: number;
  idempotencyKey: string;
  /** True only after the irreversible POST was initiated. */
  submitted: boolean;
}

interface PendingTransferLegacy {
  version: 1;
  recipientHandle: string;
  amountMicros: number;
  idempotencyKey: string;
  submitted: boolean;
}

type PendingTransfer = PendingTransferV2 | PendingTransferLegacy;

function canonicalDestination(value: string): string {
  const destination = value.trim().replace(/^@/, "");
  return destination.startsWith("ait1")
    ? destination
    : destination.toLocaleLowerCase();
}

function isPendingV2(pending: PendingTransfer): pending is PendingTransferV2 {
  return pending.version === 2;
}

function parseUsdToMicros(value: string): number | null {
  const usd = Number(value.trim());
  if (!Number.isFinite(usd) || usd <= 0) return null;
  return Math.round(usd * 1_000_000);
}

/** Wallet home — live balance, plan, and a real top-up form that POSTs. */
export function WalletOverview() {
  const {
    balance,
    loading,
    error,
    refresh,
    checkout,
    submitting,
    checkoutError,
    sources,
    sourcesLoading,
    loadSourceBalance,
    loadReceiveAddress,
    reviewTransfer,
    listSavedRecipients,
    saveRecipient,
    deleteRecipient,
    send,
    sending,
    recoverTransfer,
    recoveringTransfer,
    transferError,
    destinations,
    destinationsLoading,
    createDestination,
    setDestinationActive,
    loadDestinationBalance,
  } = useWallet();

  const [amount, setAmount] = React.useState("20.00");
  const [result, setResult] = React.useState<CheckoutResult | null>(null);
  const [recipientHandle, setRecipientHandle] = React.useState("");
  const [transferAmount, setTransferAmount] = React.useState("5.00");
  const [selectedSourceId, setSelectedSourceId] = React.useState("");
  const [sourceBalance, setSourceBalance] = React.useState<WalletBalance | null>(null);
  const [receiveAddress, setReceiveAddress] = React.useState("");
  const [challenge, setChallenge] = React.useState<WalletTransferChallenge | null>(null);
  const [savedRecipients, setSavedRecipients] = React.useState<WalletSavedRecipient[]>([]);
  const [savedRecipientId, setSavedRecipientId] = React.useState<string | undefined>();
  const [transferResult, setTransferResult] =
    React.useState<WalletTransferResult | null>(null);
  const [recipientError, setRecipientError] = React.useState("");
  const [resolving, setResolving] = React.useState(false);
  const [transferId, setTransferId] = React.useState("");
  const [pendingTransfer, setPendingTransfer] =
    React.useState<PendingTransfer | null>(null);

  React.useEffect(() => {
    try {
      setTransferId(window.localStorage.getItem(LAST_TRANSFER_ID) ?? "");
      const encoded = window.localStorage.getItem(PENDING_TRANSFER);
      if (!encoded) return;
      const pending = JSON.parse(encoded) as Record<string, unknown>;
      if (
        typeof pending.recipientHandle === "string" &&
        typeof pending.amountMicros === "number" &&
        typeof pending.idempotencyKey === "string"
      ) {
        const restored: PendingTransfer = pending.version === 2 &&
          typeof pending.sourceAccountId === "string" &&
          typeof pending.sourceKind === "string" &&
          typeof pending.sourceLabel === "string" &&
          typeof pending.challengeId === "string" &&
          typeof pending.challengeExpiresAt === "string"
          ? {
              version: 2,
              sourceAccountId: pending.sourceAccountId,
              sourceKind: pending.sourceKind as "personal" | "workspace",
              sourceLabel: pending.sourceLabel as string,
              challengeId: pending.challengeId as string,
              challengeExpiresAt: pending.challengeExpiresAt as string,
              recipientHandle: pending.recipientHandle as string,
              amountMicros: pending.amountMicros as number,
              idempotencyKey: pending.idempotencyKey as string,
              submitted: pending.submitted === true,
            }
          : {
              version: 1,
              recipientHandle: pending.recipientHandle as string,
              amountMicros: pending.amountMicros as number,
              idempotencyKey: pending.idempotencyKey as string,
              // Legacy records predate reviewed challenges. Treat them as
              // submitted and bind them only to the personal source later.
              submitted: true,
            };
        setPendingTransfer(restored);
        setRecipientHandle(restored.recipientHandle);
        setTransferAmount(
          (restored.amountMicros / 1_000_000)
            .toFixed(6)
            .replace(/0+$/, "")
            .replace(/\.$/, ""),
        );
      }
    } catch {
      // Storage may be unavailable; the in-memory idempotency key still works.
    }
  }, []);

  const selectedSource = React.useMemo(
    () => sources.find((source) => source.source_account_id === selectedSourceId) ?? null,
    [selectedSourceId, sources],
  );

  React.useEffect(() => {
    if (sources.length === 0 || selectedSourceId) return;
    const restored = pendingTransfer && isPendingV2(pendingTransfer)
      ? sources.find((source) => source.source_account_id === pendingTransfer.sourceAccountId)
      : sources.find((source) => source.kind === "personal");
    const fallback = restored ?? sources.find((source) => source.can_send) ?? sources[0];
    if (fallback) setSelectedSourceId(fallback.source_account_id);
  }, [pendingTransfer, selectedSourceId, sources]);

  React.useEffect(() => {
    if (!selectedSourceId) return;
    let active = true;
    void Promise.all([
      loadSourceBalance(selectedSourceId),
      loadReceiveAddress(selectedSourceId),
      listSavedRecipients(selectedSourceId),
    ]).then(([nextBalance, receive, recipients]) => {
      if (!active) return;
      setSourceBalance(nextBalance);
      setReceiveAddress(receive.address);
      setSavedRecipients(recipients);
    }).catch(() => {
      if (!active) return;
      setSourceBalance(null);
      setReceiveAddress("");
      setSavedRecipients([]);
    });
    return () => { active = false; };
  }, [listSavedRecipients, loadReceiveAddress, loadSourceBalance, selectedSourceId]);

  const rememberTransfer = React.useCallback((transfer: WalletTransferResult) => {
    setTransferId(transfer.transfer_id);
    try {
      window.localStorage.setItem(LAST_TRANSFER_ID, transfer.transfer_id);
    } catch {
      // The recovered result remains visible even when storage is unavailable.
    }
  }, []);

  const rememberPending = React.useCallback((pending: PendingTransfer) => {
    setPendingTransfer(pending);
    try {
      window.localStorage.setItem(PENDING_TRANSFER, JSON.stringify(pending));
    } catch {
      // The pending operation remains protected for this session.
    }
  }, []);

  const clearPending = React.useCallback(() => {
    setPendingTransfer(null);
    try {
      window.localStorage.removeItem(PENDING_TRANSFER);
    } catch {
      // Nothing else is required once the server returned a definitive result.
    }
  }, []);

  const onTopupAmount = React.useCallback(async () => {
    const micros = parseUsdToMicros(amount);
    if (micros === null) return;
    setResult(null);
    try {
      setResult(await checkout({ amount_usd: microsToUsdString(micros) }));
    } catch {
      /* checkoutError is surfaced by the hook */
    }
  }, [amount, checkout]);

  const onTopupPackage = React.useCallback(
    async (micros: number) => {
      setResult(null);
      try {
        setResult(await checkout({ amount_usd: microsToUsdString(micros) }));
      } catch {
        /* checkoutError is surfaced by the hook */
      }
    },
    [checkout],
  );

  const amountInvalid = parseUsdToMicros(amount) === null;
  const transferMicros = parseUsdMicros(transferAmount);
  const transferInvalid =
    transferMicros === null ||
    transferMicros > 1_000_000_000 ||
    transferMicros > (sourceBalance?.available_micros ?? 0) ||
    !selectedSource?.can_send ||
    (selectedSource.limits.per_transfer_micros > 0 &&
      transferMicros > selectedSource.limits.per_transfer_micros) ||
    (selectedSource.limits.daily_remaining_micros !== null &&
      transferMicros > selectedSource.limits.daily_remaining_micros);
  const submittedRetry = pendingTransfer && isPendingV2(pendingTransfer) && pendingTransfer.submitted
    ? pendingTransfer
    : null;

  const invalidateReview = React.useCallback(() => {
    setChallenge(null);
    setTransferResult(null);
    if (pendingTransfer && !pendingTransfer.submitted) clearPending();
  }, [clearPending, pendingTransfer]);

  const onRecipientChange = React.useCallback(
    (value: string) => {
      setRecipientHandle(value);
      setSavedRecipientId(undefined);
      setRecipientError("");
      invalidateReview();
    },
    [invalidateReview],
  );

  const onReviewTransfer = React.useCallback(async () => {
    if (transferMicros === null || transferInvalid) return;
    if (
      pendingTransfer?.submitted &&
      (canonicalDestination(pendingTransfer.recipientHandle) !== canonicalDestination(recipientHandle) ||
        pendingTransfer.amountMicros !== transferMicros ||
        (isPendingV2(pendingTransfer)
          ? pendingTransfer.sourceAccountId !== selectedSourceId
          : selectedSource?.kind !== "personal"))
    ) {
      setRecipientError(
        `Resolve the pending ${formatUsdMicros(pendingTransfer.amountMicros)} transfer to ${formatWalletDestination(pendingTransfer.recipientHandle)} before starting another send.`,
      );
      return;
    }
    setRecipientError("");
    setTransferResult(null);
    setResolving(true);
    try {
      if (!selectedSource) throw new Error("Choose a transfer source.");
      const matchingPending = pendingTransfer &&
        canonicalDestination(pendingTransfer.recipientHandle) === canonicalDestination(recipientHandle) &&
        pendingTransfer.amountMicros === transferMicros &&
        (isPendingV2(pendingTransfer)
          ? pendingTransfer.sourceAccountId === selectedSource.source_account_id
          : selectedSource.kind === "personal")
        ? pendingTransfer : null;
      const key = matchingPending?.idempotencyKey ?? newTransferIdempotencyKey();
      const reviewed = await reviewTransfer({
        source_account_id: selectedSource.source_account_id,
        recipient_handle: recipientHandle,
        saved_recipient_id: savedRecipientId,
        amount_micros: transferMicros,
      }, key);
      if (Date.parse(reviewed.expires_at) <= Date.now() && !matchingPending?.submitted) {
        clearPending();
        setRecipientError("That review expired. Review again to create a fresh sealed transfer.");
        return;
      }
      const next: PendingTransferV2 = {
        version: 2,
        sourceAccountId: reviewed.source.source_account_id,
        sourceKind: reviewed.source.kind,
        sourceLabel: reviewed.source.label,
        challengeId: reviewed.challenge_id,
        challengeExpiresAt: reviewed.expires_at,
        recipientHandle: reviewed.recipient.handle,
        amountMicros: reviewed.amount_micros,
        idempotencyKey: key,
        submitted: matchingPending?.submitted ?? false,
      };
      setChallenge(reviewed);
      rememberPending(next);
    } catch (err) {
      setRecipientError(
        friendlyErrorMessage(err, "Recipient handle not found."),
      );
    } finally {
      setResolving(false);
    }
  }, [clearPending, pendingTransfer, recipientHandle, rememberPending, reviewTransfer, savedRecipientId, selectedSource, selectedSourceId, transferInvalid, transferMicros]);

  const onConfirmTransfer = React.useCallback(async () => {
    if (!pendingTransfer || !isPendingV2(pendingTransfer)) return;
    // Once POST started, current RBAC/balance/limits/expiry cannot prove its
    // outcome. Retry the persisted command exactly; server idempotency decides.
    if (!pendingTransfer.submitted && (!challenge || transferMicros === null || transferInvalid)) return;
    setTransferResult(null);
    try {
      const submitted = { ...pendingTransfer, submitted: true };
      rememberPending(submitted);
      const sent = await send({
        source_account_id: submitted.sourceAccountId,
        challenge_id: submitted.challengeId,
        recipient_handle: submitted.recipientHandle,
        amount_micros: submitted.amountMicros,
      }, submitted.idempotencyKey);
      setTransferResult(sent);
      rememberTransfer(sent);
      clearPending();
      setChallenge(null);
      if (sent.sender_balance) {
        setSourceBalance((current) => current ? {
          ...current,
          available_micros: sent.sender_balance!.available_micros,
          reserved_micros: sent.sender_balance!.held_micros,
        } : current);
      }
    } catch (reason) {
      if (
        reason instanceof ApiError &&
        isDefinitiveTransferFailureStatus(reason.status)
      ) {
        clearPending();
      }
      /* transferError is surfaced by the hook */
    }
  }, [challenge, clearPending, pendingTransfer, rememberPending, rememberTransfer, send, transferInvalid, transferMicros]);

  const onRecoverTransfer = React.useCallback(async () => {
    if (!transferId.trim()) return;
    setTransferResult(null);
    try {
      const recovered = await recoverTransfer(transferId);
      setTransferResult(recovered);
      rememberTransfer(recovered);
      if (
        !pendingTransfer ||
        (canonicalDestination(pendingTransfer.recipientHandle) === canonicalDestination(recovered.recipient.handle) &&
          pendingTransfer.amountMicros === recovered.amount_micros &&
          (isPendingV2(pendingTransfer)
            ? pendingTransfer.sourceAccountId === recovered.source.source_account_id
            : recovered.source.kind === "personal"))
      ) {
        clearPending();
      }
      setChallenge(null);
    } catch {
      /* transferError is surfaced by the hook */
    }
  }, [clearPending, pendingTransfer, recoverTransfer, rememberTransfer, transferId]);

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wallet className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Wallet</h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refresh()}
            disabled={loading}
          >
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden /> Refresh
          </Button>
          <Link
            href="/wallet/activity"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ReceiptText className="h-4 w-4" aria-hidden /> Activity
          </Link>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      <WalletNav />

      {loading && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      )}

      {!loading && error && (
        <Card>
          <CardContent className="flex items-center gap-3 py-6 text-destructive">
            <AlertTriangle className="h-5 w-5" aria-hidden />
            <div>
              <p>{error}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => void refresh()}
              >
                Try again
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {!loading && !error && balance && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Card>
              <CardContent className="py-6">
                <p className="text-sm text-muted-foreground">Available</p>
                <p className="mt-1 text-3xl font-semibold tabular-nums">
                  {formatUsdMicros(balance.available_micros)}
                </p>
                {balance.plan && (
                  <p className="mt-2 text-xs uppercase tracking-wide text-muted-foreground">
                    {balance.plan} plan
                  </p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-6">
                <p className="text-sm text-muted-foreground">Reserved (in-flight)</p>
                <p className="mt-1 text-3xl font-semibold tabular-nums">
                  {formatUsdMicros(balance.reserved_micros)}
                </p>
              </CardContent>
            </Card>
          </div>

          <section className="mt-8">
            <h2 className="mb-3 flex items-center gap-2 text-lg font-medium">
              <Send className="h-5 w-5 text-primary" aria-hidden /> Send AI tokens
            </h2>
            <Card>
              <CardContent className="space-y-4 py-6">
                <p className="text-sm text-muted-foreground">
                  Choose an authorized personal or workspace balance. The server
                  seals the exact source, recipient, amount and limits before send.
                </p>
                {pendingTransfer && (
                  <p className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm text-amber-800">
                    {pendingTransfer.submitted ? "Unresolved" : "Reviewed"} logical
                    transfer: {formatUsdMicros(pendingTransfer.amountMicros)} from{" "}
                    {isPendingV2(pendingTransfer) ? pendingTransfer.sourceLabel : "Personal wallet"}
                    {" "}to {formatWalletDestination(pendingTransfer.recipientHandle)}.{" "}
                    {pendingTransfer.submitted
                      ? "Review and confirm again to reuse its original key, or recover it below. A different send is blocked."
                      : "It becomes irreversible only after Confirm send."}
                  </p>
                )}
                <div className="grid gap-1">
                  <Label htmlFor="transfer-source">Source</Label>
                  <Select
                    id="transfer-source"
                    value={selectedSourceId}
                    disabled={sourcesLoading || Boolean(pendingTransfer?.submitted)}
                    onChange={(event) => {
                      setSelectedSourceId(event.target.value);
                      setSourceBalance(null);
                      setReceiveAddress("");
                      setSavedRecipientId(undefined);
                      invalidateReview();
                    }}
                  >
                    <option value="" disabled>Choose a wallet</option>
                    {sources.map((source) => (
                      <option key={source.source_account_id} value={source.source_account_id} disabled={!source.can_send}>
                        {source.label} · {source.kind}{source.can_send ? "" : " · view only"}
                      </option>
                    ))}
                  </Select>
                  {selectedSource && (
                    <div className="space-y-1 text-xs text-muted-foreground">
                      <p>
                        Available {sourceBalance ? formatUsdMicros(sourceBalance.available_micros) : "loading…"}
                        {selectedSource.limits.daily_remaining_micros === null
                          ? " · no daily cap"
                          : ` · ${formatUsdMicros(selectedSource.limits.daily_remaining_micros)} remaining today`}
                      </p>
                      <p className="break-all font-mono tabular-nums">
                        Receive address: {receiveAddress || "loading…"}
                      </p>
                    </div>
                  )}
                </div>
                {savedRecipients.length > 0 && (
                  <div className="flex flex-wrap gap-2" aria-label="Saved recipients">
                    {savedRecipients.map((saved) => (
                      <span key={saved.saved_recipient_id} className="inline-flex items-center rounded-full border bg-secondary/40 text-xs">
                        <button
                          type="button"
                          className="px-3 py-1.5"
                          onClick={() => {
                            setSavedRecipientId(saved.saved_recipient_id);
                            setRecipientHandle(saved.handle);
                            invalidateReview();
                          }}
                        >
                          {saved.label || saved.display_name} · @{saved.handle}
                        </button>
                        <button
                          type="button"
                          aria-label={`Delete saved recipient ${saved.handle}`}
                          className="border-l px-2 py-1.5 text-muted-foreground hover:text-destructive"
                          onClick={() => void deleteRecipient(selectedSourceId, saved.saved_recipient_id).then(() => {
                            setSavedRecipients((current) => current.filter((item) => item.saved_recipient_id !== saved.saved_recipient_id));
                          })}
                        >×</button>
                      </span>
                    ))}
                  </div>
                )}
                <div className="grid gap-3 sm:grid-cols-[1fr_10rem_auto] sm:items-end">
                  <div className="grid gap-1">
                    <Label htmlFor="transfer-handle">Recipient handle</Label>
                    <Input
                      id="transfer-handle"
                      autoCapitalize="none"
                      autoComplete="off"
                      placeholder="@creator or ait1…"
                      value={recipientHandle}
                      onChange={(event) => onRecipientChange(event.target.value)}
                    />
                  </div>
                  <div className="grid gap-1">
                    <Label htmlFor="transfer-amount">Amount (USD)</Label>
                    <Input
                      id="transfer-amount"
                      inputMode="decimal"
                      value={transferAmount}
                      onChange={(event) => {
                        setTransferAmount(event.target.value);
                        invalidateReview();
                      }}
                    />
                  </div>
                  <Button
                    variant="outline"
                    disabled={
                      resolving ||
                      sending ||
                      !recipientHandle.trim() ||
                      !selectedSource ||
                      transferInvalid
                    }
                    onClick={() => void onReviewTransfer()}
                  >
                    {resolving ? "Checking…" : "Review"}
                  </Button>
                </div>

                {(challenge || submittedRetry) && (
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-primary/30 bg-primary/5 p-4">
                    <div className="space-y-1 text-sm">
                      <p className="font-medium">{challenge ? "Sealed transfer review" : "Exact unresolved transfer"}</p>
                      <p><strong>{formatUsdMicros(challenge?.amount_micros ?? submittedRetry!.amountMicros)}</strong> from <strong>{challenge?.source.label ?? submittedRetry!.sourceLabel}</strong></p>
                      <p>To <strong>{formatWalletDestination(challenge?.recipient.handle ?? submittedRetry!.recipientHandle)}</strong>{challenge ? ` (${challenge.recipient.display_name})` : ""}</p>
                      {challenge && <p className="text-xs text-muted-foreground">
                        Expires {new Date(challenge.expires_at).toLocaleTimeString()} · per-transfer limit {formatUsdMicros(challenge.source.limits.per_transfer_micros)}
                      </p>}
                    </div>
                    <Button
                      disabled={sending}
                      onClick={() => void onConfirmTransfer()}
                    >
                      {sending ? "Sending…" : submittedRetry ? "Retry exact send" : "Confirm send"}
                    </Button>
                  </div>
                )}

                {transferInvalid && transferAmount.trim() && !submittedRetry && (
                  <p className="text-sm text-destructive">
                    Enter a positive amount no greater than your available balance
                    or $1,000.
                  </p>
                )}
                {(recipientError || transferError) && (
                  <p className="text-sm text-destructive">
                    {recipientError || transferError}
                  </p>
                )}
                {transferResult && (
                  <div className="space-y-1 text-sm text-emerald-700">
                    <p className="flex items-center gap-2">
                      <Check className="h-4 w-4" aria-hidden /> Sent{" "}
                      {formatUsdMicros(transferResult.amount_micros)} to{" "}
                      {formatWalletDestination(transferResult.recipient.handle)}.
                    </p>
                    <p>From {transferResult.source.label}</p>
                    {transferResult.recipient.kind === "personal" && !transferResult.recipient.handle.startsWith("ait1") && !savedRecipients.some((saved) => canonicalDestination(saved.handle) === canonicalDestination(transferResult.recipient.handle)) && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void saveRecipient(transferResult.source.source_account_id, transferResult.recipient.handle).then((saved) => {
                          setSavedRecipients((current) => [...current, saved]);
                        })}
                      >Save recipient</Button>
                    )}
                    <p className="font-mono text-xs">Transfer {transferResult.transfer_id}</p>
                    {transferResult.receipt_proof && (
                      <p className="font-mono text-xs">
                        Signed Mint receipt {transferResult.receipt_proof.receipt_hash}
                      </p>
                    )}
                  </div>
                )}

                <div className="grid gap-3 border-t pt-4 sm:grid-cols-[1fr_auto] sm:items-end">
                  <div className="grid gap-1">
                    <Label htmlFor="recover-transfer-id">Existing transfer ID</Label>
                    <Input
                      id="recover-transfer-id"
                      autoCapitalize="none"
                      autoComplete="off"
                      placeholder="Recover after an uncertain response"
                      value={transferId}
                      onChange={(event) => setTransferId(event.target.value)}
                    />
                  </div>
                  <Button
                    variant="outline"
                    disabled={recoveringTransfer || !transferId.trim()}
                    onClick={() => void onRecoverTransfer()}
                  >
                    {recoveringTransfer ? "Recovering…" : "Recover transfer"}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Recovery only reads an existing sender-owned transfer; it never
                  sends tokens again.
                </p>
              </CardContent>
            </Card>
          </section>

          <WalletDestinations
            sources={sources}
            destinations={destinations}
            loading={destinationsLoading}
            createDestination={createDestination}
            setDestinationActive={setDestinationActive}
            loadBalance={loadDestinationBalance}
          />

          <section className="mt-8">
            <h2 className="mb-3 flex items-center gap-2 text-lg font-medium">
              <Coins className="h-5 w-5 text-primary" aria-hidden /> Add wallet credit
            </h2>
            <Card>
              <CardContent className="space-y-5 py-6">
                <div className="flex flex-wrap gap-2">
                  {PACKAGES.map((pkg) => (
                    <Button
                      key={pkg.id}
                      variant="outline"
                      disabled={submitting}
                      onClick={() => void onTopupPackage(pkg.micros)}
                    >
                      {pkg.label}
                    </Button>
                  ))}
                </div>

                <div className="flex flex-wrap items-end gap-3 border-t pt-4">
                  <div className="grid gap-1">
                    <Label htmlFor="topup-amount">Custom amount (USD)</Label>
                    <Input
                      id="topup-amount"
                      inputMode="decimal"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      className="w-40"
                    />
                  </div>
                  <Button
                    onClick={() => void onTopupAmount()}
                    disabled={submitting || amountInvalid}
                  >
                    {submitting ? "Processing…" : "Add credit"}
                  </Button>
                </div>

                {amountInvalid && amount.trim().length > 0 && (
                  <p className="text-sm text-destructive">
                    Enter an amount greater than $0.
                  </p>
                )}

                {checkoutError && (
                  <p className="text-sm text-destructive">{checkoutError}</p>
                )}

                {result && (
                  <CheckoutOutcome result={result} />
                )}
              </CardContent>
            </Card>
          </section>
        </>
      )}
    </main>
  );
}

function CheckoutOutcome({ result }: { result: CheckoutResult }) {
  if (result.checkout_url) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
        <ExternalLink className="h-4 w-4 text-primary" aria-hidden />
        <a
          href={result.checkout_url}
          className="font-medium text-primary underline"
          rel="noreferrer"
        >
          Complete your payment to add {formatUsdMicros(result.credit_micros)} to
          your wallet
        </a>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-sm text-emerald-700">
      <Check className="h-4 w-4" aria-hidden />
      Top-up of {formatUsdMicros(result.credit_micros)} started. Complete payment,
      then refresh to see your new balance.
    </div>
  );
}
