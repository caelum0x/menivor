"use client";

import * as React from "react";

import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { bpsToPercent, computeMargin, formatUsdMicros } from "./api";

/** Live margin model for agency resale — pure math, no network. */
export function MarginCalculator() {
  const [baseUsd, setBaseUsd] = React.useState(0.5);
  const [markupBps, setMarkupBps] = React.useState(3000); // 30%
  const [minFeeUsd, setMinFeeUsd] = React.useState(0.05);
  const [volume, setVolume] = React.useState(1000);

  const b = computeMargin(
    Math.round(baseUsd * 1_000_000),
    markupBps,
    Math.round(minFeeUsd * 1_000_000),
  );

  const rows: [string, string][] = [
    ["Your cost (base)", formatUsdMicros(b.base_micros)],
    [`Markup (${bpsToPercent(markupBps)}${b.min_fee_applied ? ", min fee applied" : ""})`, formatUsdMicros(b.markup_micros)],
    ["Client pays", formatUsdMicros(b.customer_micros)],
    ["Your margin", `${formatUsdMicros(b.margin_micros)} (${b.margin_pct}%)`],
  ];

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Margin calculator</h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Base cost ($)" value={baseUsd} step={0.01} onChange={setBaseUsd} />
        <Field label="Markup (bps)" value={markupBps} step={50} onChange={setMarkupBps} />
        <Field label="Min fee ($)" value={minFeeUsd} step={0.01} onChange={setMinFeeUsd} />
      </div>

      <Card>
        <CardContent className="divide-y p-0">
          {rows.map(([k, v], i) => (
            <div key={k} className="flex items-center justify-between px-4 py-3 text-sm">
              <span className={i === rows.length - 1 ? "font-semibold" : "text-muted-foreground"}>{k}</span>
              <span className={i === rows.length - 1 ? "font-semibold text-green-600" : ""}>{v}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex items-center justify-between py-4">
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">At</span>
            <Input
              type="number"
              value={volume}
              min={1}
              onChange={(e) => setVolume(Math.max(1, Number(e.target.value) || 1))}
              className="w-28"
            />
            <span className="text-sm text-muted-foreground">generations/mo</span>
          </div>
          <div className="text-right">
            <div className="text-2xl font-semibold text-green-600">
              {formatUsdMicros(b.margin_micros * volume)}
            </div>
            <div className="text-xs text-muted-foreground">projected monthly margin</div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, value, step, onChange }: { label: string; value: number; step: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium">{label}</label>
      <Input type="number" value={value} step={step} onChange={(e) => onChange(Number(e.target.value) || 0)} />
    </div>
  );
}
