"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  BITRATE_PRESETS,
  PLATFORM_SPECS,
  SPEAKING_PACE_PRESETS,
  bitsPerPixel,
  durationForWords,
  fileSizeMB,
  fitFrame,
  parseDuration,
  parseRatio,
  simplifyRatio,
  solveDimension,
  videoBitrateForSize,
  wordsForDuration,
} from "@/lib/seo/free-tools/video-math";
import { SoftCta, ToolPanel, fieldLabel } from "./shared";

function num(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function Stat({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="rounded-md border border-border px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

export function AspectRatioCalculator() {
  const [ratio, setRatio] = useState("9:16");
  const [side, setSide] = useState<"width" | "height">("width");
  const [size, setSize] = useState("1080");
  const [w, setW] = useState("1080");
  const [h, setH] = useState("1350");
  const [srcW, setSrcW] = useState("1920");
  const [srcH, setSrcH] = useState("1080");

  const parsed = parseRatio(ratio);
  const solved = parsed ? solveDimension(parsed, side === "width" ? { width: num(size) } : { height: num(size) }) : null;
  const source = { width: num(srcW), height: num(srcH) };
  const target = { width: 1080, height: 1920 };
  const valid = source.width > 0 && source.height > 0;
  const pad = valid ? fitFrame(source, target, "pad") : null;
  const crop = valid ? fitFrame(source, target, "crop") : null;

  return (
    <ToolPanel>
      <h3 className="text-lg font-semibold">Solve width or height</h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div>
          <label htmlFor="ar-ratio" className={fieldLabel}>Aspect ratio</label>
          <Input id="ar-ratio" value={ratio} onChange={(event) => setRatio(event.target.value)} placeholder="9:16" />
        </div>
        <div>
          <label htmlFor="ar-side" className={fieldLabel}>I know the</label>
          <Select id="ar-side" value={side} onChange={(event) => setSide(event.target.value as "width" | "height")}>
            <option value="width">Width</option>
            <option value="height">Height</option>
          </Select>
        </div>
        <div>
          <label htmlFor="ar-size" className={fieldLabel}>Pixels</label>
          <Input id="ar-size" type="number" min={2} value={size} onChange={(event) => setSize(event.target.value)} />
        </div>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Stat label="Resolution (even pixels)" value={solved ? `${solved.width} x ${solved.height}` : "Enter a ratio like 9:16"} />
        <Stat label="Megapixels" value={solved ? (solved.width * solved.height / 1e6).toFixed(2) : "-"} />
      </div>

      <h3 className="mt-8 text-lg font-semibold">Find the ratio of a resolution</h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div>
          <label htmlFor="ar-w" className={fieldLabel}>Width</label>
          <Input id="ar-w" type="number" min={1} value={w} onChange={(event) => setW(event.target.value)} />
        </div>
        <div>
          <label htmlFor="ar-h" className={fieldLabel}>Height</label>
          <Input id="ar-h" type="number" min={1} value={h} onChange={(event) => setH(event.target.value)} />
        </div>
        <Stat label="Aspect ratio" value={simplifyRatio(num(w), num(h)) || "-"} />
      </div>

      <h3 className="mt-8 text-lg font-semibold">Fit footage into a 1080 x 1920 vertical frame</h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="ar-sw" className={fieldLabel}>Source width</label>
          <Input id="ar-sw" type="number" min={1} value={srcW} onChange={(event) => setSrcW(event.target.value)} />
        </div>
        <div>
          <label htmlFor="ar-sh" className={fieldLabel}>Source height</label>
          <Input id="ar-sh" type="number" min={1} value={srcH} onChange={(event) => setSrcH(event.target.value)} />
        </div>
      </div>
      {pad && crop ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Stat label="Pad (whole frame visible)" value={`${pad.width} x ${pad.height}, bars ${pad.padX || pad.padY}px`} />
          <Stat label="Crop to fill" value={`scale to ${crop.width} x ${crop.height}, trim ${crop.padX || crop.padY}px`} />
        </div>
      ) : null}
      <SoftCta text="Menivor renders every video at 1080 x 1920 with captions kept inside the platform safe zones." />
    </ToolPanel>
  );
}

export function BitrateCalculator() {
  const [mode, setMode] = useState<"size" | "bitrate">("size");
  const [duration, setDuration] = useState("1:00");
  const [videoKbps, setVideoKbps] = useState("8000");
  const [audioKbps, setAudioKbps] = useState("128");
  const [targetMB, setTargetMB] = useState("50");
  const [preset, setPreset] = useState(0);

  const seconds = parseDuration(duration) ?? 0;
  const audio = num(audioKbps);
  const video = mode === "size" ? num(videoKbps) : videoBitrateForSize(num(targetMB), seconds, audio);
  const sizeMB = fileSizeMB(video, audio, seconds);
  const current = BITRATE_PRESETS[preset] ?? BITRATE_PRESETS[0];
  const bpp = current ? bitsPerPixel(video, current.width, current.height, current.fps) : 0;

  return (
    <ToolPanel>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="br-mode" className={fieldLabel}>Calculate</label>
          <Select id="br-mode" value={mode} onChange={(event) => setMode(event.target.value as "size" | "bitrate")}>
            <option value="size">File size from bitrate</option>
            <option value="bitrate">Bitrate for a target file size</option>
          </Select>
        </div>
        <div>
          <label htmlFor="br-duration" className={fieldLabel}>Duration (seconds or mm:ss)</label>
          <Input id="br-duration" value={duration} onChange={(event) => setDuration(event.target.value)} />
        </div>
        {mode === "size" ? (
          <div>
            <label htmlFor="br-video" className={fieldLabel}>Video bitrate (kbps)</label>
            <Input id="br-video" type="number" min={0} value={videoKbps} onChange={(event) => setVideoKbps(event.target.value)} />
          </div>
        ) : (
          <div>
            <label htmlFor="br-target" className={fieldLabel}>Target file size (MB)</label>
            <Input id="br-target" type="number" min={0} step="0.1" value={targetMB} onChange={(event) => setTargetMB(event.target.value)} />
          </div>
        )}
        <div>
          <label htmlFor="br-audio" className={fieldLabel}>Audio bitrate (kbps)</label>
          <Input id="br-audio" type="number" min={0} value={audioKbps} onChange={(event) => setAudioKbps(event.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="br-preset" className={fieldLabel}>Resolution for the quality check</label>
          <Select id="br-preset" value={String(preset)} onChange={(event) => setPreset(Number(event.target.value))}>
            {BITRATE_PRESETS.map((item, index) => <option key={item.label} value={index}>{item.label}</option>)}
          </Select>
        </div>
      </div>
      {seconds <= 0 ? <p className="mt-3 text-sm text-destructive">Enter a duration such as 45 or 1:30.</p> : null}
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Stat label="Video bitrate" value={`${Math.round(video).toLocaleString("en-US")} kbps`} />
        <Stat label="File size" value={`${sizeMB.toFixed(1)} MB`} />
        <Stat label="Bits per pixel" value={bpp ? bpp.toFixed(3) : "-"} />
      </div>
      {current ? (
        <p className="mt-3 text-sm text-muted-foreground">
          Recommended H.264 upload bitrate for {current.label}: {current.minKbps.toLocaleString("en-US")} to {current.maxKbps.toLocaleString("en-US")} kbps.
          {video > 0 && video < current.minKbps * 0.5 ? " Your bitrate is well below that, so expect visible artifacts on motion." : ""}
        </p>
      ) : null}
      <SoftCta text="Menivor exports upload-ready 1080 x 1920 MP4s, so you never have to tune encoder settings." />
    </ToolPanel>
  );
}

function formatMinutesSeconds(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function ScriptLengthCalculator() {
  const [mode, setMode] = useState<"duration" | "words">("duration");
  const [duration, setDuration] = useState("1:00");
  const [words, setWords] = useState("150");
  const [paceIndex, setPaceIndex] = useState(1);

  const pace = SPEAKING_PACE_PRESETS[paceIndex] ?? SPEAKING_PACE_PRESETS[1];
  const seconds = parseDuration(duration) ?? 0;
  const wordCount = num(words);
  const wpm = pace?.wpm ?? 150;

  const resultWords = mode === "duration" ? wordsForDuration(seconds, wpm) : wordCount;
  const resultSeconds = mode === "words" ? durationForWords(wordCount, wpm) : seconds;

  return (
    <ToolPanel>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="sl-mode" className={fieldLabel}>Calculate</label>
          <Select id="sl-mode" value={mode} onChange={(event) => setMode(event.target.value as "duration" | "words")}>
            <option value="duration">Word count from video length</option>
            <option value="words">Video length from word count</option>
          </Select>
        </div>
        <div>
          <label htmlFor="sl-pace" className={fieldLabel}>Speaking pace</label>
          <Select id="sl-pace" value={String(paceIndex)} onChange={(event) => setPaceIndex(Number(event.target.value))}>
            {SPEAKING_PACE_PRESETS.map((preset, index) => (
              <option key={preset.label} value={index}>{preset.label} ({preset.wpm} wpm)</option>
            ))}
          </Select>
        </div>
        {mode === "duration" ? (
          <div>
            <label htmlFor="sl-duration" className={fieldLabel}>Video length (seconds or mm:ss)</label>
            <Input id="sl-duration" value={duration} onChange={(event) => setDuration(event.target.value)} />
          </div>
        ) : (
          <div>
            <label htmlFor="sl-words" className={fieldLabel}>Script word count</label>
            <Input id="sl-words" type="number" min={0} value={words} onChange={(event) => setWords(event.target.value)} />
          </div>
        )}
      </div>
      {mode === "duration" && seconds <= 0 ? (
        <p className="mt-3 text-sm text-destructive">Enter a video length such as 45 or 1:30.</p>
      ) : null}
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Stat label="Script word count" value={`${resultWords.toLocaleString("en-US")} words`} />
        <Stat label="Video length" value={formatMinutesSeconds(resultSeconds)} />
      </div>
      <SoftCta text="Menivor turns a script like this straight into a rendered 1080 x 1920 video with AI voiceover and synced captions." />
    </ToolPanel>
  );
}

/** Static spec table, rendered server-side on the aspect ratio page. */
export function PlatformSpecTable() {
  return (
    <div className="mt-10 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="mb-3 text-left text-lg font-semibold text-foreground">Recommended upload sizes</caption>
        <thead className="text-muted-foreground">
          <tr><th className="py-2 pr-4">Placement</th><th className="py-2 pr-4">Ratio</th><th className="py-2 pr-4">Pixels</th><th className="py-2">Note</th></tr>
        </thead>
        <tbody>
          {PLATFORM_SPECS.map((spec) => (
            <tr key={spec.key} className="border-t border-border">
              <td className="py-2 pr-4 font-medium">{spec.name}</td>
              <td className="py-2 pr-4">{spec.ratio}</td>
              <td className="py-2 pr-4 tabular-nums">{spec.width} x {spec.height}</td>
              <td className="py-2 text-muted-foreground">{spec.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Static bitrate table, rendered server-side on the bitrate page. */
export function BitrateTable() {
  return (
    <div className="mt-10 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="mb-3 text-left text-lg font-semibold text-foreground">Typical H.264 upload bitrates and size per minute</caption>
        <thead className="text-muted-foreground">
          <tr><th className="py-2 pr-4">Format</th><th className="py-2 pr-4">Bitrate</th><th className="py-2">Size per minute (with 128 kbps audio)</th></tr>
        </thead>
        <tbody>
          {BITRATE_PRESETS.map((item) => (
            <tr key={item.label} className="border-t border-border">
              <td className="py-2 pr-4 font-medium">{item.label}</td>
              <td className="py-2 pr-4 tabular-nums">{item.minKbps / 1000} to {item.maxKbps / 1000} Mbps</td>
              <td className="py-2 tabular-nums">{fileSizeMB(item.minKbps, 128, 60).toFixed(0)} to {fileSizeMB(item.maxKbps, 128, 60).toFixed(0)} MB</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
