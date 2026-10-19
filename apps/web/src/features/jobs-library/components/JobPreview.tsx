import * as React from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/**
 * Jobs-library auto-looping teaser clip (from `preview_key`) shown on the job-detail
 * page before/besides the full render. Uses the poster frame as the video's
 * `poster` so the first paint is the thumbnail rather than a black box.
 */

export interface JobPreviewProps {
  /** Absolute preview-clip URL (see `lib/job-media.ts`). */
  previewUrl: string;
  /** Optional poster image shown before the clip plays. */
  posterUrl?: string;
}

export function JobPreview({ previewUrl, posterUrl }: Readonly<JobPreviewProps>) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-base">Preview clip</CardTitle>
        <CardDescription>
          A short teaser generated for this reel.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mx-auto w-full max-w-[320px] overflow-hidden rounded-lg border border-border bg-black">
          {/* 9:16 portrait teaser. */}
          <video
            src={previewUrl}
            poster={posterUrl}
            controls
            playsInline
            muted
            loop
            preload="metadata"
            className="aspect-[9/16] h-auto w-full"
          >
            Your browser does not support the video tag.
          </video>
        </div>
      </CardContent>
    </Card>
  );
}
