"use client";

import { useMemo, useState } from "react";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import {
  detectFormat,
  parseSubtitles,
  scaleCues,
  serializeSubtitles,
  type SubtitleFormat,
} from "@/lib/seo/free-tools/subtitles";
import { CopyButton, DownloadButton, ErrorNote, SoftCta, ToolPanel, fieldLabel, readTextFile } from "./shared";

const SAMPLE = `1
00:00:01,000 --> 00:00:03,200
Most viewers watch with the sound off.

2
00:00:03,400 --> 00:00:06,000
So every short needs captions.
`;

const FPS_OPTIONS = ["23.976", "24", "25", "29.97", "30"] as const;

interface SubtitleInputProps {
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly id: string;
}

function SubtitleInput({ value, onChange, id }: SubtitleInputProps) {
  const [error, setError] = useState("");
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={id} className="text-sm font-medium">Paste subtitles or choose a file</label>
        <input
          type="file"
          accept=".srt,.vtt,text/vtt,application/x-subrip"
          aria-label="Choose an SRT or VTT file"
          className="text-sm text-muted-foreground file:mr-3 file:rounded-md file:border file:border-border file:bg-transparent file:px-3 file:py-1 file:text-foreground"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            try {
              setError("");
              onChange(await readTextFile(file));
            } catch (err) {
              setError(err instanceof Error ? err.message : "Could not read that file.");
            }
          }}
        />
      </div>
      <Textarea id={id} value={value} onChange={(event) => onChange(event.target.value)} rows={10} className="font-mono text-xs" spellCheck={false} />
      {error ? <ErrorNote message={error} /> : null}
    </div>
  );
}

function OutputBlock({ text, format, base }: { readonly text: string; readonly format: SubtitleFormat; readonly base: string }) {
  const mime = format === "vtt" ? "text/vtt" : "application/x-subrip";
  return (
    <div className="mt-5">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium">Result ({format.toUpperCase()})</span>
        <div className="flex gap-2">
          <CopyButton text={text} />
          <DownloadButton text={text} filename={`${base}.${format}`} label={`Download .${format}`} type={mime} />
        </div>
      </div>
      <Textarea readOnly value={text} rows={10} className="font-mono text-xs" aria-label="Converted subtitles" />
    </div>
  );
}

export function SrtVttConverter() {
  const [input, setInput] = useState(SAMPLE);
  const inputFormat = detectFormat(input);
  const [target, setTarget] = useState<SubtitleFormat>("vtt");
  const cues = useMemo(() => parseSubtitles(input), [input]);
  const output = useMemo(() => serializeSubtitles(cues, target), [cues, target]);
  return (
    <ToolPanel>
      <SubtitleInput id="srt-vtt-input" value={input} onChange={setInput} />
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <p className="text-sm text-muted-foreground">
          Detected: <strong className="text-foreground">{inputFormat.toUpperCase()}</strong>, {cues.length} cues
        </p>
        <div className="w-40">
          <label htmlFor="srt-vtt-target" className={fieldLabel}>Convert to</label>
          <Select id="srt-vtt-target" value={target} onChange={(event) => setTarget(event.target.value as SubtitleFormat)}>
            <option value="vtt">WebVTT (.vtt)</option>
            <option value="srt">SubRip (.srt)</option>
          </Select>
        </div>
      </div>
      {input.trim() && cues.length === 0 ? <ErrorNote message="No subtitle cues found. Each cue needs a line like 00:00:01,000 --> 00:00:03,000." /> : null}
      <OutputBlock text={output} format={target} base="subtitles" />
    </ToolPanel>
  );
}

export function SubtitleShifter() {
  const [input, setInput] = useState(SAMPLE);
  const [offset, setOffset] = useState("1.5");
  const [fromFps, setFromFps] = useState("25");
  const [toFps, setToFps] = useState("25");
  const [target, setTarget] = useState<SubtitleFormat | "same">("same");
  const cues = useMemo(() => parseSubtitles(input), [input]);
  const offsetMs = Math.round((Number(offset) || 0) * 1000);
  // Subtitles timed at `fromFps` played against a `toFps` video: t' = t * from / to.
  const factor = Number(fromFps) / Number(toFps);
  const format: SubtitleFormat = target === "same" ? detectFormat(input) : target;
  const output = useMemo(
    () => serializeSubtitles(scaleCues(cues, factor, offsetMs), format),
    [cues, factor, offsetMs, format],
  );
  return (
    <ToolPanel>
      <SubtitleInput id="shift-input" value={input} onChange={setInput} />
      <div className="mt-4 grid gap-3 sm:grid-cols-4">
        <div>
          <label htmlFor="shift-offset" className={fieldLabel}>Offset (seconds)</label>
          <Input id="shift-offset" type="number" step="0.001" value={offset} onChange={(event) => setOffset(event.target.value)} />
        </div>
        <div>
          <label htmlFor="shift-from" className={fieldLabel}>Subtitle fps</label>
          <Select id="shift-from" value={fromFps} onChange={(event) => setFromFps(event.target.value)}>
            {FPS_OPTIONS.map((fps) => <option key={fps} value={fps}>{fps}</option>)}
          </Select>
        </div>
        <div>
          <label htmlFor="shift-to" className={fieldLabel}>Video fps</label>
          <Select id="shift-to" value={toFps} onChange={(event) => setToFps(event.target.value)}>
            {FPS_OPTIONS.map((fps) => <option key={fps} value={fps}>{fps}</option>)}
          </Select>
        </div>
        <div>
          <label htmlFor="shift-format" className={fieldLabel}>Output</label>
          <Select id="shift-format" value={target} onChange={(event) => setTarget(event.target.value as SubtitleFormat | "same")}>
            <option value="same">Same as input</option>
            <option value="srt">SRT</option>
            <option value="vtt">VTT</option>
          </Select>
        </div>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">
        {cues.length} cues. Positive offset delays subtitles; negative shows them earlier.
        {factor !== 1 ? ` Timings stretched by ${factor.toFixed(5)}.` : ""}
      </p>
      <OutputBlock text={output} format={format} base="subtitles-shifted" />
      <SoftCta text="Tired of fixing caption timing? Menivor times captions to each spoken word automatically." />
    </ToolPanel>
  );
}
