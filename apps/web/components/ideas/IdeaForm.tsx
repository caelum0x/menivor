"use client";

import * as React from "react";
import { Loader2, Sparkles } from "lucide-react";
import type { GenerateIdeasRequest, IdeaLanguage } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

interface IdeaFormProps {
  /** Fired with a validated request when the user submits. */
  onGenerate: (req: GenerateIdeasRequest) => void;
  /** Whether a generation is currently in flight. */
  loading: boolean;
}

const COUNT_OPTIONS = [3, 5, 8] as const;

type LanguageChoice = IdeaLanguage | "auto";

const LANGUAGE_CHOICES: readonly { value: LanguageChoice; label: string }[] = [
  { value: "auto", label: "Auto-detect" },
  { value: "tr", label: "Türkçe" },
  { value: "en", label: "English" },
];

const MIN_CONTEXT_LENGTH = 10;

/**
 * The SPARK brief: describe the app/niche (required), optional audience, how
 * many concepts, and the output language. Validates the context length before
 * submitting and disables the button while a generation is in flight.
 */
export function IdeaForm({ onGenerate, loading }: IdeaFormProps) {
  const [appContext, setAppContext] = React.useState("");
  const [audience, setAudience] = React.useState("");
  const [count, setCount] = React.useState<number>(5);
  const [language, setLanguage] = React.useState<LanguageChoice>("auto");
  const [touched, setTouched] = React.useState(false);

  const trimmedContext = appContext.trim();
  const contextValid = trimmedContext.length >= MIN_CONTEXT_LENGTH;

  const handleSubmit = React.useCallback(
    (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setTouched(true);
      if (!contextValid || loading) return;

      const trimmedAudience = audience.trim();
      onGenerate({
        app_context: trimmedContext,
        ...(trimmedAudience ? { audience: trimmedAudience } : {}),
        count,
        language,
      });
    },
    [audience, contextValid, count, language, loading, onGenerate, trimmedContext],
  );

  const showError = touched && !contextValid;

  return (
    <Card>
      <CardContent className="p-6">
        <form className="space-y-5" onSubmit={handleSubmit} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="app-context">Describe your app or niche</Label>
            <Textarea
              id="app-context"
              value={appContext}
              onChange={(e) => setAppContext(e.target.value)}
              placeholder="e.g. A budgeting app that rounds up spare change and auto-invests it for Gen Z users."
              rows={4}
              aria-invalid={showError}
              aria-describedby={showError ? "app-context-error" : undefined}
            />
            {showError ? (
              <p id="app-context-error" className="text-xs text-destructive">
                Add a little more detail (at least {MIN_CONTEXT_LENGTH}{" "}
                characters) so we can tailor the concepts.
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                The more specific you are, the sharper the concepts.
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="audience">
              Target audience{" "}
              <span className="font-normal text-muted-foreground">
                (optional)
              </span>
            </Label>
            <Input
              id="audience"
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
              placeholder="e.g. First-time investors, 18–25"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="count">Ideas</Label>
              <Select
                id="count"
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
              >
                {COUNT_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n} concepts
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="language">Language</Label>
              <Select
                id="language"
                value={language}
                onChange={(e) =>
                  setLanguage(e.target.value as LanguageChoice)
                }
              >
                {LANGUAGE_CHOICES.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="animate-spin" aria-hidden /> Generating…
              </>
            ) : (
              <>
                <Sparkles aria-hidden /> Generate ideas
              </>
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
