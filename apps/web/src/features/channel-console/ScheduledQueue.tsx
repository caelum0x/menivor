"use client";

import * as React from "react";
import { Clock, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatWhen, type ScheduledPost } from "./api";

interface ScheduledQueueProps {
  scheduled: ScheduledPost[];
  loading: boolean;
  error: string;
}

function statusVariant(status: string): "success" | "secondary" | "destructive" {
  if (status === "published" || status === "posted") return "success";
  if (status === "failed" || status === "error") return "destructive";
  return "secondary";
}

/** Read model of the pending / settled scheduled-publish queue. */
export function ScheduledQueue({ scheduled, loading, error }: ScheduledQueueProps) {
  return (
    <section>
      <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
        <Clock className="h-4 w-4" aria-hidden /> Scheduled queue
      </div>

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading queue…
        </p>
      ) : error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : scheduled.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing scheduled yet.</p>
      ) : (
        <div className="space-y-2">
          {scheduled.map((s) => (
            <Card key={s.id}>
              <CardContent className="flex items-center justify-between py-3">
                <div>
                  <p className="font-medium capitalize">{s.platforms.join(", ")}</p>
                  <p className="text-xs text-muted-foreground">
                    job {s.job_id}
                    {s.scheduled_at ? ` · ${formatWhen(s.scheduled_at)}` : ""}
                  </p>
                </div>
                <Badge variant={statusVariant(s.status)}>{s.status}</Badge>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
