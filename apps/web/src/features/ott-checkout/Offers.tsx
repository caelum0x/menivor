"use client";

import * as React from "react";
import { readSession, ViewerSignIn } from "@/src/features/ott-auth";
import { formatPrice, hasUnlock, publicOffers, startCheckout, type Offer } from "./api";

const LABEL: Record<Offer["kind"], string> = { svod: "Subscribe", tvod: "Buy", rental: "Rent" };

/** What the channel sells; one tap to the creator's own checkout (sign-in first if needed). */
export function Offers({ handle, titleId }: Readonly<{ handle: string; titleId?: string }>) {
  const [offers, setOffers] = React.useState<readonly Offer[]>([]);
  const [open, setOpen] = React.useState(false);
  const [pending, setPending] = React.useState<Offer | null>(null);
  const [error, setError] = React.useState("");
  const [returning, setReturning] = React.useState(false);

  // Back from the creator's hosted checkout: wait for the grant event, then reload without the marker.
  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const session = readSession(handle);
    if (params.get("purchase") !== "done" || !session) return undefined;
    setReturning(true);
    let tries = 0;
    const timer = setInterval(async () => {
      tries += 1;
      if (await hasUnlock(handle, session.session, titleId).catch(() => false)) {
        clearInterval(timer);
        window.location.replace(window.location.pathname);
      } else if (tries >= 15) {
        clearInterval(timer);
        setReturning(false);
        setError("We have not received the purchase yet. It can take a minute. Reload soon.");
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [handle, titleId]);

  React.useEffect(() => {
    let live = true;
    publicOffers(handle).then((data) => {
      if (!live) return;
      setOpen(data.checkout_open);
      setOffers(data.offers.filter((o) => o.kind === "svod" || !titleId || o.title_id === titleId));
    });
    return () => {
      live = false;
    };
  }, [handle, titleId]);

  const buy = async (offer: Offer, session: string) => {
    try {
      window.location.assign(await startCheckout(handle, session, offer.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Checkout could not open. Try again.");
    }
  };

  if (returning) return <p aria-live="polite" className="mb-6 text-sm">Finishing your purchase</p>;
  if (!open || offers.length === 0) return error ? <p role="alert" className="mb-6 text-sm">{error}</p> : null;
  return (
    <section className="mb-6 space-y-2" aria-label="Watch everything on this channel">
      <ul className="flex flex-wrap gap-2">
        {offers.map((offer) => (
          <li key={offer.id}>
            <button type="button" className="rounded-lg bg-foreground px-3 py-2 text-sm text-background" onClick={() => {
              const session = readSession(handle);
              if (session) void buy(offer, session.session);
              else setPending(offer);
            }}>
              {LABEL[offer.kind]}: {offer.name}, {formatPrice(offer)}
            </button>
          </li>
        ))}
      </ul>
      {pending ? (
        <ViewerSignIn handle={handle} onSignedIn={(stored) => void buy(pending, stored.session)} />
      ) : null}
      <p className="text-xs text-muted-foreground">You pay the creator directly on their checkout page.</p>
      {error ? <p role="alert" className="text-sm">{error}</p> : null}
    </section>
  );
}
