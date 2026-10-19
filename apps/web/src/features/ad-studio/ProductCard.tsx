"use client";

import * as React from "react";
import { ExternalLink, Star } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatPrice, type Product } from "./api";

const SOURCE_LABELS: Record<string, string> = {
  trendyol: "Trendyol",
  amazon: "Amazon",
  shopify: "Shopify",
  manual: "Entered manually",
  generic: "Web page",
};

/** Extracted product facts; `images` overrides the remote image list. */
export function ProductCard({ product, images }: { product: Product; images?: string[] }) {
  const price = formatPrice(product.price, product.currency, product.language);
  const original = formatPrice(product.original_price, product.currency, product.language);
  const gallery = (images ?? product.images).slice(0, 6);
  return (
    <Card>
      <CardContent className="grid gap-4 p-4 md:grid-cols-[220px_1fr]">
        <div className="grid grid-cols-3 gap-2 md:grid-cols-2">
          {gallery.length === 0 ? (
            <p className="col-span-full text-sm text-muted-foreground">No product images found.</p>
          ) : (
            gallery.map((src, i) => (
              // eslint-disable-next-line @next/next/no-img-element -- remote store / presigned media
              <img
                key={`${src}-${i}`}
                src={src}
                alt={`${product.title} image ${i + 1}`}
                className="aspect-square w-full rounded-md border border-border bg-secondary/40 object-contain"
                referrerPolicy="no-referrer"
              />
            ))
          )}
        </div>
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{SOURCE_LABELS[product.source] ?? product.source}</Badge>
            {product.brand ? <Badge variant="outline">{product.brand}</Badge> : null}
          </div>
          <h2 className="text-lg font-semibold leading-snug">{product.title}</h2>
          {price ? (
            <p className="text-base">
              <span className="font-semibold">{price}</span>
              {original ? (
                <span className="ml-2 text-sm text-muted-foreground line-through">{original}</span>
              ) : null}
            </p>
          ) : null}
          {product.rating ? (
            <p className="flex items-center gap-1 text-sm text-muted-foreground">
              <Star className="h-4 w-4" aria-hidden />
              {product.rating.toFixed(1)} / 5
              {product.review_count ? ` from ${product.review_count} reviews` : ""}
            </p>
          ) : null}
          {product.bullets.length > 0 ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {product.bullets.slice(0, 5).map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          ) : product.description ? (
            <p className="text-sm text-muted-foreground">{product.description.slice(0, 280)}</p>
          ) : null}
          {product.url ? (
            <a
              href={product.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              View product page <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
