"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Clapperboard, Loader2, Wand2 } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { listTemplates, type TemplateSummary } from "@/src/features/templates/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/**
 * Template chooser shown when `/create` is opened without a `?template=` slug.
 * Loads the live gallery and links each card back into the compose flow.
 */
export function TemplatePicker() {
  const { getToken } = useAuth();
  const [templates, setTemplates] = React.useState<TemplateSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let active = true;
    (async () => {
      try {
        const token = (await getToken()) ?? undefined;
        const res = await listTemplates({ token });
        if (active) setTemplates(res.templates);
      } catch (err) {
        if (active) {
          setError(
            friendlyErrorMessage(err, "Failed to load templates."),
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [getToken]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading
        templates…
      </div>
    );
  }

  if (error) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {error}
      </p>
    );
  }

  if (templates.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No templates are available yet. Check back soon.
      </p>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {templates.map((t) => (
        <Card key={t.slug} className="flex flex-col">
          <CardContent className="flex flex-1 flex-col gap-3 py-5">
            <div className="flex items-center gap-2">
              <Clapperboard className="h-4 w-4 text-primary" aria-hidden />
              <h3 className="font-semibold">{t.name}</h3>
            </div>
            <p className="flex-1 text-sm text-muted-foreground">
              {t.description}
            </p>
            <div className="flex flex-wrap gap-1">
              <Badge variant="secondary">{t.genre}</Badge>
              <Badge variant="outline">{t.aspect}</Badge>
            </div>
            <Button asChild size="sm" className="mt-1 w-full">
              <a href={`/create/templates?template=${encodeURIComponent(t.slug)}`}>
                <Wand2 className="mr-1 h-4 w-4" aria-hidden /> Use template
              </a>
            </Button>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
