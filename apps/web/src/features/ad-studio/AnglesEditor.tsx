"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AdAngle } from "./api";

const FIELDS: { key: "hook" | "pain" | "proof" | "offer" | "cta"; label: string }[] = [
  { key: "hook", label: "Hook" },
  { key: "pain", label: "Pain" },
  { key: "proof", label: "Proof" },
  { key: "offer", label: "Offer" },
  { key: "cta", label: "Call to action" },
];

/** Editable ad angles. Edits are local until the parent saves them. */
export function AnglesEditor({
  angles,
  onChange,
  disabled,
}: {
  angles: AdAngle[];
  onChange: (next: AdAngle[]) => void;
  disabled?: boolean;
}) {
  const update = (index: number, key: (typeof FIELDS)[number]["key"], value: string) => {
    onChange(angles.map((a, i) => (i === index ? { ...a, [key]: value, source: "edited" } : a)));
  };
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {angles.map((angle, index) => (
        <Card key={angle.id || index}>
          <CardContent className="space-y-2 p-4">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-medium">{angle.label}</h3>
              <Badge variant={angle.source === "llm" ? "default" : "secondary"}>
                {angle.source === "llm" ? "AI copy" : angle.source === "edited" ? "Edited" : "Draft"}
              </Badge>
            </div>
            {FIELDS.map((field) => (
              <div key={field.key} className="grid gap-1">
                <Label htmlFor={`${angle.id}-${field.key}`} className="text-xs text-muted-foreground">
                  {field.label}
                </Label>
                <Input
                  id={`${angle.id}-${field.key}`}
                  value={angle[field.key]}
                  maxLength={220}
                  disabled={disabled}
                  onChange={(e) => update(index, field.key, e.target.value)}
                />
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
