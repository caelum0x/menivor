"use client";

import * as React from "react";
import { Download, Receipt } from "lucide-react";
import type { Invoice } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  formatCents,
  formatDate,
  invoiceStatusVariant,
  invoiceToCsv,
  statusLabel,
} from "./format";

export interface InvoicesCardProps {
  invoices: readonly Invoice[];
  /** Whether the invoices surface is available to the caller (`billing.manage`). */
  canManage: boolean;
}

/**
 * The workspace's invoices, newest first. Amounts are the exact integer-cents
 * sum rendered in each invoice's own currency. Download builds a CSV receipt
 * client-side from the invoice the tenant already holds — it never calls another
 * endpoint and so can never surface another tenant's data. Only rendered to
 * callers with `billing.manage`.
 */
export function InvoicesCard({
  invoices,
  canManage,
}: Readonly<InvoicesCardProps>) {
  if (!canManage) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Receipt className="size-5 text-primary" aria-hidden />
          Invoices
        </CardTitle>
        <CardDescription>
          Billing history for this workspace, newest first.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {invoices.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No invoices yet. They appear here after your first paid billing
            cycle.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {invoices.map((invoice) => (
              <InvoiceRow key={invoice.id} invoice={invoice} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

interface InvoiceRowProps {
  invoice: Readonly<Invoice>;
}

function InvoiceRow({ invoice }: Readonly<InvoiceRowProps>) {
  const onDownload = React.useCallback(() => {
    downloadInvoiceCsv(invoice);
  }, [invoice]);

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <p className="flex items-center gap-2 font-medium tabular-nums">
          {formatCents(invoice.amount_cents, invoice.currency)}
          <Badge variant={invoiceStatusVariant(invoice.status)}>
            {statusLabel(invoice.status)}
          </Badge>
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {invoice.period_start && invoice.period_end
            ? `${formatDate(invoice.period_start)} – ${formatDate(invoice.period_end)}`
            : formatDate(invoice.created_at)}
        </p>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={onDownload}
        aria-label={`Download invoice ${invoice.id}`}
      >
        <Download className="size-4" aria-hidden /> Download
      </Button>
    </li>
  );
}

/**
 * Serialize one invoice to a CSV receipt and trigger a browser download. Guarded
 * for SSR (no `document`); the object URL is revoked after the click so the blob
 * is not leaked.
 */
function downloadInvoiceCsv(invoice: Readonly<Invoice>): void {
  if (typeof document === "undefined") return;
  const csv = invoiceToCsv(invoice);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `invoice-${invoice.id}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
