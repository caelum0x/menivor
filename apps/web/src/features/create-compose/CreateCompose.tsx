"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Clapperboard, Loader2 } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getTemplate, type TemplateDetail } from "@/src/features/templates/api";
import { TemplateComposeForm } from "./TemplateComposeForm";
import { TemplatePicker } from "./TemplatePicker";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/**
 * Top-level create surface. With `?template=<slug>` it loads the template
 * detail and renders the compose form; otherwise it shows the template picker.
 * All data is live — no mock fixtures.
 */
export function CreateCompose() {
  const searchParams = useSearchParams();
  const slug = searchParams.get("template");

  if (!slug) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Pick a genre template to compile a reel from.
        </p>
        <TemplatePicker />
      </div>
    );
  }

  return <TemplateComposeLoader slug={slug} />;
}

function TemplateComposeLoader({ slug }: { slug: string }) {
  const { getToken } = useAuth();
  const [template, setTemplate] = React.useState<TemplateDetail | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    (async () => {
      try {
        const token = (await getToken()) ?? undefined;
        const detail = await getTemplate(slug, { token });
        if (active) setTemplate(detail);
      } catch (err) {
        if (active) {
          setError(
            friendlyErrorMessage(err, "Failed to load this template."),
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [getToken, slug]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading
        template…
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
        <Button asChild variant="outline" size="sm">
          <a href="/create/templates">
            <ArrowLeft className="mr-1 h-4 w-4" aria-hidden /> Back to templates
          </a>
        </Button>
      </div>
    );
  }

  if (!template) return null;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Button asChild variant="ghost" size="sm" className="-ml-2">
          <a href="/create/templates">
            <ArrowLeft className="mr-1 h-4 w-4" aria-hidden /> All templates
          </a>
        </Button>
        <div className="flex items-center gap-2">
          <Clapperboard className="h-5 w-5 text-primary" aria-hidden />
          <h2 className="text-xl font-semibold">{template.name}</h2>
        </div>
        <p className="text-sm text-muted-foreground">{template.description}</p>
        <div className="flex flex-wrap gap-1">
          <Badge variant="secondary">{template.genre}</Badge>
          <Badge variant="outline">{template.aspect}</Badge>
          <Badge variant="outline">{template.caption_style}</Badge>
        </div>
      </div>
      <TemplateComposeForm template={template} />
    </div>
  );
}
