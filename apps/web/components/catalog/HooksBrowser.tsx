"use client";

import * as React from "react";
import { Check, Copy, Quote } from "lucide-react";
import type { HookCatalog } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useHookCatalog } from "@/components/catalog/use-catalog";
import {
  CardGridSkeleton,
  EmptyState,
  ErrorPanel,
} from "@/components/catalog/states";
import { Pagination, usePaginated } from "@/components/catalog/Pagination";
import { SearchBar } from "@/components/catalog/SearchBar";

const PAGE_SIZE = 20;

interface FlatHook {
  language: string;
  text: string;
}

/** Flatten the language-keyed catalog into a single list for a given language. */
function hooksForLanguage(
  catalog: HookCatalog,
  language: string,
): readonly FlatHook[] {
  const lines = catalog[language] ?? [];
  return lines.map((text) => ({ language, text }));
}

/** Language-tabbed, searchable, paginated browser of native hook lines. */
export function HooksBrowser() {
  const { status, data, error, reload } = useHookCatalog();
  const [query, setQuery] = React.useState("");
  const [language, setLanguage] = React.useState<string>("");

  const catalog = data ?? {};
  const languages = React.useMemo(
    () => Object.keys(catalog).filter((k) => (catalog[k] ?? []).length > 0).sort(),
    [catalog],
  );

  // Default the active language once the catalog resolves.
  React.useEffect(() => {
    const first = languages[0];
    if (first && !languages.includes(language)) {
      setLanguage(first);
    }
  }, [languages, language]);

  const activeLanguage = language || languages[0] || "";
  const hooks = React.useMemo(
    () => hooksForLanguage(catalog, activeLanguage),
    [catalog, activeLanguage],
  );
  const filtered = React.useMemo(() => {
    if (!query) return hooks;
    const q = query.toLowerCase();
    return hooks.filter((h) => h.text.toLowerCase().includes(q));
  }, [hooks, query]);
  const { page, pageCount, pageItems, setPage } = usePaginated(
    filtered,
    PAGE_SIZE,
  );

  if (status === "loading") return <CardGridSkeleton count={6} lines={2} />;
  if (status === "error") {
    return (
      <ErrorPanel
        title="Couldn't load the hook catalog"
        message={error}
        onRetry={reload}
      />
    );
  }
  if (languages.length === 0) {
    return (
      <EmptyState
        title="No hooks"
        message="The hook catalog is empty right now. Check back soon."
        icon={<Quote className="size-6" aria-hidden />}
      />
    );
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap gap-2" role="tablist" aria-label="Hook languages">
        {languages.map((lang) => {
          const active = lang === activeLanguage;
          return (
            <Button
              key={lang}
              role="tab"
              aria-selected={active}
              variant={active ? "default" : "outline"}
              size="sm"
              onClick={() => {
                setLanguage(lang);
                setQuery("");
              }}
            >
              {lang.toUpperCase()}
              <Badge variant={active ? "secondary" : "outline"}>
                {(catalog[lang] ?? []).length}
              </Badge>
            </Button>
          );
        })}
      </div>

      <SearchBar
        value={query}
        onChange={setQuery}
        placeholder={`Search ${activeLanguage.toUpperCase()} hooks`}
        resultLabel={`${filtered.length} of ${hooks.length}`}
        className="mb-6"
      />

      {filtered.length === 0 ? (
        <EmptyState
          title="No matches"
          message={`No hook matches "${query}".`}
          icon={<Quote className="size-6" aria-hidden />}
        />
      ) : (
        <>
          <ul className="grid gap-3 sm:grid-cols-2">
            {pageItems.map((hook, i) => (
              <li key={`${hook.language}-${(page - 1) * PAGE_SIZE + i}`}>
                <HookCard text={hook.text} />
              </li>
            ))}
          </ul>
          <Pagination
            page={page}
            pageCount={pageCount}
            totalItems={filtered.length}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}

function HookCard({ text }: Readonly<{ text: string }>) {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = React.useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be unavailable (insecure context); fail quietly.
    }
  }, [text]);

  return (
    <Card className="h-full">
      <CardContent className="flex h-full items-start justify-between gap-3 p-4">
        <p className="flex-1 text-sm leading-relaxed">
          <Quote
            className="mr-1.5 inline size-3.5 -translate-y-0.5 text-primary"
            aria-hidden
          />
          {text}
        </p>
        <Button
          variant="ghost"
          size="icon"
          onClick={handleCopy}
          aria-label={copied ? "Copied" : "Copy hook"}
          className="size-8 shrink-0"
        >
          {copied ? (
            <Check className="size-4 text-success" aria-hidden />
          ) : (
            <Copy className="size-4" aria-hidden />
          )}
        </Button>
      </CardContent>
    </Card>
  );
}
