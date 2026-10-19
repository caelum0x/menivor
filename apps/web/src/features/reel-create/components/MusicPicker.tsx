"use client";

import * as React from "react";
import { Library, Sparkles } from "lucide-react";
import type { MusicGenerator } from "@/lib/types";
import { listMusicGenerators } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useApiToken } from "@/lib/use-api-token";
import { MusicLibraryList } from "./MusicLibraryList";
import { MusicGenerateForm } from "./MusicGenerateForm";

interface MusicPickerProps {
  /** Currently-selected library track id, or null for "no music". */
  value: string | null;
  onSelect: (musicId: string | null, label: string | null) => void;
  /** Current AI-BGM brief (`music_prompt`), or null when unused. */
  prompt: string | null;
  /** Chosen AI-BGM provider (`bgm_provider`), or null to auto-select. */
  provider: string | null;
  /**
   * Emits the next AI brief + provider. The parent clears the library
   * `music_id` when this is used (the two are mutually exclusive).
   */
  onGenerateChange: (prompt: string | null, provider: string | null) => void;
}

type Tab = "library" | "ai";

/**
 * Background-music step. Always offers the curated library
 * ({@link MusicLibraryList}); when at least one AI-BGM provider is enabled
 * server-side (GET /catalog/music-generators), it additionally exposes a
 * "Generate with AI" tab ({@link MusicGenerateForm}) that turns a text prompt
 * into a custom royalty-free track. Choosing one path clears the other so a job
 * only ever carries a `music_id` OR a `music_prompt`.
 *
 * The generator probe degrades silently: if it is still loading, errors, or
 * returns none, only the library tab is shown — AI generation is purely
 * additive and never blocks picking a track.
 */
export function MusicPicker({
  value,
  onSelect,
  prompt,
  provider,
  onGenerateChange,
}: MusicPickerProps) {
  const getApiToken = useApiToken();
  const [generators, setGenerators] = React.useState<readonly MusicGenerator[]>(
    [],
  );
  // Default to the AI tab when a brief is already in progress (e.g. returning
  // to this step), otherwise the library.
  const [tab, setTab] = React.useState<Tab>(prompt ? "ai" : "library");

  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const token = await getApiToken();
        const list = await listMusicGenerators({ token });
        if (!cancelled) setGenerators(list);
      } catch {
        // AI generation is additive: on any failure fall back to library-only.
        if (!cancelled) setGenerators([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getApiToken]);

  const aiAvailable = generators.length > 0;
  // Guard against showing an AI-only view if the provider list disappears.
  const activeTab: Tab = aiAvailable ? tab : "library";

  return (
    <div className="space-y-4">
      {aiAvailable && (
        <div
          role="tablist"
          aria-label="Background music source"
          className="inline-flex rounded-lg border border-border bg-secondary/30 p-1"
        >
          <TabButton
            selected={activeTab === "library"}
            onClick={() => setTab("library")}
            icon={<Library className="size-4" aria-hidden />}
            label="Music library"
          />
          <TabButton
            selected={activeTab === "ai"}
            onClick={() => setTab("ai")}
            icon={<Sparkles className="size-4" aria-hidden />}
            label="Generate with AI"
          />
        </div>
      )}

      {activeTab === "ai" && aiAvailable ? (
        <MusicGenerateForm
          generators={generators}
          prompt={prompt}
          provider={provider}
          onChange={onGenerateChange}
        />
      ) : (
        <MusicLibraryList value={value} onSelect={onSelect} />
      )}
    </div>
  );
}

interface TabButtonProps {
  selected: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}

function TabButton({ selected, onClick, icon, label }: TabButtonProps) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        selected
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {icon}
      {label}
    </button>
  );
}
