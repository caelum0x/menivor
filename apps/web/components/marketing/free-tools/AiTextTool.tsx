"use client";

import { useState } from "react";
import { Loader2, Shuffle, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  MAX_TOPIC_CHARS,
  type GenerateOutput,
  type GeneratorKind,
  type ScriptResult,
} from "@/lib/seo/free-tools/generate";
import { validateGenerateRequest } from "@/lib/seo/free-tools/generate";
import { templateOutput } from "@/lib/seo/free-tools/templates";
import { CopyButton, ErrorNote, SoftCta, ToolPanel, fieldLabel } from "./shared";

interface AiTextToolProps {
  readonly kind: GeneratorKind;
  readonly placeholder: string;
  readonly defaultPlatform?: "tiktok" | "reels" | "shorts" | "youtube";
}

const BUTTON_LABEL: Record<GeneratorKind, string> = {
  hooks: "Generate 10 hooks",
  script: "Write my script",
  hashtags: "Generate hashtags",
  titles: "Generate 10 titles",
  captions: "Generate 10 captions",
  ideas: "Generate 10 video ideas",
};

const CTA_TEXT: Record<GeneratorKind, string> = {
  hooks: "Like a hook? Menivor turns it into a finished vertical video with a voiceover and word-by-word captions.",
  script: "Menivor can voice this script, add footage and burn in karaoke captions for you.",
  hashtags: "Need the video too? Menivor makes ready-to-post reels from a link or a topic.",
  titles: "Menivor writes the title, script, voiceover and captions, then renders the whole video.",
  captions: "Menivor also writes the script, voiceover and captions for the video itself, not just the post caption.",
  ideas: "Picked an idea? Menivor turns it into a finished vertical video with a script, voiceover and captions.",
};

function scriptToText(script: ScriptResult): string {
  const beats = script.beats.map((beat, index) => `${index + 1}. ${beat.say}${beat.show ? `\n   [Show: ${beat.show}]` : ""}`);
  return [`HOOK: ${script.hook}`, "", ...beats, "", `CTA: ${script.cta}`].join("\n");
}

function ResultView({ output, kind }: { readonly output: GenerateOutput; readonly kind: GeneratorKind }) {
  if (output.kind === "script") {
    const { script } = output;
    return (
      <div className="mt-6 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-lg font-semibold">Your script</h3>
          <CopyButton text={scriptToText(script)} label="Copy script" />
        </div>
        <p className="rounded-md bg-primary/10 px-3 py-2"><span className="font-semibold">Hook: </span>{script.hook}</p>
        <ol className="space-y-2">
          {script.beats.map((beat, index) => (
            <li key={`${index}-${beat.say.slice(0, 20)}`} className="rounded-md border border-border px-3 py-2">
              <p>{beat.say}</p>
              {beat.show ? <p className="mt-1 text-sm text-muted-foreground">Show: {beat.show}</p> : null}
            </li>
          ))}
        </ol>
        {script.cta ? <p className="rounded-md bg-primary/10 px-3 py-2"><span className="font-semibold">Call to action: </span>{script.cta}</p> : null}
      </div>
    );
  }
  const joined = output.items.join(kind === "hashtags" ? " " : "\n");
  return (
    <div className="mt-6">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">{output.items.length} results</h3>
        <CopyButton text={joined} label="Copy all" />
      </div>
      {kind === "hashtags" ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {output.items.map((tag) => (
            <span key={tag} className="rounded-full border border-border px-3 py-1 text-sm">{tag}</span>
          ))}
        </div>
      ) : (
        <ol className="mt-3 space-y-2">
          {output.items.map((item, index) => (
            <li key={item} className="flex items-start justify-between gap-3 rounded-md border border-border px-3 py-2">
              <span><span className="mr-2 text-muted-foreground">{index + 1}.</span>{item}</span>
              <CopyButton text={item} label="Copy" />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function AiTextTool({ kind, placeholder, defaultPlatform = "tiktok" }: AiTextToolProps) {
  const [topic, setTopic] = useState("");
  const [platform, setPlatform] = useState<string>(defaultPlatform);
  const [tone, setTone] = useState("bold");
  const [lengthSec, setLengthSec] = useState("30");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [output, setOutput] = useState<GenerateOutput | null>(null);
  const [source, setSource] = useState<"ai" | "template">("ai");
  const [seed, setSeed] = useState(1);

  /** Offline formulas: used when the AI writer is unavailable, and for shuffles. */
  function applyTemplates(nextSeed: number): boolean {
    const request = validateGenerateRequest({ kind, topic, platform, tone, lengthSec: Number(lengthSec) });
    if (!request.ok) {
      setError(request.error);
      return false;
    }
    setOutput(templateOutput(request.value, nextSeed));
    setSource("template");
    setSeed(nextSeed);
    return true;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/tools/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, topic, platform, tone, lengthSec: Number(lengthSec) }),
      });
      const data = (await res.json().catch(() => null)) as { ok?: boolean; output?: GenerateOutput; error?: string } | null;
      if (res.status === 400 && data?.error) {
        setError(data.error);
        return;
      }
      if (!res.ok || !data?.ok || !data.output) {
        applyTemplates(seed + 1);
        return;
      }
      setOutput(data.output);
      setSource("ai");
    } catch {
      applyTemplates(seed + 1);
    } finally {
      setLoading(false);
    }
  }

  const showTone = kind !== "hashtags";
  return (
    <ToolPanel>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor={`topic-${kind}`} className={fieldLabel}>What is your video about?</label>
          <Textarea
            id={`topic-${kind}`}
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder={placeholder}
            maxLength={MAX_TOPIC_CHARS}
            rows={3}
            required
          />
          <p className="mt-1 text-xs text-muted-foreground">{topic.length}/{MAX_TOPIC_CHARS}</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label htmlFor={`platform-${kind}`} className={fieldLabel}>Platform</label>
            <Select id={`platform-${kind}`} value={platform} onChange={(event) => setPlatform(event.target.value)}>
              <option value="tiktok">TikTok</option>
              <option value="reels">Instagram Reels</option>
              <option value="shorts">YouTube Shorts</option>
              {kind === "titles" ? <option value="youtube">YouTube (long-form)</option> : null}
            </Select>
          </div>
          {showTone ? (
            <div>
              <label htmlFor={`tone-${kind}`} className={fieldLabel}>Tone</label>
              <Select id={`tone-${kind}`} value={tone} onChange={(event) => setTone(event.target.value)}>
                <option value="bold">Bold</option>
                <option value="funny">Funny</option>
                <option value="educational">Educational</option>
                <option value="story">Story</option>
                <option value="salesy">Salesy</option>
              </Select>
            </div>
          ) : null}
          {kind === "script" ? (
            <div>
              <label htmlFor="length-script" className={fieldLabel}>Length</label>
              <Select id="length-script" value={lengthSec} onChange={(event) => setLengthSec(event.target.value)}>
                <option value="15">15 seconds</option>
                <option value="30">30 seconds</option>
                <option value="60">60 seconds</option>
              </Select>
            </div>
          ) : null}
        </div>
        <Button type="submit" size="lg" disabled={loading || topic.trim().length < 3}>
          {loading ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
          {loading ? "Writing..." : BUTTON_LABEL[kind]}
        </Button>
      </form>
      {error ? <ErrorNote message={error} /> : null}
      {output ? (
        <>
          {source === "template" ? (
            <div className="mt-5 flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
              <span>
                {kind === "script"
                  ? "Instant script outline from a proven short-form structure. Replace the [brackets] with your specifics."
                  : "Instant results from proven short-form formulas."}
              </span>
              <Button type="button" variant="outline" size="sm" onClick={() => applyTemplates(seed + 1)}>
                <Shuffle className="size-4" /> Shuffle
              </Button>
            </div>
          ) : null}
          <ResultView output={output} kind={kind} />
          <SoftCta text={CTA_TEXT[kind]} />
        </>
      ) : null}
    </ToolPanel>
  );
}
