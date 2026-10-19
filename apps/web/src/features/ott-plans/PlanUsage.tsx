"use client";

import * as React from "react";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { getOttPlan, METER_LABELS, setOttOverage, type OttPlanView } from "./api";

/** This month's OTT usage against the plan's caps, and the overage switch (off until the creator turns it on). */
export function PlanUsage() {
  const getApiToken = useApiToken();
  const [view, setView] = React.useState<OttPlanView | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const next = await getOttPlan({ token: await getApiToken() });
        if (live) setView(next);
      } catch (err) {
        if (live) setError(friendlyErrorMessage(err, "Your plan usage could not load."));
      }
    })();
    return () => {
      live = false;
    };
  }, [getApiToken]);

  if (error) return <p role="alert" className="text-sm">{error}</p>;
  if (!view) return null;

  const toggle = async () => {
    try {
      setView(await setOttOverage(!view.overage.opted_in, { token: await getApiToken() }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "The overage setting could not be saved."));
    }
  };

  return (
    <section aria-label="Channel usage this month" className="space-y-2 rounded-xl border border-border p-3">
      <h2 className="text-sm font-semibold">Usage this month on your {view.plan} plan</h2>
      <ul className="grid grid-cols-2 gap-2 text-sm">
        {view.meters.map((m) => (
          <li key={m.meter} data-meter={m.meter}>
            {METER_LABELS[m.meter]}: {Math.round(m.used)} of {Math.round(m.included)} {m.unit}
            {m.at_cap ? " (limit reached)" : ""}
          </li>
        ))}
      </ul>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={view.overage.opted_in} onChange={() => void toggle()} />
        Keep going past my limits and bill the extra
      </label>
    </section>
  );
}
