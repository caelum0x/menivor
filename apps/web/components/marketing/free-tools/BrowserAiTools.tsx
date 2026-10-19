"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Mic, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  chunksToCues,
  chunksToTranscript,
  parseSubtitles,
  serializeSubtitles,
  type TimedChunk,
} from "@/lib/seo/free-tools/subtitles";
import {
  MAX_MEDIA_BYTES,
  createKokoroWorker,
  createWhisperWorker,
  decodeToMono16k,
} from "./browser-workers";
import { CopyButton, DownloadButton, ErrorNote, SoftCta, ToolPanel, downloadBlob, fieldLabel } from "./shared";

type WorkerMessage =
  | { type: "status"; message: string }
  | { type: "progress"; file: string; progress: number }
  | { type: "done"; text?: string; chunks?: TimedChunk[]; blob?: Blob }
  | { type: "error"; message: string };

const LANGUAGES: ReadonlyArray<readonly [string, string]> = [
  ["english", "English"], ["spanish", "Spanish"], ["french", "French"], ["german", "German"],
  ["portuguese", "Portuguese"], ["italian", "Italian"], ["dutch", "Dutch"], ["hindi", "Hindi"],
  ["japanese", "Japanese"], ["korean", "Korean"], ["chinese", "Chinese"], ["arabic", "Arabic"],
  ["russian", "Russian"], ["turkish", "Turkish"], ["indonesian", "Indonesian"], ["polish", "Polish"],
];

function useModelWorker(factory: () => Worker) {
  const ref = useRef<Worker | null>(null);
  useEffect(() => () => ref.current?.terminate(), []);
  return () => {
    if (!ref.current) ref.current = factory();
    return ref.current;
  };
}

function runWorker(
  worker: Worker,
  payload: unknown,
  onStatus: (message: string) => void,
  transfer: Transferable[] = [],
): Promise<Extract<WorkerMessage, { type: "done" }>> {
  return new Promise((resolve, reject) => {
    const progress = new Map<string, number>();
    worker.onmessage = (event: MessageEvent<WorkerMessage>) => {
      const data = event.data;
      if (data.type === "status") onStatus(data.message);
      if (data.type === "progress") {
        progress.set(data.file, data.progress);
        const values = [...progress.values()];
        const avg = values.reduce((sum, value) => sum + value, 0) / values.length;
        onStatus(`Downloading the model (first run only): ${Math.round(avg)}%`);
      }
      if (data.type === "done") resolve(data);
      if (data.type === "error") reject(new Error(data.message));
    };
    worker.onerror = (event) => reject(new Error(event.message || "The in-browser model failed to start. Try a recent Chrome, Edge, Firefox or Safari."));
    worker.postMessage(payload, transfer);
  });
}

interface SpeechToTextProps {
  readonly mode: "subtitles" | "transcript";
}

export function SpeechToText({ mode }: SpeechToTextProps) {
  const getWorker = useModelWorker(createWhisperWorker);
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("english");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const [format, setFormat] = useState<"srt" | "vtt">("srt");

  const subtitleOut = useMemo(
    () => (mode === "subtitles" && text ? serializeSubtitles(parseSubtitles(text), format) : ""),
    [mode, text, format],
  );

  async function start() {
    if (!file) return;
    if (file.size > MAX_MEDIA_BYTES) {
      setError("That file is over 200 MB. Trim it or export the audio only.");
      return;
    }
    setBusy(true);
    setError("");
    setText("");
    const started = performance.now();
    try {
      setStatus("Reading the audio track...");
      const audio = await decodeToMono16k(file);
      const result = await runWorker(getWorker(), { audio, language }, setStatus, [audio.buffer]);
      const chunks = result.chunks ?? [];
      if (mode === "subtitles") {
        setText(serializeSubtitles(chunksToCues(chunks), "srt"));
      } else {
        setText(chunksToTranscript(chunks) || (result.text ?? "").trim());
      }
      setStatus(`Done in ${Math.round((performance.now() - started) / 1000)} s.`);
    } catch (err) {
      setStatus("");
      setError(err instanceof Error ? err.message : "Transcription failed. Try a shorter clip or another browser.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ToolPanel>
      <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
        <div>
          <label htmlFor={`media-${mode}`} className={fieldLabel}>Video or audio file (up to 10 minutes)</label>
          <input
            id={`media-${mode}`}
            type="file"
            accept="video/*,audio/*,.mp4,.mov,.webm,.mp3,.wav,.m4a,.ogg"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            className="block w-full text-sm text-muted-foreground file:mr-3 file:rounded-md file:border file:border-border file:bg-transparent file:px-3 file:py-2 file:text-foreground"
          />
        </div>
        <div>
          <label htmlFor={`lang-${mode}`} className={fieldLabel}>Spoken language</label>
          <Select id={`lang-${mode}`} value={language} onChange={(event) => setLanguage(event.target.value)}>
            {LANGUAGES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Select>
        </div>
      </div>
      <Button type="button" size="lg" className="mt-4" disabled={!file || busy} onClick={start}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
        {busy ? "Working..." : mode === "subtitles" ? "Generate subtitles" : "Convert to text"}
      </Button>
      {status ? <p className="mt-3 text-sm text-muted-foreground" aria-live="polite">{status}</p> : null}
      {error ? <ErrorNote message={error} /> : null}
      {text ? (
        <div className="mt-5">
          <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-medium">{mode === "subtitles" ? "Edit captions (timings are kept)" : "Transcript"}</span>
            <div className="flex flex-wrap gap-2">
              {mode === "subtitles" ? (
                <>
                  <Select aria-label="Download format" value={format} onChange={(event) => setFormat(event.target.value as "srt" | "vtt")} className="h-8 w-24">
                    <option value="srt">SRT</option>
                    <option value="vtt">VTT</option>
                  </Select>
                  <DownloadButton text={subtitleOut} filename={`captions.${format}`} label={`Download .${format}`} type={format === "vtt" ? "text/vtt" : "application/x-subrip"} />
                </>
              ) : (
                <>
                  <CopyButton text={text} />
                  <DownloadButton text={text} filename="transcript.txt" label="Download .txt" />
                </>
              )}
            </div>
          </div>
          <Textarea value={text} onChange={(event) => setText(event.target.value)} rows={12} className="font-mono text-xs" aria-label="Result" />
          <SoftCta text={mode === "subtitles" ? "Want animated word-by-word captions burned into the video? Menivor does that automatically." : "Turn the key points into short videos: Menivor writes, voices and captions them for you."} />
        </div>
      ) : null}
    </ToolPanel>
  );
}

const VOICES: ReadonlyArray<readonly [string, string]> = [
  ["af_heart", "Heart (US, female)"],
  ["af_bella", "Bella (US, female)"],
  ["af_nicole", "Nicole (US, female, soft)"],
  ["am_michael", "Michael (US, male)"],
  ["am_fenrir", "Fenrir (US, male)"],
  ["bf_emma", "Emma (UK, female)"],
  ["bm_george", "George (UK, male)"],
  ["bm_fable", "Fable (UK, male)"],
];
const MAX_TTS_CHARS = 1000;

export function VoiceoverTool() {
  const getWorker = useModelWorker(createKokoroWorker);
  const [text, setText] = useState("Most people scroll past in two seconds. Here is how to make them stop.");
  const [voice, setVoice] = useState("af_heart");
  const [speed, setSpeed] = useState("1");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [audio, setAudio] = useState<{ url: string; blob: Blob } | null>(null);

  useEffect(() => () => { if (audio) URL.revokeObjectURL(audio.url); }, [audio]);

  async function generate() {
    setBusy(true);
    setError("");
    const started = performance.now();
    try {
      const result = await runWorker(getWorker(), { text: text.trim(), voice, speed: Number(speed) }, setStatus);
      if (!result.blob) throw new Error("No audio was produced.");
      setAudio({ url: URL.createObjectURL(result.blob), blob: result.blob });
      setStatus(`Done in ${Math.round((performance.now() - started) / 1000)} s.`);
    } catch (err) {
      setStatus("");
      setError(err instanceof Error ? err.message : "Voice generation failed. Try a recent Chrome, Edge or Firefox.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ToolPanel>
      <label htmlFor="tts-text" className={fieldLabel}>Script</label>
      <Textarea id="tts-text" value={text} onChange={(event) => setText(event.target.value)} maxLength={MAX_TTS_CHARS} rows={5} />
      <p className="mt-1 text-xs text-muted-foreground">{text.length}/{MAX_TTS_CHARS}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="tts-voice" className={fieldLabel}>Voice</label>
          <Select id="tts-voice" value={voice} onChange={(event) => setVoice(event.target.value)}>
            {VOICES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Select>
        </div>
        <div>
          <label htmlFor="tts-speed" className={fieldLabel}>Speed</label>
          <Select id="tts-speed" value={speed} onChange={(event) => setSpeed(event.target.value)}>
            <option value="0.9">0.9x (calm)</option>
            <option value="1">1x</option>
            <option value="1.1">1.1x (short-form pace)</option>
            <option value="1.2">1.2x</option>
          </Select>
        </div>
      </div>
      <Button type="button" size="lg" className="mt-4" disabled={busy || text.trim().length < 2} onClick={generate}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Mic className="size-4" />}
        {busy ? "Generating..." : "Generate voiceover"}
      </Button>
      {status ? <p className="mt-3 text-sm text-muted-foreground" aria-live="polite">{status}</p> : null}
      {error ? <ErrorNote message={error} /> : null}
      {audio ? (
        <div className="mt-5 space-y-3">
          <audio controls src={audio.url} className="w-full" />
          <Button type="button" variant="outline" size="sm" onClick={() => downloadBlob(audio.blob, "voiceover.wav")}>
            Download WAV
          </Button>
          <SoftCta text="Menivor can turn this voiceover into a full vertical video with footage and karaoke captions." />
        </div>
      ) : null}
    </ToolPanel>
  );
}
