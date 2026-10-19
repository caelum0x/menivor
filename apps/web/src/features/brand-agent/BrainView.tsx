"use client";

import * as React from "react";
import { Brain, Loader2, Pencil } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { getMemory, markBrainSeen, saveMemorySection, type BrandMemory } from "./api";
import { MessageCard } from "./MessageCard";

export const SECTION_TITLES: Record<string, string> = {
  positioning: "Positioning",
  product: "Product",
  market: "Market",
  voice_audience: "Voice and audience",
};

/** Edit a section as JSON (structured, versioned on save). */
function SectionEditor({
  spaceId,
  section,
  data,
  onSaved,
}: {
  spaceId: string;
  section: string;
  data: Record<string, unknown>;
  onSaved: () => void;
}) {
  const requestOptions = useRequestOptions();
  const [value, setValue] = React.useState(() => JSON.stringify(data, null, 2));
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const save = async () => {
    setError("");
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(value) as Record<string, unknown>;
    } catch {
      setError("That is not valid JSON. Check the quotes and commas.");
      return;
    }
    setBusy(true);
    try {
      await saveMemorySection(spaceId, section, parsed, await requestOptions());
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <label htmlFor={`brain-${section}`} className="sr-only">
        Edit {SECTION_TITLES[section]}
      </label>
      <Textarea
        id={`brain-${section}`}
        rows={12}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="font-mono text-xs"
      />
      <ErrorText message={error} />
      <Button type="button" size="sm" onClick={save} disabled={busy}>
        {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} Save as a new version
      </Button>
    </div>
  );
}

/** Brand memory: every section, its version, and an edit path that writes a new version. */
export function BrainView({ spaceId, onSeen }: { spaceId: string; onSeen?: () => void }) {
  const requestOptions = useRequestOptions();
  const [memory, setMemory] = React.useState<BrandMemory | null>(null);
  const [editing, setEditing] = React.useState<string | null>(null);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const opts = await requestOptions();
      setMemory(await getMemory(spaceId, opts));
      await markBrainSeen(spaceId, opts);
      onSeen?.();
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [spaceId, requestOptions, onSeen]);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ErrorText message={error} />;
  if (!memory) return <Loader2 className="size-5 animate-spin text-muted-foreground" aria-label="Loading" />;

  const sections = Object.keys(SECTION_TITLES).filter((s) => memory.sections[s]);
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Brain className="size-5 text-primary" aria-hidden />
        <h2 className="text-lg font-semibold">Brain</h2>
        <span className="text-sm text-muted-foreground">version {memory.version}</span>
      </div>
      {sections.length === 0 && (
        <p className="text-sm text-muted-foreground">Nothing saved yet. Start a session and set up your brand.</p>
      )}
      {sections.map((section) => (
        <section key={section} className="glass-subtle space-y-2 rounded-2xl border border-border p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">
              {SECTION_TITLES[section]}{" "}
              <span className="text-xs text-muted-foreground">v{memory.updated[section]}</span>
            </h3>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setEditing(editing === section ? null : section)}
              aria-label={`Edit ${SECTION_TITLES[section]}`}
            >
              <Pencil className="size-4" aria-hidden />
            </Button>
          </div>
          {editing === section ? (
            <SectionEditor
              spaceId={spaceId}
              section={section}
              data={memory.sections[section] ?? {}}
              onSaved={() => {
                setEditing(null);
                void load();
              }}
            />
          ) : (
            <MessageCard
              card={{ type: "setup_step", step: section, data: memory.sections[section] ?? {} }}
              action={null}
            />
          )}
        </section>
      ))}
    </div>
  );
}
