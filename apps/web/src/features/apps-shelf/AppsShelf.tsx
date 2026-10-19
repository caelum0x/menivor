"use client";

import * as React from "react";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { AppUse } from "./AppUse";
import { listApps, priceText, type ShelfApp } from "./api";

/** Tiles with a moving preview and the price; tapping one opens its single input screen. */
export function AppsShelf() {
  const [apps, setApps] = React.useState<readonly ShelfApp[] | null>(null);
  const [open, setOpen] = React.useState<ShelfApp | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    listApps()
      .then((list) => live && setApps(list))
      .catch((err) => live && setError(friendlyErrorMessage(err, "The apps could not load.")));
    return () => {
      live = false;
    };
  }, []);

  if (error) return <p role="alert">{error}</p>;
  if (apps === null) return <p className="text-sm text-muted-foreground">Loading</p>;
  if (apps.length === 0) return <p className="text-sm">New apps arrive here once their previews are ready.</p>;
  if (open) {
    return (
      <div className="space-y-4">
        <button type="button" className="text-sm underline" onClick={() => setOpen(null)}>All apps</button>
        <AppUse app={open} />
      </div>
    );
  }
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {apps.map((app) => (
        <li key={app.id}>
          <button type="button" className="w-full text-left" onClick={() => setOpen(app)}>
            <video className="aspect-[9/16] w-full rounded-xl object-cover" src={app.preview_url} muted loop autoPlay playsInline aria-hidden />
            <span className="mt-2 block font-medium">{app.name}</span>
            <span className="block text-xs text-muted-foreground">{app.blurb}</span>
            <span className="block text-xs">{priceText(app.price)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
