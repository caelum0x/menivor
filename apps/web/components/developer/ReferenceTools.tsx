import type * as React from "react";
import Link from "next/link";
import {
  Cpu,
  Gauge,
  GitCompare,
  LineChart,
  TrendingUp,
  Wand2,
  Workflow,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface ReferenceTool {
  readonly href: string;
  readonly title: string;
  readonly blurb: string;
  readonly Icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
}

const TOOLS: readonly ReferenceTool[] = [
  { href: "/hook-lab", title: "Hook score", blurb: "The first-3s signals and the 70% hook gate the pipeline applies.", Icon: Gauge },
  { href: "/ab-lab", title: "A/B winner", blurb: "The retention-weighted score used to promote a variant.", Icon: GitCompare },
  { href: "/retention-lab", title: "Retention tiers", blurb: "How a per-second viewer curve maps to a reach tier and drop-off.", Icon: LineChart },
  { href: "/trend-lab", title: "Trend ranking", blurb: "Opportunity, velocity, and saturation for a usage series.", Icon: TrendingUp },
  { href: "/effects-lab", title: "Effect kernels", blurb: "The camera and VFX animation curves the renderer evaluates.", Icon: Wand2 },
  { href: "/filtergraph", title: "Filtergraph", blurb: "The exact FFmpeg filter_complex a RenderSpec compiles to.", Icon: Workflow },
  { href: "/workflows-lab", title: "Workflow manifests", blurb: "ComfyUI workflow pins and the input validator the API runs.", Icon: Cpu },
];

/**
 * Developer reference for the scoring and render formulas behind the API. Each
 * tool runs the same shared library the pipeline uses, on inputs you type in,
 * so integrators can predict API behaviour before sending real jobs. Nothing is
 * saved or submitted from these pages.
 */
export function ReferenceTools() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Scoring &amp; render reference</CardTitle>
        <CardDescription>
          Interactive versions of the formulas behind the API. They run the same
          code as the pipeline on inputs you enter; nothing is saved.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        {TOOLS.map(({ href, title, blurb, Icon }) => (
          <Link
            key={href}
            href={href}
            className="group flex items-start gap-3 rounded-lg border border-border p-3 transition-colors hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Icon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            <span>
              <span className="block text-sm font-medium group-hover:underline">
                {title}
              </span>
              <span className="block text-xs text-muted-foreground">{blurb}</span>
            </span>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}
